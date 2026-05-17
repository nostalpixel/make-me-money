# Advanced Features (Codex Brainstorm)

> Sourced from Codex independent brainstorm, 2026-05-17.
> All 10 ideas ranked by implementation complexity and value.

---

## 1. Regime Detection Layer

**What:** Automatically classify market state as "trending", "choppy", or "panic" and
switch strategy behavior accordingly.

**Why it matters:** RSI+MACD fires in choppy markets and loses. A regime filter would
suppress entries when conditions don't suit the strategy.

**Simple implementation:**
- Trending: ADX > 25 or price > 50-period EMA
- Choppy: ADX < 20 and price oscillating around EMA
- Panic: ATR spike > 2× 20-period average ATR

```python
def get_regime(ohlcv) -> str:
    closes = pd.Series([c[4] for c in ohlcv])
    highs  = pd.Series([c[2] for c in ohlcv])
    lows   = pd.Series([c[3] for c in ohlcv])
    adx    = ta.trend.ADXIndicator(highs, lows, closes).adx().iloc[-1]
    atr    = ta.volatility.AverageTrueRange(highs, lows, closes).average_true_range()
    atr_ratio = atr.iloc[-1] / atr.rolling(20).mean().iloc[-1]
    if atr_ratio > 2.0: return "panic"
    if adx > 25:        return "trending"
    return "choppy"
```

**Bot behavior by regime:**
- trending → trade normally
- choppy → skip entries, hold existing positions
- panic → send alert, skip entries, widen alert thresholds

**Effort:** 1 day. High impact.

---

## 2. Funding Rate + Open Interest Filter

**What:** Even on spot, perpetual funding rates and open interest reveal crowd positioning.
Use as a macro bias overlay.

**Signals:**
- Extreme positive funding (>0.1%/8hr) + rising OI → crowded longs → fade warning, skip BUY
- Negative funding + rising OI → short squeeze potential → BUY bias
- OI dropping sharply → deleveraging event → hold cash

**Data source:** Bybit API — `GET /v5/market/funding/history` and `GET /v5/market/open-interest`

```python
async def get_funding_bias(exchange) -> str:
    funding = exchange.fetch_funding_rate("BTC/USDT:USDT")
    rate    = float(funding["fundingRate"])
    if rate > 0.001:  return "crowded_long"   # skip BUY
    if rate < -0.001: return "crowded_short"  # support BUY
    return "neutral"
```

**Effort:** Half day. Free data, already on Bybit.

---

## 3. On-Chain Flow Signal

**What:** Exchange inflows/outflows, whale wallet movements, stablecoin mints/burns as
macro bias overlay to suppress bad entries or boost conviction.

**Free data sources:**
- CryptoQuant API (free tier): exchange inflows, miner outflows
- Glassnode (limited free): exchange balance changes
- Whale Alert Telegram channel: large transfers (subscribe and parse)
- IntoTheBlock API (free): large transactions, exchange flows

**Use case:** If exchange inflows spike (whales depositing to sell), suppress BUY signals
for the next 2-4 hours. Conversely, large outflows (whales withdrawing) are bullish.

**Effort:** 2 days. Requires choosing one data source and building parser.

---

## 4. Order Book Fragility Index

**What:** Real-time bid/ask depth analysis — delay entries during thin or manipulated liquidity.

**Metrics:**
- Bid/ask imbalance: `(bid_volume - ask_volume) / total_volume` — positive = buy pressure
- Wall detection: unusually large single order at a level (potential spoof)
- Sweep frequency: how often large market orders eat through levels

```python
async def get_book_health(exchange) -> dict:
    book    = await asyncio.to_thread(exchange.fetch_order_book, "BTC/USDT", 20)
    bid_vol = sum(b[1] for b in book["bids"][:10])
    ask_vol = sum(a[1] for a in book["asks"][:10])
    imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    spread    = (book["asks"][0][0] - book["bids"][0][0]) / book["bids"][0][0]
    return {"imbalance": imbalance, "spread": spread, "fragile": spread > 0.0005}
```

**Effort:** Half day. Fully free, already on Bybit.

---

## 5. Auto Post-Mortems (Trade Debriefs)

**What:** After every closed trade, bot sends a compact analysis card:
- Entry rationale (RSI/MACD values at entry)
- Regime at entry (trending/choppy/panic)
- Max adverse excursion (worst point during trade)
- Max favorable excursion (best point we could have exited)
- Slippage vs expected
- One suggested rule tweak

**Example:**
```
📋 TRADE DEBRIEF — Trade #4

Entry: $78,138 (RSI 44.2, MACD +12.4, regime: choppy ⚠️)
Exit: $84,390 via take-profit ✅
Hold time: 18h 32m

Max loss during trade: -2.1% at hour 3
Best possible exit: $85,200 (+9.0%) — missed by 0.9%
Slippage: $0.23 (0.003%)

💡 Suggestion: entered in choppy regime — would have been filtered
   by regime detection. Consider waiting for ADX > 25.
```

**Effort:** 1 day. Requires storing entry context in DB alongside trade.

---

## 6. /whatif Command (Counterfactual Simulator)

**What:** Replay last N trades with different rules and see the delta.

**Usage examples:**
```
/whatif atr_trail        → What if SL was ATR-based instead of -5%?
/whatif skip_choppy      → What if we filtered out choppy regime entries?
/whatif tp 12            → What if TP was +12% instead of +8%?
/whatif wait 1           → What if we waited 1 more candle before entering?
```

**Implementation:**
1. Fetch trade history from DB
2. Re-fetch OHLCV for each trade's time window from Bybit
3. Re-simulate with altered rule
4. Return: new P&L, new win rate, delta vs actual

**Effort:** 2 days. Genuinely rare feature — most bots don't have this.

---

## 7. Conviction-Scaled Position Sizing

**What:** Instead of fixed 50% allocation, scale position by multi-factor conviction score.

**Conviction factors (0-1 each):**
- Signal strength: how far RSI is from 45 (further below = stronger)
- Regime alignment: trending = 1.0, choppy = 0.5, panic = 0.0
- Funding bias: neutral = 1.0, crowded_long = 0.5
- Book health: healthy = 1.0, fragile = 0.3
- Fear & Greed: extreme fear = 1.2 (slight overweight), extreme greed = 0.7

**Position size = base_size × conviction_score**
- Base size: 30% of portfolio
- High conviction (0.9+): 50% max
- Low conviction (<0.5): skip trade entirely

**Effort:** 1.5 days. Requires features 1, 2, 4 as inputs.

---

## 8. Narrative Intelligence Feed

**What:** Classify crypto news into actionable categories, surface only signals that
affect your current position.

**Data sources (free):**
- CryptoPanic API (free): crypto news aggregator with sentiment scores
- Messari RSS feed: structured crypto news
- Alternative.me: already using for Fear & Greed

**Classification categories:**
- ETF/institutional flows → bullish macro
- Regulatory action → risk-off
- Exchange risk (hack, insolvency) → emergency alert
- Halving/protocol events → scheduled macro
- Whale moves → short-term pressure

**Bot behavior:** Only send narrative alerts when relevant to open position.
If holding BTC and "exchange hack" narrative spikes → immediate alert to review.

**Effort:** 1.5 days. CryptoPanic API is free with registration.

---

## 9. Mission Control Auto-Refreshing Dashboard

**What:** One message in Telegram that gets silently edited every 15 minutes with
the full market state snapshot. Always up to date when you open the chat.

**Format:**
```
🖥️ MISSION CONTROL  —  updated 14:32 UTC

₿ $78,191 (+0.8%)  |  Regime: 📊 Trending
😨 Fear & Greed: 38  |  Funding: neutral
📈 RSI: 52.1  MACD: +12.4 ↑

📍 Position: +0.2% ($+0.01)  |  18h 32m
🎯 TP: $84,390  |  ⚠️ Alert: $74,231

💼 Portfolio: $10.02 (+0.2% from start)
🔁 Next poll: 8 min
```

**Implementation:** Store the message ID after first send. Use `bot.edit_message_text()`
instead of sending new messages. Silently updates without pinging.

**Effort:** Half day. Uses Telegram's edit_message API.

---

## 10. Chaos Drills (Resilience Testing)

**What:** Periodically run automated "what would break" drills against live logic.

**Drill scenarios:**
- Flash crash: simulate -20% price move, verify alerts fire correctly
- API outage: mock exchange unreachable, verify retry/backoff and alert
- Stale candles: feed repeated OHLCV, verify candle staleness detection
- DB corruption: simulate write failure mid-trade, verify recovery
- Clock drift: simulate 30s time offset, verify NTP check triggers

**Implementation:** A `chaos.py` module that can be triggered via `/chaos` command.
Runs in dry-run mode (no real orders), reports pass/fail for each scenario.

**Effort:** 2 days. Mostly test harness work. Gives real confidence before $100 deposit.

---

## Priority for Implementation

| # | Feature | Effort | Value | Depends on |
|---|---------|--------|-------|------------|
| 9 | Mission Control dashboard | 0.5d | High | Nothing |
| 5 | Auto post-mortems | 1d | High | Nothing |
| 1 | Regime detection | 1d | High | Nothing |
| 2 | Funding rate filter | 0.5d | Medium | Nothing |
| 4 | Order book health | 0.5d | Medium | Nothing |
| 6 | /whatif simulator | 2d | High | DB history |
| 7 | Conviction sizing | 1.5d | High | 1, 2, 4 |
| 8 | Narrative intelligence | 1.5d | Medium | CryptoPanic API key |
| 3 | On-chain flows | 2d | Medium | External API |
| 10 | Chaos drills | 2d | Medium | Phase 0 fixes done |
