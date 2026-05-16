# Infrastructure & Stack Decisions

> Researched 2026-05-17. Honest answers — no hype.

---

## Go vs Rust vs Python

### Does the language matter for a trading bot?

Short answer: **not at this scale, and not for this strategy.**

The bottleneck in a 5–15 minute signal bot is **network latency to the exchange**
(50–150ms per REST call) and **signal computation** (pandas/ta on 80 candles takes ~2ms).
The language runtime contributes <1ms. Rewriting in Go or Rust buys nothing measurable.

Where language *does* matter:
- **HFT / market making**: sub-millisecond order placement, tick-by-tick processing.
  Go or Rust needed. We are not there.
- **Mempool sniping / MEV**: you need to be in the same block. Rust + custom networking.
  Far out of scope.
- **Large backtests over years of tick data**: Python with numpy/pandas is slow.
  Go would be 10–30× faster here. Worth it only if backtests take >10 min.

### Verdict

| Language | Execution speed | Dev speed | Ecosystem (crypto libs) | Verdict |
|----------|----------------|-----------|------------------------|---------|
| Python | Slow (~2ms signal) | Fast | Best (ccxt, pytoniq, ta, pandas) | ✅ Keep |
| Go | Fast (~0.1ms) | Medium | Decent (go-bybit, no ta-lib) | Overkill now |
| Rust | Fastest | Slow | Thin (few crypto libs) | Way overkill |

**If we ever move to <1 min timeframes or WebSocket-driven execution, consider Go.**
Python with asyncio handles WebSockets fine for 5–15 min strategies.

Rewriting now would take 2–3 weeks and produce zero trading edge improvement.

---

## Docker vs Bare Metal

### Does Docker add meaningful overhead?

Docker adds ~1–5ms of overhead per process start and ~5% CPU overhead on steady-state
workloads. For a bot that runs a loop every 5 minutes, this is **completely irrelevant**.

### What Docker actually gives us

- Reproducible environment — no "works on my Mac" failures when moving to a server
- Easy deploy: `git pull && docker compose up -d` — done
- Isolation: bot can't accidentally clobber system Python or interfere with other processes
- Restart policy: `restart: unless-stopped` handles crashes automatically

### Verdict

**Keep Docker.** The overhead is noise. The operational benefits are real.
Bare metal would save ~5ms and cost hours of environment management. Bad trade.

---

## EC2 in Singapore — Is It Worth It?

### Latency numbers (current vs hosted)

| Setup | Latency to Bybit | Notes |
|-------|-----------------|-------|
| Mac at home (NZ) | ~150–250ms | Variable, ISP routing |
| EC2 ap-southeast-1 (Singapore) | ~3–8ms | Bybit's matching engine is in SG |
| DigitalOcean SGP | ~5–10ms | Cheaper than EC2 |

### Does this matter for our strategy?

**For a 5–15 min signal bot: No.** If the signal fires, placing the order 200ms later
vs 5ms later changes the fill price by cents on a $10 order. Immaterial.

**When it starts to matter:**
- Sub-1-minute strategies
- WebSocket-driven execution where you're reacting to real-time ticks
- Copy trading where you need to beat other copiers to a fill

### Cost comparison

| Option | Monthly cost | Notes |
|--------|-------------|-------|
| Mac at home | $0 | Already running |
| DigitalOcean Basic (1 vCPU, 1GB, SGP) | $6 | Good enough for this bot |
| EC2 t3.micro (Singapore) | ~$8 | Free tier for 12 months |
| EC2 t3.small (Singapore) | ~$15 | More comfortable headroom |

### Verdict

**Not worth it right now.** The bot runs fine on a Mac.
**Worth it when:** moving to a VPS for 24/7 reliability without keeping a Mac running,
OR when strategies go to 1-min timeframes.

If you do move: **DigitalOcean SGP $6/mo** is the sweet spot. EC2 free tier is also
fine for 12 months, then gets expensive.

---

## Do We Need a Domain / Hostname?

### What would we use it for?

- **Telegram webhooks** instead of polling (bot receives updates via HTTPS POST instead
  of long-polling). Requires a public HTTPS endpoint. Reduces load, slightly lower latency.
- **TON wallet webhooks** (QuickNode/Toncenter push notifications).
- **Mini app** (see below) — requires a domain for the web app URL.
- **Status dashboard** — public or private web UI.

### Do we need it now?

No. Long-polling works fine. Webhooks are a nice-to-have.

**If/when we move to a VPS:** get a domain. A `.xyz` domain is $1–2/year.
Use Caddy or nginx for HTTPS (free Let's Encrypt cert). Total extra cost: ~$2/year.

---

## Telegram Mini App — Is It Worth It?

### What is a Telegram Mini App?

A web app that opens inside Telegram (full-screen WebView). Users tap a button in
the bot and see a rich UI — charts, tables, toggles — instead of text messages.

### What it could do for this bot

- **Live portfolio dashboard**: balance, open positions, P&L chart, trade history table
- **Strategy control panel**: enable/disable strategies, set allocations with sliders
- **Wallet tracker**: list of watched wallets, their recent trades, copy status
- **Performance analytics**: win rate, Sharpe, drawdown charts per strategy

### What it takes

- A small web app (React or vanilla JS) served from a public URL
- `initData` validation on the server side (verifies the request is from Telegram)
- A domain + HTTPS (see above)
- Telegram's `web_app_url` button in the bot to launch it

### Is it worth it?

**Eventually yes, now no.** It's the right UX direction as the bot grows.
Building it before the core strategy works is premature.

**Trigger to build it:** when we have 3+ active strategies and allocation management
becomes painful through text commands.

---

## Summary: What to Actually Do

| Decision | Recommendation | When |
|----------|---------------|------|
| Language | Stay Python | Never change unless <1min TF |
| Docker | Keep it | Always |
| EC2 Singapore | Get a $6 DO droplet | When moving to 24/7 server |
| Domain | Get a $2/yr .xyz | When moving to server |
| Mini app | Build it | After 3+ strategies are live |
| Go/Rust rewrite | Don't | Unless HFT-level latency needed |

**Immediate priority:** none of the above. Close the current trade, implement native
SL/TP and the trend filter, then think about infrastructure.
