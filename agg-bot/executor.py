import asyncio
import logging
from datetime import datetime, timezone

import ccxt

import db

logger = logging.getLogger(__name__)

PAIR         = "BTC/USDT"
POSITION_PCT = 0.90   # 90% of portfolio per trade — aggressive
TP_PCT       = 0.20   # sell at +20%
MIN_ORDER    = 5.0    # Bybit spot minimum notional (USDT)

# Alert thresholds — no auto-sell, just notify
DRAWDOWN_ALERTS = [-0.15, -0.25, -0.40]


def _make_exchange(api_key: str, secret: str, testnet: bool) -> ccxt.bybit:
    ex = ccxt.bybit({
        "apiKey": api_key,
        "secret": secret,
        "options": {"defaultType": "spot"},
    })
    if testnet:
        ex.set_sandbox_mode(True)
    return ex


async def get_balance(exchange: ccxt.bybit) -> float:
    bal = await asyncio.to_thread(exchange.fetch_balance)
    return float(bal.get("USDT", {}).get("free", 0))


async def get_btc_balance(exchange: ccxt.bybit) -> float:
    bal = await asyncio.to_thread(exchange.fetch_balance)
    return float(bal.get("BTC", {}).get("free", 0))


async def get_total_portfolio(exchange: ccxt.bybit) -> float:
    bal  = await asyncio.to_thread(exchange.fetch_balance)
    usdt = float(bal.get("USDT", {}).get("free", 0))
    btc  = float(bal.get("BTC",  {}).get("free", 0))
    if btc > 0:
        ticker = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
        return usdt + btc * float(ticker["last"])
    return usdt


async def place_buy(exchange: ccxt.bybit) -> dict | None:
    usdt = await get_balance(exchange)
    size = round(usdt * POSITION_PCT, 2)

    if size < MIN_ORDER:
        logger.warning("Balance too low to place order: %.2f USDT", usdt)
        return None

    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    btc_price = float(ticker["last"])
    btc_qty   = round(size / btc_price, 6)

    order = await asyncio.to_thread(exchange.create_market_buy_order, PAIR, btc_qty)
    ts    = datetime.now(timezone.utc).isoformat()
    price = float(order.get("average") or order.get("price") or btc_price)
    trade_id = db.open_trade(ts, PAIR, "buy", size, price)
    logger.info("AGG BUY: %.2f USDT @ %.2f | trade_id=%d", size, price, trade_id)
    return {"trade_id": trade_id, "price": price, "size_usdt": size}


async def check_tp(exchange: ccxt.bybit, position: dict) -> bool:
    ticker  = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    current = float(ticker["last"])
    pnl_pct = (current - position["entry_price"]) / position["entry_price"]
    return pnl_pct >= TP_PCT


async def check_drawdown_alerts(exchange: ccxt.bybit, position: dict, alerted: set) -> tuple[str | None, float]:
    """Returns (alert_message, current_pnl_pct) if a new drawdown threshold crossed."""
    ticker  = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    current = float(ticker["last"])
    pnl_pct = (current - position["entry_price"]) / position["entry_price"]

    for threshold in DRAWDOWN_ALERTS:
        if pnl_pct <= threshold and threshold not in alerted:
            alerted.add(threshold)
            msg = (
                f"⚠️ DRAWDOWN ALERT  —  AGG BOT\n"
                f"Position at {pnl_pct*100:.1f}% (threshold: {threshold*100:.0f}%)\n"
                f"Entry: ${position['entry_price']:,.2f} | Now: ${current:,.2f}\n"
                f"Holding as planned — no auto-sell. /aggstatus for details."
            )
            return msg, pnl_pct

    return None, pnl_pct


async def close_position(exchange: ccxt.bybit, position: dict, reason: str) -> dict:
    btc        = await get_btc_balance(exchange)
    order      = await asyncio.to_thread(exchange.create_market_sell_order, PAIR, btc)
    exit_price = float(order.get("average") or order.get("price") or 0)
    pnl        = (exit_price - position["entry_price"]) / position["entry_price"] * position["size_usdt"]
    db.close_trade(position["id"], exit_price, reason, round(pnl, 4))
    logger.info("AGG CLOSE (%s): exit=%.2f pnl=%.4f", reason, exit_price, pnl)
    return {"exit_price": exit_price, "pnl_usdt": pnl, "reason": reason}


async def reconcile(exchange: ccxt.bybit) -> str | None:
    position = db.get_open_position()
    btc      = await get_btc_balance(exchange)
    ticker   = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    has_btc  = btc * float(ticker["last"]) > MIN_ORDER * 0.5

    if position and not has_btc:
        return "mismatch_no_btc"
    if not position and has_btc:
        return "mismatch_unknown_btc"
    return None
