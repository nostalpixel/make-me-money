# Action Plan

> Machine-readable implementation roadmap. Last updated: 2026-05-17. Codex-reviewed.
> Source of truth for all development priorities.
> Reference: proposals/ directory for full detail on each item.

---

## Project Context

**What this is:** Autonomous crypto trading bot. Claude Code experiment.
**Goal:** Deploy-and-forget for 3 months with $100 USDT.
**Exchange:** Bybit spot (BTC/USDT). Additional: TON/USDT on DeDust DEX.
**Language:** Python 3.11, Docker Compose, SQLite, python-telegram-bot.
**Current state:** Bot live, first trade executed, multiple bugs fixed. Not yet safe for unattended operation.

**Core philosophy (read first):**
- BTC is a long-term hold. Never auto-sell BTC on drawdown.
- Two capital pools: BTC Hold (passive) + USDT Opportunity Fund (active trading).
- Bot only trades the Opportunity Fund. Graduated alerts on drawdown, human decides exits.
- Asymmetric: cut winners at TP, hold losers in BTC (acceptable long-term exposure).
- See: `proposals/trading-philosophy.md`

---

## Phase 0 — Correctness (BLOCKING — do before anything else)

These are bugs that can cause financial loss or silent failures. Fix before adding $100.

### 0.1 — Fix exit bug: sell only trade-owned BTC
**File:** `bot/executor.py` → `close_position()`
**Bug:** `close_position()` sells all free BTC balance, not just the BTC from this trade.
If user holds any BTC manually, bot will dump it.
**Fix:** Store exact BTC quantity purchased in the `trades` table on entry. On exit, sell only that quantity.
```sql
ALTER TABLE trades ADD COLUMN btc_qty REAL;
```
In `place_buy()`: after order fill, record `order['filled']` as `btc_qty`.
In `close_position()`: sell `position['btc_qty']` not `await get_btc_balance()`.

### 0.2 — Persist circuit breaker state to DB
**File:** `bot/main.py`, `bot/db.py`
**Bug:** `context.bot_data["paused"]` resets to False on every container restart.
**Fix:** Add `bot_state` table in SQLite. Read `paused` flag from DB on startup, write to DB on every change.
```sql
CREATE TABLE IF NOT EXISTS bot_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
```
On startup: `paused = db.get_state("paused", default="false") == "true"`
On pause/resume: `db.set_state("paused", "true"/"false")`

### 0.3 — Use closed candles only for signal
**File:** `bot/strategy.py` → `get_signal()`
**Bug:** Signal computed on candles including the currently-forming (incomplete) candle.
MACD/RSI on a half-formed candle creates repainting false signals.
**Fix:** Drop the last candle before computing indicators: `ohlcv = ohlcv[:-1]`
One line change in `get_signal()`.

### 0.4 — Use exchange lot size metadata for order precision
**File:** `bot/executor.py` → `place_buy()`
**Bug:** `round(btc_amount, 6)` is hardcoded precision. Bybit's minimum quantity and
step size must come from the exchange's market metadata or orders get rejected.
**Fix:**
```python
market = exchange.market(PAIR)
step   = market['precision']['amount']
btc_amount = exchange.amount_to_precision(PAIR, size / btc_price)
```

### 0.5 — Fee-aware P&L
**File:** `bot/executor.py` → `close_position()`
**Bug:** P&L calculation ignores trading fees (~0.1% taker each side = 0.2% round-trip).
On a $100 account this materially affects TP/SL math.
**Fix:** Subtract fees from P&L: `pnl = gross_pnl - (entry_size * 0.002)`
Or fetch actual fee from order response: `order['fee']['cost']`

---

## Phase 1 — Safety (required for unattended operation)

### 1.1 — Replace hard stop-loss with drawdown alerts
**File:** `bot/executor.py`, `bot/main.py`
**Current:** `SL_PCT = -0.05` triggers automatic full BTC sell at -5%.
**Change (per trading philosophy):** Remove auto-sell. Add graduated alerts:
- -5%: send warning, continue holding
- -10%: send alert "liquidity attention needed", pause new entries
- -15%: send strong alert "manual review required", stay paused
- Never auto-sell BTC. Human sends /resume to re-enable entries after reviewing.
**Config:**
```python
ALERT_THRESHOLDS = [-0.05, -0.10, -0.15, -0.20]
PAUSE_THRESHOLD  = -0.10  # pause new entries at this level
```
Track which thresholds already alerted (per position, in DB) to avoid spam.

### 1.2 — Daily loss limit (Opportunity Fund protection)
**File:** `bot/main.py` → `poll_market()`
**What:** If daily P&L across all trades < -X% of Opportunity Fund, pause all new entries until next UTC day.
**Config:** `DAILY_LOSS_LIMIT = -0.10` (10% of trading capital per day)
**Implementation:** Check `db.daily_pnl()` before every BUY attempt. If below limit, skip and alert.

### 1.3 — USDT liquidity floor alert
**File:** `bot/main.py` → `poll_market()`
**What:** If USDT balance < floor threshold, alert "trading capital low — consider top-up" and pause entries.
**Config:** `LIQUIDITY_FLOOR_USDT = 10.0` (adjustable, scale with deposit size)
**Why:** Prevents bot from making tiny trades with last few dollars when better to wait for top-up.

### 1.4 — Exchange-native TP order after entry
**File:** `bot/executor.py` → `place_buy()`
**What:** Immediately after a BUY fills, place a limit sell order at TP price on Bybit.
Exchange holds the TP — it fires even if bot crashes.
**Note:** Bybit spot supports `takeProfit` param on order create, or a separate conditional order.
Verify exact API params for your account type before implementing.
**Store:** TP order ID in `trades` table (`tp_order_id TEXT`). On close_position(), cancel the TP order first.
**No exchange stop-loss** — per trading philosophy, we alert on drawdown, not auto-sell.

### 1.5 — Heartbeat alert
**File:** `bot/main.py`
**What:** Every 6 hours, bot sends "💓 alive | portfolio: $X | position: Y" to Telegram.
If user doesn't receive a heartbeat for 12+ hours, something is wrong.
**Implementation:** Add `job_queue.run_repeating(heartbeat, interval=21600, first=21600)`
```python
async def heartbeat(context):
    portfolio = await executor.get_total_portfolio(exchange)
    position  = db.get_open_position()
    pos_str   = f"holding BTC @ ${position['entry_price']:,.0f}" if position else "no position"
    await context.bot.send_message(chat_id, f"💓 Alive | ${portfolio:.2f} | {pos_str}")
```

---

## Phase 2 — Performance (improve edge before scaling to $100)

### 2.1 — Poll interval: 15min → 5min
**File:** `bot/main.py`
**Change:** `POLL_INTERVAL = 900` → `POLL_INTERVAL = 300`
**Cost:** 3× more API calls. Well within Bybit free tier.
**Impact:** Drawdown alerts and TP checks are 3× more responsive.

### 2.2 — Higher-timeframe trend filter
**File:** `bot/strategy.py`, `bot/main.py`
**What:** Only take BUY signals when 1h trend is also bullish (price above 1h EMA-50).
**Implementation:**
```python
async def get_trend_filter(exchange) -> bool:
    ohlcv_1h = await asyncio.to_thread(exchange.fetch_ohlcv, PAIR, "1h", limit=60)
    closes   = pd.Series([c[4] for c in ohlcv_1h[:-1]])
    ema50    = closes.ewm(span=50).mean().iloc[-1]
    return closes.iloc[-1] > ema50
```
Gate BUY branch: `if signal == "BUY" and await get_trend_filter(exchange):`

### 2.3 — Spread pre-check before market order
**File:** `bot/executor.py` → `place_buy()`
**What:** Fetch order book top, compute spread, skip trade if spread > 0.1%.
**Implementation:**
```python
book   = await asyncio.to_thread(exchange.fetch_order_book, PAIR, 1)
spread = (book['asks'][0][0] - book['bids'][0][0]) / book['bids'][0][0]
if spread > 0.001:
    logger.info("Skipping: spread %.4f%%", spread * 100)
    return None
```

### 2.4 — Walk-forward backtest validation
**File:** `bot/backtest.py` (extend existing)
**What:** Split 90 days of historical data into 30-day train + 7-day OOS windows.
Run signal logic on OOS windows with 0.1% fee simulation. Report win rate, Sharpe, drawdown.
**Gate:** If Sharpe < 0.5 or win rate < 50% OOS, flag strategy as unvalidated in output.
**When to do:** Before committing $100. Not blocking for $10 phase.

---

## Phase 3 — UX (Telegram experience)

### 3.1 — Command menu registration
**File:** `bot/main.py` → `on_startup()`
**What:** Call `bot.set_my_commands([...])` to register commands in Telegram's "/" menu.
One API call, zero ongoing code.
```python
await app.bot.set_my_commands([
    ("status",  "Portfolio balance and open position"),
    ("log",     "Last 10 trades"),
    ("pause",   "Pause trading"),
    ("resume",  "Resume trading"),
    ("stats",   "Performance report"),
])
```

### 3.2 — Analytics: /stats and /perf commands
**Files:** New `bot/analytics.py`, extend `bot/main.py`, `bot/db.py`
**What:** See `proposals/analytics.md` for full spec.
- `analytics.py`: win_rate(), profit_factor(), sharpe_ratio(), max_drawdown(), equity_curve()
- DB: add `portfolio_snapshots` table (daily snapshot of total portfolio)
- `/stats` command: full performance report per strategy + overall
- `/perf 7d` / `/perf 30d`: time-windowed P&L
- Enhance daily summary with 7-day mini stats block

### 3.3 — Money management phase tracker
**File:** `bot/db.py`, `bot/main.py`
**What:** Implement 3-phase extraction model from `proposals/money-management.md`.
- Phase 1: Bank 40% of each gain until initial deposit recouped
- Phase 2: Bank 20% of each gain (house money phase)
- Phase 3: Bank 10-15% at scale
- DB table `money_management` tracks phase, banked total, high-water mark
- Daily summary reports current phase and banked amount

---

## Phase 4 — Infrastructure (for unattended VPS deployment)

### 4.1 — Move to VPS (DigitalOcean Singapore, $6/mo)
**When:** Before committing $100 for 3-month run.
**Steps:**
1. Provision DO droplet (Ubuntu 22.04, 1GB RAM, SGP region)
2. Install Docker + Docker Compose
3. Copy `.env` securely (never commit)
4. `git clone && docker compose up -d`
5. Add DO firewall: block all inbound except SSH (port 22)

### 4.2 — GitHub Actions CI/CD
**File:** `.github/workflows/deploy.yml`
**What:** On push to main:
1. Run backtest as smoke test (fail fast if signal logic broken)
2. SSH to VPS, `git pull && docker compose up -d --build`
3. Send Telegram notification: "🚀 Deployed commit <sha>"
**Requires:** GitHub secret `VPS_SSH_KEY` and `VPS_HOST`

### 4.3 — Docker healthcheck
**File:** `Dockerfile`
**What:** Add healthcheck so Docker restarts the bot if it becomes unresponsive.
```dockerfile
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
  CMD python -c "import sqlite3; sqlite3.connect('trade.db').execute('SELECT 1')" || exit 1
```

---

## Phase 5 — Scale (after 30 days of live profitable operation)

Do not start until:
- All Phase 0-1 items complete
- Bot has run 30+ days with real money
- At least 20 completed trades in DB
- Win rate > 50% and Sharpe > 1.0 over those trades

### 5.1 — Multi-strategy architecture
See `proposals/ux-and-multi-strategy.md` → Section B, C, D.
Strategy registry, per-strategy capital allocation, parallel job_queue execution.

### 5.2 — Grid bot (Bybit native)
Deploy Bybit's native grid bot on $20-30 of the portfolio.
Targets sideways markets when RSI+MACD signal = HOLD.
See `proposals/strategy-gap-analysis.md` → Section 1.

### 5.3 — TradingView webhook integration
See `proposals/strategy-gap-analysis.md` → Section 2.
Requires domain + HTTPS endpoint + TradingView Pro ($15/mo).

### 5.4 — TON copy trading
See `proposals/wallet-tracking-copy-trading.md` → Approach C.
Poll toncenter every 15s, decode DeDust swaps, mirror trades.
Extend existing `ton-bot/` module.

### 5.5 — Telegram Mini App
See `proposals/ux-and-multi-strategy.md` → Section D.
Portfolio dashboard, strategy controls, allocation sliders.
Build only after 3+ strategies are live and text commands become painful.

---

## What NOT to Build (confirmed out of scope)

| Item | Reason |
|------|--------|
| Rust / Go rewrite | No latency benefit at 5-15min timeframe |
| Bare metal (remove Docker) | No performance gain, loses operational benefits |
| Mempool monitoring | Overkill; requires full node |
| Martingale / averaging down | Banned by trading philosophy |
| Meme coin sniping | Banned by trading philosophy |
| Martingale doubling | Banned by trading philosophy |
| Funding rate harvesting | Requires >$1k capital to be meaningful |
| WebSocket price feed | Defer until exchange-native TP in place |

---

## Phase 0.5 — Operational Reliability (Codex-flagged gaps, added 2026-05-17)

These were missing from the original plan. All required for unattended 3-month operation.

### 0.5.1 — Idempotent order lifecycle (crash recovery)
**What:** If bot crashes between order sent and DB write, or between TP placed and DB updated,
state diverges and bot can double-enter, fail to exit, or lose track of positions.
**Fix:** Use a DB transaction that writes order intent BEFORE sending to exchange, then confirms
on success. On startup reconciliation (0.5.2), repair any `pending_*` rows.
States: `pending_entry` → `open` → `pending_exit` → `closed` | `error`

### 0.5.2 — Startup reconciliation
**What:** On every bot start, compare exchange open orders + BTC balance against DB.
Repair any divergence before resuming normal operation.
**Implementation:** Extend `executor.reconcile()` to:
1. Check for any open exchange orders not in DB — close or record them
2. Check for `pending_entry` rows in DB — verify if order filled or not
3. Check for `pending_exit` rows — verify if TP order still live on exchange
4. Alert on any mismatch, pause until manually reviewed if unrecoverable

### 0.5.3 — Partial fill and dust handling
**What:** Market orders can partially fill. Exit must handle case where BTC qty received ≠ expected.
**Fix:** After fill, record actual `btc_qty` from `order['filled']` (not computed). On exit,
sell exactly `position['btc_qty']`. If sell partially fills, retry remainder up to 3 times.
Guard: if remaining BTC notional < $1, treat as dust and skip.

### 0.5.4 — API fault policy (retry + circuit breaker)
**What:** Current code catches generic exceptions and sends "skipping" alerts but has no
structured retry or escalation. Silent loops hide exchange outages.
**Fix:**
- Wrap all exchange calls with retry: 3 attempts, exponential backoff (5s, 15s, 45s)
- After 3 failures: pause bot, send "exchange unreachable" alert, stop retrying
- On poll_market exception: distinguish transient (network) vs permanent (auth, balance) errors
- Log full traceback for permanent errors

### 0.5.5 — Clock sync and UTC day boundary
**What:** VPS clock drift breaks candle boundary logic and daily P&L resets.
**Fix:**
- Add NTP check on startup: if system clock vs exchange time > 5s, alert and halt
- Use UTC-based day boundaries for `daily_pnl` queries (already done via `date.today()` — verify TZ)
- In Docker: set `TZ=UTC` in docker-compose.yml

### 0.5.6 — SQLite durability
**What:** Default SQLite settings can lose recent writes on power loss or Docker force-kill.
**Fix:** Add to `db.init()`:
```python
con.execute("PRAGMA journal_mode=WAL")
con.execute("PRAGMA synchronous=NORMAL")
```
Confirm `trade.db` volume mount path in docker-compose is correct (already done, verify).

### 0.5.7 — Bybit API key hardening (BLOCKER)
**What:** Current API key must be verified to have no withdrawal permissions and should be
IP-restricted to VPS IP before going to $100. A leaked key with withdrawal rights = total loss.
**Action (human task, not code):**
1. Bybit → API Management → edit key
2. Enable: Read, Spot Trading ONLY
3. Disable: Withdrawals, Futures, Options
4. Set IP restriction to VPS IP once VPS is provisioned
5. Rotate key if it was ever committed to git or shared (it was visible in session — rotate now)

### 0.5.8 — Pause semantics: entries only, not protective jobs
**What:** When paused, bot must still:
- Check drawdown alerts on open position
- Maintain/check exchange TP orders
- Run heartbeat
- Run startup reconciliation
Only NEW entries should be blocked.
**Fix:** Change guard from `if context.bot_data.get("paused"): return` at top of poll_market
to a targeted check only around the BUY branch.

### 0.5.9 — Emergency kill switch
**What:** One command/env var that immediately stops all new orders and alerts.
**Implementation:**
- `/kill` Telegram command: sets `kill_switch=true` in DB, sends confirmation
- On startup: if `kill_switch=true` in DB, start in paused mode, alert operator
- Separate from `/pause` — kill switch survives restarts, requires explicit `/unkill` to clear

### 0.5.10 — Secondary alert on Telegram failure
**What:** If Telegram send fails (bot blocked, token expired, network), alerts are silently lost.
**Fix:** Log all unsent alerts to DB table `alert_queue`. On next successful send, prepend
"[missed alerts: N]" header. If Telegram unreachable for >1hr, write to local log file as fallback.

---

## Current Blockers Summary (updated after Codex review)

Before bot is safe with $100 for 3 months, in priority order:

1. **0.5.7** Rotate/harden Bybit API key (human task — do now)
2. **0.1** Fix exit bug (sells all BTC not just trade BTC)
3. **0.4** Use exchange lot size metadata for order precision
4. **1.4** Exchange-native TP order after entry
5. **0.5.2** Startup reconciliation
6. **0.5.1** Idempotent order lifecycle
7. **0.2** Persist paused state to DB
8. **0.5.8** Fix pause to allow protective jobs to run
9. **0.5.9** Emergency kill switch
10. **0.5.4** API fault policy (retry + circuit breaker)
11. **0.5** Fee-aware P&L
12. **0.3** Closed candles for signal
13. **1.1** Replace stop-loss with drawdown alerts
14. **1.5** Heartbeat alert
15. **0.5.5** Clock sync check on startup
16. **0.5.6** SQLite WAL mode
17. **4.1** Move to VPS

**After all above:** 2-4 weeks paper/tiny-size live with forced restart and network failure drills.
**Only then:** Deposit $100 and run for 3 months.
