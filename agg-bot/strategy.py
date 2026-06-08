import pandas as pd

DIP_WINDOW_CANDLES = 16   # 16 × 15m = 4h lookback
DIP_THRESHOLD      = 0.05  # 5% drop triggers buy


def get_dip(ohlcv: list[list]) -> tuple[bool, float, str]:
    """
    Returns (is_dip, drop_pct, reason).
    is_dip=True when BTC dropped >= DIP_THRESHOLD in the last 4h.
    Drop last candle (still forming).
    """
    if len(ohlcv) < DIP_WINDOW_CANDLES + 1:
        return False, 0.0, "not enough candles"

    candles = ohlcv[:-1]  # drop live candle
    window  = candles[-DIP_WINDOW_CANDLES:]

    df     = pd.DataFrame(window, columns=["ts", "open", "high", "low", "close", "volume"])
    df["close"] = df["close"].astype(float)

    price_start = float(df["close"].iloc[0])
    price_now   = float(df["close"].iloc[-1])
    drop_pct    = (price_now - price_start) / price_start  # negative = drop

    if drop_pct <= -DIP_THRESHOLD:
        reason = f"BTC dropped {drop_pct*100:.1f}% in 4h (${price_start:,.0f} → ${price_now:,.0f})"
        return True, drop_pct, reason

    reason = f"drop only {drop_pct*100:.1f}% in 4h — need ≥ -{DIP_THRESHOLD*100:.0f}%"
    return False, drop_pct, reason
