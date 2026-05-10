import pandas as pd
import ta


RSI_PERIOD = 14
RSI_BUY    = 45   # loosened from 30 — RSI rarely hits 30 in bull markets
RSI_SELL   = 65   # loosened from 70


def get_signal(ohlcv: list[list]) -> str:
    """
    Pure function. Returns 'BUY', 'SELL', or 'HOLD'.
    ohlcv: list of [timestamp, open, high, low, close, volume]
    Requires at least RSI_PERIOD + 1 candles.
    """
    if len(ohlcv) < 40:  # need enough candles for MACD(12,26,9)
        return "HOLD"

    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    df["close"] = df["close"].astype(float)

    rsi  = ta.momentum.RSIIndicator(df["close"], window=RSI_PERIOD).rsi()
    macd = ta.trend.MACD(df["close"])
    hist = macd.macd_diff()

    last_rsi  = rsi.iloc[-1]
    last_hist = hist.iloc[-1]

    if last_rsi < RSI_BUY and last_hist > 0:
        return "BUY"
    if last_rsi > RSI_SELL and last_hist < 0:
        return "SELL"
    return "HOLD"
