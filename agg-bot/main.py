"""
make-me-money agg-bot
Aggressive dip-buyer: buys BTC on ≥5% 4h drops, holds through drawdowns, sells at +20%.
No stop-loss. Disabled by default — /aggenable to activate.
"""
import asyncio
import logging
import os
import signal
import sqlite3
import sys

import ccxt
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db
import executor
import reporter
from strategy import get_dip

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [agg] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 900   # 15 min
PAIR          = "BTC/USDT"
TIMEFRAME     = "15m"
CANDLES       = 80


def make_exchange() -> ccxt.bybit:
    return executor._make_exchange(
        api_key=os.environ["BYBIT_API_KEY"],
        secret=os.environ["BYBIT_SECRET"],
        testnet=os.environ.get("BYBIT_TESTNET", "true").lower() == "true",
    )


def _auth(update: Update) -> bool:
    return str(update.effective_chat.id) == os.environ["TELEGRAM_ALLOWED_CHAT_ID"]


# ── Commands ──────────────────────────────────────────────────────────────────

async def cmd_aggenable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return
    context.bot_data["enabled"] = True
    await update.message.reply_text(
        "🟢 AGG BOT ENABLED\n"
        "Will buy 90% of USDT when BTC drops ≥5% in 4h.\n"
        "TP: +20% | No stop-loss — holds through all dips.\n"
        "Use /aggdisable to turn off."
    )


async def cmd_aggdisable(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return
    context.bot_data["enabled"] = False
    await update.message.reply_text(
        "🔴 AGG BOT DISABLED\n"
        "No new entries. Any open position is still held.\n"
        "Use /aggenable to turn back on."
    )


async def cmd_aggstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return
    exchange  = make_exchange()
    portfolio = await executor.get_total_portfolio(exchange)
    position  = db.get_open_position()
    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    price     = float(ticker["last"])
    enabled   = context.bot_data.get("enabled", False)
    await update.message.reply_text(reporter.status_card(portfolio, position, price, enabled))


async def cmd_agglog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _auth(update):
        return
    trades = db.last_n_trades(10)
    if not trades:
        await update.message.reply_text("AGG: No trades yet.")
        return
    lines = []
    for t in trades:
        status = f"{t['exit_reason']} {t['pnl_usdt']:+.4f}" if t["status"] == "closed" else "OPEN"
        lines.append(f"{t['ts'][:16]} {t['side'].upper()} ${t['size_usdt']:.2f} → {status}")
    await update.message.reply_text("📋 AGG trades\n" + "\n".join(lines))


# ── Polling job ───────────────────────────────────────────────────────────────

async def poll_market(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]

    async def alert(text: str) -> None:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            pass

    try:
        exchange = make_exchange()
        position = db.get_open_position()

        # ── In a position: check TP and drawdown alerts ───────────────────
        if position:
            hit_tp = await executor.check_tp(exchange, position)
            if hit_tp:
                result    = await executor.close_position(exchange, position, "take_profit")
                portfolio = await executor.get_total_portfolio(exchange)
                await alert(reporter.close_card(result["exit_price"], result["pnl_usdt"], portfolio))
                context.bot_data["alerted_thresholds"] = set()
            else:
                alerted = context.bot_data.setdefault("alerted_thresholds", set())
                msg, pnl_pct = await executor.check_drawdown_alerts(exchange, position, alerted)
                if msg:
                    await alert(msg)

                # Hourly hold update (every 4 polls)
                polls = context.bot_data.get("hold_polls", 0) + 1
                context.bot_data["hold_polls"] = polls
                if polls % 4 == 0:
                    ticker   = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
                    price    = float(ticker["last"])
                    entry    = position["entry_price"]
                    pnl_pct  = (price - entry) / entry * 100
                    pnl_usdt = (price - entry) / entry * position["size_usdt"]
                    portfolio = await executor.get_total_portfolio(exchange)
                    await alert(
                        f"📍 AGG: HOLDING BTC\n"
                        f"Entry: ${entry:,.2f} | Now: ${price:,.2f}\n"
                        f"P&L: {pnl_pct:+.2f}% (${pnl_usdt:+.4f})\n"
                        f"TP target: ${entry * 1.20:,.2f} (+20%) — holding through dips"
                    )
            return

        # ── No position: check for dip entry ─────────────────────────────
        ohlcv     = await asyncio.to_thread(exchange.fetch_ohlcv, PAIR, TIMEFRAME, limit=CANDLES)
        is_dip, drop_pct, reason = get_dip(ohlcv)
        portfolio = await executor.get_total_portfolio(exchange)
        ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
        price     = float(ticker["last"])
        enabled   = context.bot_data.get("enabled", False)

        logger.info("Dip check: is_dip=%s drop=%.2f%% enabled=%s", is_dip, drop_pct * 100, enabled)

        # Throttle non-dip notifications to every 4h
        last_notif_ts = context.bot_data.get("last_notif_ts", 0)
        now_ts        = asyncio.get_event_loop().time()
        prev_dip      = context.bot_data.get("prev_dip", False)
        dip_changed   = is_dip != prev_dip
        overdue       = (now_ts - last_notif_ts) >= 4 * 3600

        if dip_changed or overdue:
            await alert(reporter.signal_card(is_dip, drop_pct, reason, price, portfolio))
            context.bot_data["last_notif_ts"] = now_ts
        context.bot_data["prev_dip"] = is_dip

        if not is_dip:
            return

        if not enabled:
            logger.info("Dip detected but bot is disabled — skipping entry")
            return

        if portfolio < executor.MIN_ORDER * 2:
            await alert(f"⚠️ AGG: Balance too low (${portfolio:.2f}). Top up to resume.")
            return

        result    = await executor.place_buy(exchange)
        if result is None:
            await alert("⚠️ AGG: Order failed — balance too low.")
            return

        context.bot_data["hold_polls"]          = 0
        context.bot_data["alerted_thresholds"]  = set()
        portfolio = await executor.get_total_portfolio(exchange)
        await alert(reporter.trade_card(result["price"], result["size_usdt"], reason, portfolio))

    except ccxt.AuthenticationError:
        await alert("🔐 AGG: API auth error — check Bybit key.")
        logger.critical("AuthenticationError")

    except ccxt.InsufficientFunds:
        await alert("⚠️ AGG: Insufficient funds.")

    except sqlite3.OperationalError as e:
        await alert(f"🚨 AGG: DB error: {e}")

    except Exception as e:
        logger.error("Unhandled error in agg poll_market: %s", e, exc_info=True)
        await alert(f"⚠️ AGG: Error in poll cycle: {e}")


# ── Daily summary ─────────────────────────────────────────────────────────────

async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    try:
        exchange  = make_exchange()
        portfolio = await executor.get_total_portfolio(exchange)
        await context.bot.send_message(chat_id=chat_id, text=reporter.daily_summary_card(portfolio))
    except Exception as e:
        logger.error("Daily summary error: %s", e)


# ── Startup ───────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    chat_id  = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    exchange = make_exchange()
    testnet  = os.environ.get("BYBIT_TESTNET", "true").lower() == "true"
    mode     = "TESTNET" if testnet else "LIVE"

    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("aggenable",  "Enable aggressive dip-buy bot"),
        BotCommand("aggdisable", "Disable aggressive dip-buy bot"),
        BotCommand("aggstatus",  "AGG bot status and open position"),
        BotCommand("agglog",     "Last 10 AGG trades"),
    ])

    mismatch  = await executor.reconcile(exchange)
    portfolio = await executor.get_total_portfolio(exchange)
    position  = db.get_open_position()
    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    price     = float(ticker["last"])

    pos_line = (
        f"📍 Holding BTC  entry=${position['entry_price']:,.2f}"
        if position else "📍 No open position"
    )

    lines = [
        f"🤖 AGG Bot online [{mode}]  —  DISABLED",
        f"BTC/USDT @ ${price:,.2f}",
        f"",
        f"💼 Portfolio: ${portfolio:.4f}",
        f"{pos_line}",
        f"",
        f"⚙️ Strategy: buy 90% on ≥5% 4h dip | TP +20% | No SL",
        f"Use /aggenable to activate when topped up.",
    ]

    if mismatch:
        lines.append(f"⚠️ Position mismatch on startup: {mismatch}")

    await app.bot.send_message(chat_id=chat_id, text="\n".join(lines))


def main() -> None:
    required = ["BYBIT_API_KEY", "BYBIT_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID"]
    missing  = [k for k in required if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing env vars: {', '.join(missing)}")

    db.init()

    app = (
        Application.builder()
        .token(os.environ["TELEGRAM_BOT_TOKEN"])
        .post_init(on_startup)
        .build()
    )
    app.bot_data["enabled"]             = False
    app.bot_data["alerted_thresholds"]  = set()

    app.add_handler(CommandHandler("aggenable",  cmd_aggenable))
    app.add_handler(CommandHandler("aggdisable", cmd_aggdisable))
    app.add_handler(CommandHandler("aggstatus",  cmd_aggstatus))
    app.add_handler(CommandHandler("agglog",     cmd_agglog))

    app.job_queue.run_repeating(poll_market,    interval=POLL_INTERVAL, first=30)
    app.job_queue.run_daily(daily_summary, time=__import__("datetime").time(9, 5))

    def _sigterm(*_):
        logger.info("SIGTERM received — shutting down agg bot")
        asyncio.get_event_loop().create_task(
            app.bot.send_message(
                chat_id=os.environ["TELEGRAM_ALLOWED_CHAT_ID"],
                text="🛑 AGG Bot shutting down. Open positions held on exchange.",
            )
        )
        app.stop_running()

    signal.signal(signal.SIGTERM, _sigterm)

    logger.info("Starting agg bot (disabled by default)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
