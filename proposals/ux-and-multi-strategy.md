# UX & Multi-Strategy Proposals

> Researched 2026-05-16. Bot currently: single strategy, manual slash commands, no menu.

---

## A — Telegram UX Polish

### What Telegram supports natively

**Command menu** (`BotFather → /setcommands`): registers commands so they appear in
the "/" menu when the user taps the text field. Zero code change needed — just a
`setMyCommands` API call on startup.

```
status    - Portfolio balance and open position
log       - Last 10 trades
pause     - Pause trading
resume    - Resume trading
tonstatus - TON bot status
tonlog    - Last 10 TON trades
```

**Inline keyboard buttons** (`InlineKeyboardMarkup`): reply messages with tappable
buttons instead of requiring typed commands. After each trade notification, attach
buttons like [📊 Status] [⏸ Pause] [📋 Log].

**Persistent reply keyboard** (`ReplyKeyboardMarkup`): always-visible keyboard at the
bottom of the chat with big tap targets for the most common commands. Simpler than
inline, but less contextual.

**Callback query handlers**: `CallbackQueryHandler` in python-telegram-bot handles
button taps. Enables confirmation dialogs — e.g. tapping [⏸ Pause] shows
"Pause all strategies? [Yes] [Cancel]".

### Implementation path

1. `on_startup`: call `bot.set_my_commands([...])` to register the command menu.
2. Add `ReplyKeyboardMarkup` with [Status] [Log] [Pause] [Resume] as persistent bottom bar.
3. Upgrade trade cards and daily summaries to include an `InlineKeyboardMarkup` with
   contextual buttons ([📊 Status] after every notification).
4. Add `CallbackQueryHandler` for all button actions.

**Effort:** ~1 day. No architectural change.

---

## B — Strategy Selection

### Candidate strategies to add

| Strategy | Logic | Character |
|----------|-------|-----------|
| **RSI+MACD (current)** | RSI<45 + MACD hist>0 | Momentum, existing |
| **EMA Crossover** | Fast EMA crosses above slow EMA | Trend-following, fewer trades |
| **Bollinger Band Mean Reversion** | Price touches lower band + RSI not oversold | Mean-revert, range markets |
| **VWAP Deviation** | Price > 2% below VWAP on 15m | Intraday mean reversion |
| **Breakout** | Price breaks above N-period high with volume spike | Trend initiation |

### Architecture options

**Option 1 — Strategy registry (recommended)**  
Define strategies as classes implementing a common `get_signal(ohlcv) -> Signal` interface.
Register them in a dict. Bot loads active strategies from config/DB.

```python
STRATEGIES = {
    "rsi_macd": RSIMACDStrategy,
    "ema_cross": EMACrossStrategy,
    "bb_revert": BollingerReversionStrategy,
}
```

Active strategies stored in `bot_config` table in SQLite. `/strategy list` shows all,
`/strategy enable rsi_macd` activates one.

**Option 2 — Config file**  
`strategies.json` lists enabled strategies. Simpler but requires restart to change.

Option 1 is better — allows live switching via Telegram.

---

## C — Capital Allocation per Strategy

### Model

Each strategy gets a **capital allocation percentage** (sums to ≤100%). Example:
```
rsi_macd:  40%  →  $4 of $10 portfolio
ema_cross: 60%  →  $6 of $10 portfolio
```

Stored in `strategy_config` table:
```sql
CREATE TABLE strategy_config (
    strategy_id  TEXT PRIMARY KEY,
    enabled      BOOLEAN,
    allocation   REAL,   -- 0.0 to 1.0
    max_position REAL    -- max USDT per trade from this strategy's bucket
);
```

`/allocate rsi_macd 40` sets allocation. Bot validates total ≤ 100% before saving.

Each strategy's executor draws only from its allocation bucket. PnL is tracked
per-strategy so performance attribution is clear.

### Capital isolation

Each strategy maintains its own "virtual wallet" derived from the allocation:
- `available_usdt = total_usdt * allocation`
- Strategy can only trade up to `available_usdt`
- Unused allocation stays as USDT (doesn't drift to other strategies)

---

## D — Parallel Strategy Execution

### How to run multiple strategies simultaneously

All strategies share one exchange connection (one API key, one rate limit budget).
They run as **separate `job_queue` jobs** in the same Telegram bot process:

```python
for strategy_id, strategy_cls in active_strategies.items():
    app.job_queue.run_repeating(
        make_poll_fn(strategy_cls, allocation[strategy_id]),
        interval=strategy_cls.POLL_INTERVAL,
        first=10,
        name=strategy_id,
    )
```

Each strategy:
- Has its own position tracking row (`strategy_id` column in `trades` table)
- Checks only its own open position
- Draws from its capital allocation bucket
- Reports to Telegram with a strategy prefix (e.g. `[EMA]`, `[RSI]`)

### Concurrency considerations

- Multiple strategies may try to trade simultaneously — use an `asyncio.Lock` per
  exchange side (buy/sell) to prevent race conditions on balance reads.
- Rate limits: Bybit allows ~600 req/min on spot; 3-4 strategies at 15-min intervals
  is nowhere near the limit.
- One position per strategy (not per bot) — strategies don't share position state.

### DB schema addition

```sql
ALTER TABLE trades ADD COLUMN strategy_id TEXT DEFAULT 'rsi_macd';
```

---

## Combined Implementation Roadmap

| Phase | Work | Effort |
|-------|------|--------|
| 1 | Telegram command menu + inline buttons | 0.5 day |
| 2 | Strategy registry + `strategy_config` DB table | 1 day |
| 3 | Capital allocation model + `/allocate` command | 0.5 day |
| 4 | Parallel job_queue execution + per-strategy P&L | 1 day |
| 5 | Add 1-2 new strategies (EMA cross + BB revert) | 1 day |

**Total:** ~4 days of implementation.  
**Prerequisite:** Complete P1 (native SL/TP) from `strategy-enhancements.md` first,
since multi-strategy amplifies the risk of the poll-gap problem.
