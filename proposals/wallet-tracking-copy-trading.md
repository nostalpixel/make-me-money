# Wallet Tracking & Copy Trading Proposal

> Researched 2026-05-17. Goal: find and mirror high-return wallets automatically.

---

## Two Distinct Problems

**Wallet discovery** — identify wallets with strong track records.  
**Copy execution** — replicate their trades in real time with our own capital.

These are solved separately.

---

## Part 1 — Finding High-Return Wallets

### On-chain (TON, Ethereum, Solana, etc.)

On-chain wallets are fully transparent. Every swap, entry, exit, and PnL is public.

**Tools for wallet discovery:**

| Tool | What it provides | Free tier |
|------|-----------------|-----------|
| **Nansen** | Wallet labels, "Smart Money" filter, PnL rankings | No (paid) |
| **Arkham Intelligence** | Wallet profiling, entity labels, flows | Free searches |
| **DeBank** | On-chain portfolio + PnL across chains | Free |
| **Dune Analytics** | Custom SQL over on-chain data | Free |
| **Cielo Finance** | Real-time wallet activity feed, copy alerts | Free tier |
| **GMGN** (Solana/TON) | Meme coin smart money tracking | Free |
| **Defined.fi** | DEX trade feed, wallet PnL, token discovery | Free tier |

**Screening criteria for a copy-worthy wallet:**
- Win rate > 60% over 90+ days
- ≥ 20 completed trades (not just 1 lucky trade)
- Average trade return > 15%
- Max drawdown < 30%
- Active recently (last trade < 7 days)
- Not a known MEV bot (sandwich bots have high win rates but aren't copyable)

**Where to pull data programmatically:**

For TON:
- `api.ton.cat` — wallet history, jetton trades
- `tonviewer.com/api` — transaction history
- `toncenter.com/api/v2` — raw transactions, filterable by contract

For EVM chains (ETH, BSC, etc.):
- `api.etherscan.io` — free, 5 req/sec
- `api.zerion.io` — positions + PnL, DeFi-aware
- The Graph — indexed DEX data via GraphQL

### CEX (Bybit, Binance, OKX)

CEX trading is private. The only windows:
- **Bybit Leaderboard**: public top trader rankings with ROI, win rate, drawdown.
  `https://api.bybit.com/v5/copytrading/public-master-info` — returns top traders
  with stats. Bybit's own copy trading infrastructure already exists.
- **Binance Leaderboard**: similar public API.

**Bybit Copy Trading API** (already exists):
- Bybit has a native copy trading product. Master traders opt in, followers allocate capital.
- `GET /v5/copytrading/public-master-info` — list master traders with performance stats.
- `POST /v5/copytrading/order/create` — place a copy order (follower side).
- This is the fastest path to CEX copy trading: use Bybit's own infrastructure, no need to
  reverse-engineer timing.

---

## Part 2 — Copy Execution

### Approach A — Bybit Native Copy Trading (easiest for CEX)

Bybit lets you follow a master trader and auto-copy every trade with configurable:
- Capital allocation (fixed amount or % of portfolio)
- Max position size
- Stop copying if drawdown exceeds X%

**Pros:** Zero latency (Bybit mirrors trades internally), no code needed.  
**Cons:** Limited to Bybit perps/futures masters, not spot. Requires finding a good master on their leaderboard.

### Approach B — CEX Leaderboard Monitor + Mirror (custom)

1. Poll Bybit/Binance leaderboard API every 60s.
2. Detect position changes for tracked traders (compare current open positions).
3. When a position opens, replicate proportionally.

**Gap:** Leaderboard APIs don't expose real-time positions — only aggregate stats.
To see real-time positions, you'd need the trader to share their UID and for their
positions to be public (some Bybit master traders make positions public).

### Approach C — On-Chain Wallet Monitor (best for DeFi/TON)

For on-chain wallets, every trade is visible in real time:

1. **Discovery**: use Dune/Nansen/GMGN to find 3-5 high-return wallets.
2. **Monitor**: subscribe to each wallet's transaction stream.
   - TON: poll `toncenter.com/api/v2/getTransactions?address=<wallet>` every 30s.
   - EVM: use `eth_getLogs` or a webhook service (Alchemy/QuickNode notify).
3. **Decode**: parse the swap transaction — extract token in, token out, amount.
4. **Mirror**: execute the same swap on our DEX (DeDust/STON.fi for TON, Uniswap for ETH).

**Latency:** 30–60s behind the original wallet. Acceptable for swing trades,
problematic for meme coin sniping (price moves in seconds).

### Approach D — Real-Time Mempool Monitoring (advanced)

Watch the mempool for pending transactions from target wallets before they confirm.
Mirror the trade in the same block.

**Feasibility:** Requires running a full node or paying for mempool access (Blocknative,
Flashbots). Overkill for a $10 experiment. Not recommended yet.

---

## Risks

| Risk | Description | Mitigation |
|------|-------------|------------|
| **Latency disadvantage** | We're always behind the original wallet | Stick to slow-moving assets (BTC, ETH, TON) not meme coins |
| **MEV bots** | Copying a bot that sandwiches trades — their edge vanishes when copied | Screen for human-like trade timing, not sub-second intervals |
| **Survivorship bias** | Past performance ≠ future performance | Require 90+ day history, ≥20 trades, diversify across 3-5 wallets |
| **Wallet size mismatch** | $1M whale buying; we put in $5 — their liquidity ≠ our liquidity | Irrelevant at our scale; we're price-takers either way |
| **Rug / exit liquidity** | Wallet dumps on followers | Only copy on assets with deep liquidity (BTC, ETH, TON) |
| **Correlated drawdown** | All copied wallets lose at same time | Diversify wallets across different strategies/chains |

---

## Recommended Starting Point

Given current stack (Bybit + TON/DeDust):

1. **Short term:** Browse Bybit's copy trading leaderboard manually. Find 1-2 master
   traders with 90-day ROI > 30%, drawdown < 20%, ≥ 50 trades. Allocate $5 via
   Bybit's native copy trading. Zero code, immediate exposure.

2. **Medium term:** Build a TON wallet monitor. Identify 3 high-return wallets via
   GMGN or Cielo. Poll their transaction history every 60s via toncenter API.
   Decode DEX swaps and mirror on DeDust. Extend the existing `ton-bot/` module.

3. **Long term:** Aggregate leaderboard screener that ranks wallets by Sharpe ratio
   across on-chain and CEX sources, auto-rotates out underperforming wallets.

---

## Implementation Estimate

| Component | Effort |
|-----------|--------|
| Bybit native copy (manual setup) | 30 min |
| TON wallet monitor (toncenter polling) | 1 day |
| Swap decoder (parse DeDust tx) | 1 day |
| Mirror execution (reuse ton-bot executor) | 0.5 day |
| Wallet scoring / auto-discovery | 2 days |
| **Total (TON copy trading MVP)** | **~2.5 days** |
