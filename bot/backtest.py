"""
30-day backtest on real Bybit historical data.
Run: python bot/backtest.py
No API key needed — uses public OHLCV endpoint.
"""
import time
from datetime import datetime, timedelta, timezone

import ccxt

from strategy import get_signal

PAIR      = "BTC/USDT"
TIMEFRAME = "15m"
DAYS      = 30
SL_PCT    = -0.05
TP_PCT    =  0.08
SIZE_PCT  =  0.50
START     = 20.0
FEES      =  0.001  # 0.1% per leg


def run() -> None:
    ex    = ccxt.bybit()
    since = int((datetime.now(timezone.utc) - timedelta(days=DAYS)).timestamp() * 1000)

    print(f"Fetching {DAYS}d of {PAIR} {TIMEFRAME} candles from Bybit...")
    all_candles: list = []
    while True:
        batch = ex.fetch_ohlcv(PAIR, TIMEFRAME, since=since, limit=1000)
        if not batch:
            break
        all_candles.extend(batch)
        since = batch[-1][0] + 1
        if len(batch) < 1000:
            break
        time.sleep(0.2)

    print(f"Fetched {len(all_candles)} candles")

    portfolio = START
    position  = None  # {"entry": float, "size_usdt": float}
    trades    = []
    wins = losses = 0

    for i in range(60, len(all_candles)):
        window = all_candles[i - 60: i + 1]
        price  = float(window[-1][4])  # close

        if position:
            pnl_pct = (price - position["entry"]) / position["entry"]
            if pnl_pct <= SL_PCT or pnl_pct >= TP_PCT:
                reason = "tp" if pnl_pct >= TP_PCT else "sl"
                fee    = position["size_usdt"] * FEES
                pnl    = position["size_usdt"] * pnl_pct - fee
                portfolio += pnl
                trades.append({"reason": reason, "pnl": pnl, "pnl_pct": pnl_pct})
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                position = None
            continue

        signal = get_signal(window)
        if signal == "BUY":
            size = portfolio * SIZE_PCT
            if size < 1.0:
                break
            fee = size * FEES
            portfolio -= fee
            position = {"entry": price, "size_usdt": size}

    # Close any open position at last price
    if position:
        price   = float(all_candles[-1][4])
        pnl_pct = (price - position["entry"]) / position["entry"]
        fee     = position["size_usdt"] * FEES
        pnl     = position["size_usdt"] * pnl_pct - fee
        portfolio += pnl
        trades.append({"reason": "open_at_end", "pnl": pnl, "pnl_pct": pnl_pct})

    total_pnl = portfolio - START
    win_rate  = wins / len(trades) * 100 if trades else 0
    max_dd    = min((t["pnl_pct"] for t in trades), default=0) * 100

    print(f"\n{'─'*40}")
    print(f"Backtest: {DAYS}d {PAIR} {TIMEFRAME}")
    print(f"Trades:   {len(trades)} | Wins: {wins} | Losses: {losses}")
    print(f"Win rate: {win_rate:.1f}%")
    print(f"P&L:      ${total_pnl:+.4f} ({total_pnl/START*100:+.1f}%)")
    print(f"Final:    ${portfolio:.4f}")
    print(f"Max loss: {max_dd:.1f}%")
    print(f"{'─'*40}")

    if total_pnl > 0:
        print("✅ Strategy was profitable over this period.")
    else:
        print("❌ Strategy lost money over this period. Consider adjusting before going live.")


if __name__ == "__main__":
    run()
