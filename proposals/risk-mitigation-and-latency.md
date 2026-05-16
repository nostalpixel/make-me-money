# Risk Mitigation & Latency Reduction

> Researched 2026-05-17. Applies to both the signal-based bot and copy trading.

---

## Part 1 — Risk Mitigation

### R1 — Exchange-Native Stop Orders (highest priority)

**Problem:** Software stops checked every 15 minutes. A fast move wipes through the
stop before the bot reacts. If the process crashes, position has no protection.

**Solution:** Place a stop-market order on Bybit immediately after every BUY fill.

```
Entry at $80,000 → immediately POST stop-market SELL at $76,000 (-5%)
```

Bybit V5 supports `stopLoss` param directly in the order create call, or a separate
conditional order. Exchange holds the stop — it fires even if our bot is offline.

**Cost:** ~1 API call per entry. Zero latency on execution.

---

### R2 — Per-Strategy Drawdown Circuit Breaker

**Problem:** A bad strategy can keep losing without bound if not interrupted.

**Solution:** Track rolling drawdown per strategy. If a strategy loses more than X%
from its peak allocation, automatically pause it and send an alert.

```
Allocation peak: $6.00
Current value:   $4.80  →  -20% drawdown  →  AUTO PAUSE
```

Threshold configurable per strategy (default: -15%). Stored in `strategy_config`.
Resume requires explicit `/resume <strategy_id>`.

---

### R3 — Daily Loss Limit

**Problem:** A runaway strategy or bad market day can lose the entire account.

**Solution:** Hard daily P&L floor. If cumulative daily loss across all strategies
exceeds X% of total portfolio, pause all trading until the next UTC day.

```
Portfolio: $10.00 | Daily limit: -10% ($1.00)
If daily_pnl < -$1.00 → pause all → alert user
```

Already have `daily_pnl` table in DB. Just needs a check in the poll loop.

---

### R4 — Correlation Guard for Copy Trading

**Problem:** If all copied wallets use the same strategy (e.g. all momentum traders),
they lose simultaneously in the same market condition.

**Solution:** When selecting copy wallets, require low correlation between their
trade histories. Measure with Pearson correlation on their daily return series.
Target: max pairwise correlation < 0.5.

Practical shortcut: pick wallets from different asset classes or chains
(e.g. one BTC trader, one TON DeFi trader, one altcoin trader).

---

### R5 — Liquidity / Slippage Pre-Check

**Problem:** Market orders on thin books get filled at bad prices.
At $10 this is noise; at $100+ it materially impacts returns.

**Solution:** Before every market order:
1. Fetch top-of-book: `exchange.fetch_order_book(symbol, limit=5)`
2. Compute estimated fill price by walking the book for our order size
3. If estimated slippage > 0.1%, skip the trade and log it

```python
asks = book['asks']  # [[price, qty], ...]
fill_price = walk_book(asks, size_usdt)
slippage = (fill_price - asks[0][0]) / asks[0][0]
if slippage > 0.001:
    logger.info("Skipping trade: slippage %.3f%%", slippage * 100)
    return None
```

---

### R6 — Wallet Vetting Pipeline (copy trading)

**Problem:** One lucky whale ≠ a good signal source. Past performance on 5 trades
can be pure luck.

**Minimum criteria before copying a wallet:**

| Metric | Minimum |
|--------|---------|
| Trade history | ≥ 90 days |
| Number of trades | ≥ 30 |
| Win rate | > 55% |
| Sharpe ratio | > 1.0 |
| Max drawdown | < 25% |
| Last active | < 14 days |
| Trade interval | > 30 min (filters bots) |
| Asset | BTC, ETH, TON only (no meme coins) |

Re-screen every 30 days. Auto-stop copying if rolling 30-day win rate drops below 45%.

---

## Part 2 — Latency Reduction

### L1 — Reduce Poll Interval: 15 min → 5 min

**Current:** Bot polls every 15 minutes. Entry/exit signals can be stale by up to 15 min.

**Fix:** Change `POLL_INTERVAL = 900` to `POLL_INTERVAL = 300`. 

**Cost:** 3× more API calls to Bybit and CoinGecko. Still well within free tier rate limits
(Bybit: 600 req/min; we'd use ~1 req/5min per strategy). Minimal compute cost.

**Impact:** Signals and SL/TP checks are 3× more timely. Biggest bang-for-buck latency win.

---

### L2 — Bybit WebSocket for Real-Time Price Feed

**Problem:** `fetch_ticker` is a REST call with ~100–300ms round-trip. For SL/TP
monitoring, polling REST every 5 min still means a 5-min gap.

**Solution:** Subscribe to Bybit's WebSocket `tickers.BTC/USDT` stream. Receive
price updates in real time (~100ms delay from exchange). Check SL/TP on every tick.

```python
from pybit.unified_trading import WebSocket

ws = WebSocket(testnet=False, channel_type="spot")
ws.ticker_stream(symbol="BTCUSDT", callback=on_tick)

def on_tick(msg):
    price = float(msg['data']['lastPrice'])
    if position and check_sl_tp_price(price, position):
        asyncio.create_task(close_position(...))
```

**Library:** `pybit` (Bybit's official Python SDK) supports WebSocket natively.
Add `pybit>=5.0.0` to requirements.

**Impact:** SL/TP response drops from "up to 15 min" to "under 1 second."
Eliminates the largest risk gap in the current bot.

---

### L3 — TON Transaction Webhooks (copy trading)

**Problem:** Polling `toncenter` every 60s means 0–60s latency on wallet copy.

**Solution:** Use **QuickNode's TON webhooks** or **Toncenter notification API**
to push a webhook call to our server when a target wallet transacts.

```
Wallet transacts → Toncenter/QuickNode pushes POST to our endpoint → decode & mirror
```

**QuickNode TON** (paid, ~$49/mo) supports address activity webhooks.

**Free alternative:** Run a lightweight polling loop at 15s intervals instead of 60s.
At 4 watched wallets × 4 req/min = 16 req/min — well within toncenter free tier (10 req/sec).

**Impact:** Reduces copy latency from 60s to 15s with no extra cost, or <5s with webhooks.

---

### L4 — Server Co-Location (advanced)

**Problem:** Bot runs on a Mac at home. Network round-trip to Bybit Singapore servers
is ~50–150ms depending on routing.

**Solution:** Move Docker container to a VPS in Singapore (AWS ap-southeast-1,
DigitalOcean SGP). Bybit's matching engine is in Singapore — latency drops to ~5ms.

**Cost:** ~$6/month (DigitalOcean Basic Droplet). 

**Impact:** Marginal for a 15-min strategy. Matters for 1-min or tick-level trading.
Worth doing when strategies move to shorter timeframes.

---

### L5 — Parallel OHLCV Fetch (minor)

**Current:** Strategy fetches 15m OHLCV, waits, then checks signal. If adding a 1h
trend filter (Proposal P2), that's two sequential fetches.

**Fix:** Fetch both timeframes concurrently with `asyncio.gather`.

```python
ohlcv_15m, ohlcv_1h = await asyncio.gather(
    asyncio.to_thread(exchange.fetch_ohlcv, PAIR, "15m", limit=80),
    asyncio.to_thread(exchange.fetch_ohlcv, PAIR, "1h",  limit=50),
)
```

**Impact:** Saves ~200–400ms per poll cycle. Small but free.

---

## Summary Table

| Item | Type | Effort | Impact | Priority |
|------|------|--------|--------|----------|
| R1 — Native stop orders | Risk | Low | High | P0 |
| L2 — WebSocket price feed | Latency | Medium | High | P1 |
| L1 — 15min → 5min poll | Latency | Trivial | Medium | P1 |
| R2 — Drawdown circuit breaker | Risk | Low | Medium | P2 |
| R3 — Daily loss limit | Risk | Low | Medium | P2 |
| L3 — TON webhooks / faster poll | Latency | Low | Medium | P2 |
| R5 — Slippage pre-check | Risk | Low | Low-medium | P3 |
| R6 — Wallet vetting pipeline | Risk | Medium | High (copy) | P3 |
| R4 — Correlation guard | Risk | Medium | Medium (copy) | P4 |
| L4 — Server co-location | Latency | Low | Low (now) | P5 |
| L5 — Parallel OHLCV fetch | Latency | Trivial | Trivial | P5 |
