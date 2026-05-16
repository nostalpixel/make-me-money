# Analytics Implementation Proposal

> Designed 2026-05-17. Covers per-strategy and overall portfolio performance tracking.

---

## What We Need to Track

### Per-Strategy Metrics
- Win rate (% of trades closed in profit)
- Average win / average loss
- Profit factor (gross profit / gross loss)
- Sharpe ratio (return / volatility of returns)
- Max drawdown (largest peak-to-trough loss)
- Total P&L (USDT)
- Number of trades
- Average hold time

### Overall Portfolio Metrics
- Total portfolio value over time (equity curve)
- Combined P&L across all strategies
- Daily / weekly / monthly P&L
- Capital allocation efficiency (how much is idle vs deployed)
- Phase tracker (money management phase 1/2/3 per strategy-enhancements.md)

---

## Part 1 — Data Layer (DB Schema)

Extend SQLite with two new tables:

```sql
-- Snapshots of portfolio value, taken on every daily summary
CREATE TABLE portfolio_snapshots (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT    NOT NULL,          -- ISO 8601 UTC
    total_usdt REAL   NOT NULL,          -- USDT + BTC notional
    usdt_free  REAL   NOT NULL,
    btc_held   REAL   NOT NULL,
    btc_price  REAL   NOT NULL
);

-- Per-strategy performance cache, rebuilt on demand
CREATE TABLE strategy_stats (
    strategy_id    TEXT    PRIMARY KEY,
    trades_total   INTEGER NOT NULL DEFAULT 0,
    trades_won     INTEGER NOT NULL DEFAULT 0,
    gross_profit   REAL    NOT NULL DEFAULT 0,
    gross_loss     REAL    NOT NULL DEFAULT 0,
    max_drawdown   REAL    NOT NULL DEFAULT 0,
    last_updated   TEXT    NOT NULL
);
```

The existing `trades` table already has all raw data. `strategy_stats` is a
pre-computed cache so `/stats` responds instantly.

---

## Part 2 — Metrics Engine (`analytics.py`)

New module that computes all metrics from the `trades` table on demand.

```python
def win_rate(strategy_id: str = None) -> float:
    """Closed trades with pnl > 0 / total closed trades."""

def profit_factor(strategy_id: str = None) -> float:
    """Gross profit / gross loss. >1 = profitable."""

def sharpe_ratio(strategy_id: str = None) -> float:
    """Daily return mean / daily return std × sqrt(365)."""

def max_drawdown(strategy_id: str = None) -> float:
    """Largest peak-to-trough in cumulative P&L curve."""

def avg_hold_time(strategy_id: str = None) -> float:
    """Average seconds between open and close for closed trades."""

def equity_curve(strategy_id: str = None) -> list[tuple[str, float]]:
    """[(timestamp, cumulative_pnl), ...] for charting."""

def daily_returns(strategy_id: str = None) -> list[tuple[str, float]]:
    """[(date, pnl), ...] for last 30 days."""

def summary(strategy_id: str = None) -> dict:
    """All metrics in one call. strategy_id=None = overall portfolio."""
```

All functions accept `strategy_id=None` for overall and a specific ID for per-strategy.
Once multi-strategy is live, strategy_id maps to the `strategy_id` column in `trades`.

---

## Part 3 — Telegram Commands

### `/stats` — Full performance report

```
📊 PERFORMANCE REPORT

Overall (all strategies):
  Trades: 12 | Won: 7 (58%)
  P&L: +$1.24 | Profit factor: 1.8
  Sharpe: 1.42 | Max DD: -8.3%
  Avg hold: 4h 12m

BTC RSI+MACD:
  Trades: 10 | Won: 6 (60%)
  P&L: +$0.94 | Profit factor: 1.9
  Sharpe: 1.51 | Max DD: -7.1%

TON DeDust:
  Trades: 2 | Won: 1 (50%)
  P&L: +$0.30 | Profit factor: 1.5
  Sharpe: n/a (too few trades)
```

### `/perf 7d` / `/perf 30d` — Time-windowed report

Shows P&L, win rate, and trade count for the last 7 or 30 days only.

### Daily summary enhancement

Append a mini stats block to the existing 9am daily summary:
```
📈 7-day: +2.3% | Win rate: 60% | 8 trades
```

---

## Part 4 — Portfolio Snapshot Job

Add a daily snapshot job (runs at midnight UTC) to capture portfolio value over time.
This builds the equity curve for long-term performance tracking.

```python
async def snapshot_portfolio(context):
    exchange  = make_exchange()
    total     = await executor.get_total_portfolio(exchange)
    usdt_free = await executor.get_balance(exchange)
    btc       = await executor.get_btc_balance(exchange)
    ticker    = await asyncio.to_thread(exchange.fetch_ticker, "BTC/USDT")
    price     = float(ticker["last"])
    db.save_snapshot(total, usdt_free, btc, price)
```

---

## Part 5 — Future: Mini App Chart

When the Telegram Mini App is built (from `ux-and-multi-strategy.md`), the analytics
module feeds directly into it:

- Equity curve chart (Chart.js or Recharts)
- Per-strategy breakdown bar chart
- Win/loss distribution histogram
- Daily P&L heatmap (GitHub contribution style)

The `equity_curve()` and `daily_returns()` functions already return chart-ready data.

---

## Implementation Order

| Step | Work | Effort |
|------|------|--------|
| 1 | DB migrations (2 new tables) | 1hr |
| 2 | `analytics.py` metrics engine | 3hr |
| 3 | `/stats` Telegram command | 1hr |
| 4 | `/perf` command | 1hr |
| 5 | Snapshot job + daily summary enhancement | 1hr |
| **Total** | | **~1 day** |

No breaking changes — all additive. Can ship while bot is live.
