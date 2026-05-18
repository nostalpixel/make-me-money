# make-me-money

Project started with:

'''
create repo here:

echo "# make-me-money" >> README.md
git init
git add README.md
git commit -m "first commit"
git branch -M main
git remote add origin git@github.com:nostalpixel/make-me-money.git
git push -u origin main

then read description, and call plan ceo review or whatsover


your task will be:

"pure Claude code experiment, where Claude is given 20 USDT and tries to make money"

you need to improvise, including how I give you money.
'''

---

# make-me-money 🤖

> A pure Claude Code experiment. Claude is given **$20 USDT** and told to turn it into **$40**.  
> No human in the loop. No borrowed money. No proprietary services.

[![live](https://img.shields.io/badge/status-live-brightgreen)](#)
[![exchange](https://img.shields.io/badge/exchange-Bybit%20spot-orange)](#)
[![pair](https://img.shields.io/badge/pair-BTC%2FUSDT-blue)](#)
[![strategy](https://img.shields.io/badge/strategy-RSI14%20%2B%20MACD-purple)](#)

---

## What is this

Claude Code designed a trading strategy, wrote all the code, debugged the backtest, and deployed the bot — autonomously, in a single session.

The bot trades **BTC/USDT spot** on Bybit using a **RSI(14) + MACD histogram** confirmation signal. Every decision gets reported to Telegram in real time. Significant trades get drafted as X posts in [`social/X.md`](social/X.md).

**Goal:** $20 → $40.  
**Rules:** open-source only, no leverage, no borrowed capital.

---

## Strategy

| Parameter | Value |
|-----------|-------|
| Pair | BTC/USDT spot |
| Timeframe | 15-minute candles |
| Signal | RSI(14) + MACD histogram |
| BUY trigger | RSI < 45 **and** MACD hist > 0 |
| SELL trigger | RSI > 65 **and** MACD hist < 0 |
| Position size | 50% of portfolio per trade |
| Stop loss | −5% |
| Take profit | +8% |
| Poll interval | every 15 minutes |

One position at a time. SL/TP checked every poll. No leverage.

---

## Architecture

```
bot/
├── main.py       # Telegram bot, command handlers, job scheduler
├── strategy.py   # Pure signal function — RSI + MACD
├── executor.py   # Bybit order execution (all async via asyncio.to_thread)
├── reporter.py   # Telegram message formatting + X post drafts
├── db.py         # SQLite trade log and daily P&L
└── backtest.py   # 30-day historical simulation (no API key needed)

social/
└── X.md          # Auto-generated post drafts on ±5% trades

deps/
├── requirements.txt
└── .env.example
```

---

## Running locally

**Prerequisites:** Docker + Docker Compose

```bash
git clone git@github.com:nostalpixel/make-me-money.git
cd make-me-money
cp deps/.env.example .env   # fill in your keys
docker compose up --build
```

The bot sends a startup card to Telegram and begins polling immediately.

### Environment variables

```env
BYBIT_API_KEY=...
BYBIT_SECRET=...
BYBIT_TESTNET=false          # true for sandbox
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_ID=... # your chat ID — only you can control the bot
```

---

## Telegram commands

| Command | Description |
|---------|-------------|
| `/status` | Portfolio balance, open position, total P&L |
| `/log` | Last 10 trades with P&L |
| `/pause` | Halt new trades (open positions held) |
| `/resume` | Resume trading |

---

## Deploying to EC2

```bash
git clone git@github.com:nostalpixel/make-me-money.git
cd make-me-money
cp deps/.env.example .env && nano .env
docker compose up -d
```

`restart: unless-stopped` keeps the bot alive across reboots. Trade history persists in `trade.db` (mounted as a volume).

---

## Backtest

Runs against 30 days of real Bybit OHLCV data. No API key required.

```bash
python bot/backtest.py
```

---

## Progress

| Date | Portfolio | Event |
|------|-----------|-------|
| 2026-05-10 | $20.00 | Bot deployed |

*This table is updated as the experiment progresses.*

---

## TON Bot

A second bot running in parallel, trading **TON/USDT on DeDust DEX** (on-chain, no CEX).

| Parameter | Value |
|-----------|-------|
| Pair | TON/USDT spot |
| DEX | DeDust v2 (TON mainnet) |
| Timeframe | 30-minute candles (GeckoTerminal) |
| Signal | RSI(14) + MACD histogram |
| SELL trigger | RSI > 65 + MACD bearish → swap TON → USDT |
| BUY trigger | RSI < 45 + MACD bullish → swap USDT → TON |
| Gas reserve | 1 TON always kept in wallet |
| Poll interval | every 30 minutes |

```
ton-bot/
├── main.py       # Telegram bot, commands, job scheduler
├── strategy.py   # RSI+MACD using GeckoTerminal OHLCV
├── executor.py   # TON wallet (pytoniq) + DeDust swaps
├── reporter.py   # Telegram message formatting
└── db.py         # SQLite trade log
```

### Extra env vars needed

```env
TON_MNEMONIC=word1 word2 ... word24   # 24-word TON wallet mnemonic
```

### TON Telegram commands

| Command | Description |
|---------|-------------|
| `/tonstatus` | TON + USDT balances, portfolio value, P&L |
| `/tonlog` | Last 10 TON trades |
| `/tonpause` | Pause TON trading |
| `/tonresume` | Resume TON trading |

---

## Updates — 2026-05-18

### Strategy upgrades

- **Regime filter** — ADX(14) + ATR ratio now classify market as `trending`, `choppy`, or `panic`. Entries blocked in choppy/panic regimes.
- **Repainting fix** — last (still-forming) candle is now dropped before signal calculation to prevent false signals.
- **Funding rate bias** — fetched from Bybit perpetuals as a contrarian signal (`crowded_long` / `crowded_short` / `neutral`).

### New Telegram commands

| Command | Description |
|---------|-------------|
| `/price` | Live BTC price, 24h range, spread, current signal, Fear & Greed index |
| `/howfar` | Visual RSI/MACD bars showing exactly how far from a BUY signal |

### Signal updates every poll

The bot now sends a Telegram message every 15 minutes (when no position is open) with the current signal, RSI, MACD histogram, regime, and the reason it's holding — so you're never in the dark.