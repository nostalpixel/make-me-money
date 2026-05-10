import asyncio
import logging
from datetime import datetime, timezone

import ccxt

import db

logger = logging.getLogger(__name__)

PAIR        = "BTC/USDT"
POSITION_PCT = 0.50   # 50% of portfolio per trade
SL_PCT      = -0.05
TP_PCT      =  0.08
MIN_ORDER   =  5.0    # Bybit spot minimum notional (USDT)


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
    """Returns available USDT balance."""
    bal = await asyncio.to_thread(exchange.fetch_balance)
    return float(bal.get("USDT", {}).get("free", 0))


async def get_btc_balance(exchange: ccxt.bybit) -> float:
    """Returns free BTC balance (for spot reconciliation)."""
    bal = await asyncio.to_thread(exchange.fetch_balance)
    return float(bal.get("BTC", {}).get("free", 0))


async def place_buy(exchange: ccxt.bybit) -> dict | None:
    """Buy BTC/USDT with 50% of available USDT. Returns order info or None."""
    usdt = await get_balance(exchange)
    size = round(usdt * POSITION_PCT, 2)

    if size < MIN_ORDER:
        logger.warning("Balance too low to place order: %.2f USDT", usdt)
        return None

    order = await asyncio.to_thread(
        exchange.create_market_buy_order, PAIR, None, {"quoteOrderQty": size}
    )
    ts = datetime.now(timezone.utc).isoformat()
    price = float(order.get("average") or order.get("price") or 0)
    trade_id = db.open_trade(ts, PAIR, "buy", size, price)
    logger.info("BUY executed: %.2f USDT @ %.2f | trade_id=%d", size, price, trade_id)
    return {"trade_id": trade_id, "price": price, "size_usdt": size}


async def check_sl_tp(exchange: ccxt.bybit, position: dict) -> str | None:
    """
    Checks current price against SL/TP for an open position.
    Returns 'stop_loss', 'take_profit', or None.
    """
    ticker = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    current = float(ticker["last"])
    entry   = position["entry_price"]
    pnl_pct = (current - entry) / entry

    if pnl_pct <= SL_PCT:
        return "stop_loss"
    if pnl_pct >= TP_PCT:
        return "take_profit"
    return None


async def close_position(exchange: ccxt.bybit, position: dict, reason: str) -> dict:
    """Sells all BTC and closes the position in DB."""
    btc = await get_btc_balance(exchange)
    order = await asyncio.to_thread(exchange.create_market_sell_order, PAIR, btc)
    exit_price = float(order.get("average") or order.get("price") or 0)
    pnl = (exit_price - position["entry_price"]) / position["entry_price"] * position["size_usdt"]
    db.close_trade(position["id"], exit_price, reason, round(pnl, 4))
    logger.info("CLOSE (%s): exit=%.2f pnl=%.4f", reason, exit_price, pnl)
    return {"exit_price": exit_price, "pnl_usdt": pnl, "reason": reason}


async def reconcile(exchange: ccxt.bybit) -> None:
    """
    Spot reconciliation: compare DB open position vs actual BTC balance.
    For spot, position = BTC balance > dust threshold.
    """
    position = db.get_open_position()
    btc = await get_btc_balance(exchange)
    has_btc = btc * 50000 > MIN_ORDER  # rough notional check

    if position and not has_btc:
        logger.error("MISMATCH: DB shows open position but no BTC on exchange")
        return "mismatch_no_btc"
    if not position and has_btc:
        logger.warning("MISMATCH: BTC on exchange but no open position in DB")
        return "mismatch_unknown_btc"
    return None
