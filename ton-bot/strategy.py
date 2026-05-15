"""
RSI(14) + MACD signal on TON/USDT using GeckoTerminal OHLCV.
Returns 'BUY' (enter TON), 'SELL' (exit to USDT), or 'HOLD'.
"""
import aiohttp
import pandas as pd
import ta

RSI_PERIOD = 14
RSI_BUY    = 45
RSI_SELL   = 65

# DeDust TON/USDT pool on TON mainnet (GeckoTerminal network: ton)
GECKO_BASE = "https://api.geckoterminal.com/api/v2"
TON_USDT_POOL = "EQD8TJ8xEWB1SpnRE4d89YO3jl0W0EiBnNS4NAtmRDaq9nPi"  # DeDust TON/USDT
TIMEFRAME  = "minute"
AGGREGATE  = "30"   # 30-min candles
LIMIT      = 80


async def fetch_ohlcv() -> list[list]:
    """Returns [[ts, open, high, low, close, volume], ...] newest-last."""
    url = (
        f"{GECKO_BASE}/networks/ton/pools/{TON_USDT_POOL}"
        f"/ohlcv/{TIMEFRAME}?aggregate={AGGREGATE}&limit={LIMIT}&currency=usd"
    )
    async with aiohttp.ClientSession(headers={"Accept": "application/json"}) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
    # GeckoTerminal returns newest-first; reverse to oldest-first
    candles = data["data"]["attributes"]["ohlcv_list"]
    candles.reverse()
    return candles  # each: [ts_unix, open, high, low, close, volume]


async def get_ton_price_usdt() -> float:
    """Current TON/USDT spot price via GeckoTerminal."""
    url = f"{GECKO_BASE}/networks/ton/pools/{TON_USDT_POOL}"
    async with aiohttp.ClientSession(headers={"Accept": "application/json"}) as session:
        async with session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
    return float(data["data"]["attributes"]["base_token_price_usd"])


def get_signal(ohlcv: list[list]) -> str:
    if len(ohlcv) < 40:
        return "HOLD"

    closes = pd.Series([float(c[4]) for c in ohlcv])

    rsi  = ta.momentum.RSIIndicator(closes, window=RSI_PERIOD).rsi()
    macd = ta.trend.MACD(closes)
    hist = macd.macd_diff()

    last_rsi  = rsi.iloc[-1]
    last_hist = hist.iloc[-1]

    if last_rsi < RSI_BUY and last_hist > 0:
        return "BUY"
    if last_rsi > RSI_SELL and last_hist < 0:
        return "SELL"
    return "HOLD"
