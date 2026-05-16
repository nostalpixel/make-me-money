import pandas as pd
import ta


RSI_PERIOD = 14
RSI_BUY    = 45   # loosened from 30 — RSI rarely hits 30 in bull markets
RSI_SELL   = 65   # loosened from 70


def get_signal(ohlcv: list[list]) -> tuple[str, float, float, str]:
    """
    Returns (signal, rsi, macd_hist, reason).
    signal is 'BUY', 'SELL', or 'HOLD'.
    """
    if len(ohlcv) < 40:  # need enough candles for MACD(12,26,9)
        return "HOLD", 0.0, 0.0, "not enough candles"

    # Drop last candle — it's still forming and causes repainting false signals
    ohlcv = ohlcv[:-1]

    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["close"] = df["close"].astype(float)

    rsi  = ta.momentum.RSIIndicator(df["close"], window=RSI_PERIOD).rsi()
    macd = ta.trend.MACD(df["close"])
    hist = macd.macd_diff()

    last_rsi  = float(rsi.iloc[-1])
    last_hist = float(hist.iloc[-1])

    if last_rsi < RSI_BUY and last_hist > 0:
        reason = f"RSI {last_rsi:.1f} < {RSI_BUY} and MACD hist {last_hist:+.2f} > 0 → bullish"
        return "BUY", last_rsi, last_hist, reason

    if last_rsi > RSI_SELL and last_hist < 0:
        reason = f"RSI {last_rsi:.1f} > {RSI_SELL} and MACD hist {last_hist:+.2f} < 0 → bearish"
        return "SELL", last_rsi, last_hist, reason

    parts = []
    if last_rsi >= RSI_BUY:
        parts.append(f"RSI {last_rsi:.1f} not below {RSI_BUY}")
    if last_hist <= 0:
        parts.append(f"MACD hist {last_hist:+.2f} not positive")
    reason = "; ".join(parts) if parts else f"RSI {last_rsi:.1f}, MACD hist {last_hist:+.2f}"
    return "HOLD", last_rsi, last_hist, reason
