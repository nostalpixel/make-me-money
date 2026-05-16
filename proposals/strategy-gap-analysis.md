# Strategy Gap Analysis

> Cross-referencing the research doc (2026-05-17) against our current + planned stack.
> Goal: identify what's genuinely new and worth adding.

---

## What We Already Have or Are Building

| Strategy | Status |
|----------|--------|
| RSI + MACD signal bot (BTC/USDT spot, 15m) | ✅ Live |
| TON/USDT on DeDust DEX | ✅ Live (needs mnemonic) |
| Native SL/TP (P1 proposal) | 📋 Planned |
| Trend filter / 1h EMA (P2 proposal) | 📋 Planned |
| ATR position sizing (P3) | 📋 Planned |
| Multi-strategy + allocation (UX proposal) | 📋 Planned |
| Copy trading — wallet monitor | 📋 Planned |
| Mean reversion (RSI component) | ✅ Partially covered |

---

## What's New and Genuinely Useful

### 🟢 HIGH VALUE — Add These

#### 1. Spot Grid Bot

**Why it's additive:** Our RSI+MACD bot sits idle when signal = HOLD (sideways/choppy market).
A grid bot *thrives* in exactly that condition. The two strategies are complementary by design:

- RSI+MACD active → trending market, directional trades
- Grid bot active → sideways market, range harvesting
- Both can run simultaneously, allocated separately

**How it works with our stack:**
- Deploy a grid between two price levels (e.g. $70k–$90k BTC)
- Place limit buy/sell orders every 1.5% apart
- Each round-trip = small profit
- No signal logic needed — pure order management

Bybit has a native grid bot built in. Zero code path: use Bybit's UI to launch a grid,
allocate a % of capital. More control path: build it ourselves with the exchange API
(`create_limit_order` in a loop).

**Verdict:** Best ROI addition. Low effort if using Bybit's native grid. Medium effort to build custom.

---

#### 2. TradingView + Bybit Webhook Automation

**Why it's useful:** Instead of writing indicator logic in Python (fragile, hard to visualize,
slow to iterate), use TradingView's Pine Script ecosystem:

- Thousands of community strategies available
- Visual backtesting in TradingView UI
- Alerts fire a webhook → hits our server → places order on Bybit

**What changes in our stack:**
- Replace `strategy.py` signal logic with a TradingView alert listener
- Add a `/webhook` HTTP endpoint (FastAPI, 10 lines)
- TradingView sends: `{"action": "BUY", "symbol": "BTCUSDT", "price": 80000}`
- Our bot receives, validates, executes

**What this unlocks:**
- Use any of TradingView's thousands of strategies without rewriting them in Python
- Faster strategy iteration (change logic in Pine Script, not code)
- Visual backtest before deploying

**Requires:** Domain + HTTPS endpoint (already in infrastructure proposal). TradingView
Pro plan (~$15/mo) for real-time alerts and webhook support.

**Verdict:** High leverage once we have a server + domain. Turns any TradingView strategy
into a live bot in minutes.

---

#### 3. Spot DCA Bot

**Why it's useful:** Simple, proven, and orthogonal to everything else.
DCA doesn't try to time the market — it just accumulates BTC/TON on a schedule.

Use case: allocate 20% of portfolio to weekly DCA into BTC. Set it and forget it.
The RSI+MACD bot handles active trading on the remaining 80%.

**Effort:** 30 lines of code. One job_queue daily/weekly task, one `create_market_buy_order`.

**Verdict:** Quick win, genuinely robust. Good complement to active strategies.

---

#### 4. Rebalancing Bot

**Why it's useful:** As the portfolio grows across BTC, TON, and USDT, allocations drift.
A rebalancing bot forces disciplined profit-taking (sell winners, buy laggards) without emotion.

Example target: 50% BTC, 30% TON, 20% USDT.
If BTC runs to 70%, bot sells some BTC and buys TON/USDT back to target.

**Fits naturally** into the multi-strategy allocation system from `ux-and-multi-strategy.md`.
The same `strategy_config` table can hold rebalancing targets.

**Verdict:** Medium-term addition. Becomes valuable once portfolio is >$100 and holds multiple assets.

---

### 🟡 LOWER PRIORITY — Research Further

#### 5. Low-Leverage Futures Grid

**What it adds:** Futures allow shorting, so a neutral grid captures both up and down moves.
At 2x leverage, doubles grid profits with controlled risk.

**Why not now:** We're spot-only by design (no liquidation risk). Leverage adds complexity
and requires more robust monitoring. Only worth it after native SL/TP and WebSocket feed
are in place.

**Verdict:** Phase 3 addition. Add after core risk infrastructure is solid.

---

#### 6. Funding Rate Harvesting

**What it adds:** In extreme market conditions (everyone long), funding rates can be
0.1%+ every 8 hours = ~110% APR just for holding a short hedge.

**Why not now:** The research is right — "smaller edge than Twitter claims, more advanced."
Requires delta-neutral hedging (long spot, short perp) and capital on both sides.
At $10 portfolio, the absolute dollar gains are trivial.

**Verdict:** Interesting for later when portfolio is >$1k. Skip for now.

---

### 🔴 ALREADY EXCLUDED (confirmed by research)

The research confirms what we already knew to avoid: Martingale, AI sniper bots,
Telegram signal groups, influencer copy trading, unlimited leverage scalping.
Our copy trading proposal specifically filtered these out (verified track record,
liquidity-only assets, no meme coins).

---

## Revised Strategy Roadmap

```
Phase 1 — Stability (current trade closes)
  - Native SL/TP on Bybit (P1)
  - 1h trend filter (P2)
  - 5-min poll interval

Phase 2 — Breadth
  - Bybit native grid bot (manual setup, $3 allocation)
  - DCA bot (30 lines, weekly BTC accumulation)
  - TradingView webhook listener (needs domain)

Phase 3 — Scale
  - Rebalancing bot
  - Multi-strategy allocation UI (Mini App)
  - TON copy trading (wallet monitor)
  - Low-leverage futures grid

Phase 4 — Infrastructure
  - VPS in Singapore
  - Domain + Caddy HTTPS
  - WebSocket price feed
```

---

## One Key Insight from the Research

> "The most sustainable crypto bot systems are boring, disciplined, low leverage,
> volatility harvesting, risk controlled."

Our RSI+MACD bot is the exciting one. The grid bot + DCA are the boring ones.
**The boring ones usually outperform long-term.** Consider allocating more capital
to grid/DCA than to the signal bot.
