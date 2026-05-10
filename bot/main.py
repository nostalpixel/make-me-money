"""
make-me-money bot
Claude is given 20 USDT and tries to double it.
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
from strategy import get_signal

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 900  # seconds (15 min)
DAILY_HOUR    = 9    # UTC
DAILY_MIN     = 0
PAIR          = "BTC/USDT"
TIMEFRAME     = "15m"
CANDLES       = 80   # enough for RSI(14) + MACD(12,26,9)


def make_exchange() -> ccxt.bybit:
    return executor._make_exchange(
        api_key=os.environ["BYBIT_API_KEY"],
        secret=os.environ["BYBIT_SECRET"],
        testnet=os.environ.get("BYBIT_TESTNET", "true").lower() == "true",
    )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    exchange = make_exchange()
    portfolio = await executor.get_balance(exchange)
    position  = db.get_open_position()
    await update.message.reply_text(reporter.status_card(portfolio, position))


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    context.bot_data["paused"] = True
    await update.message.reply_text("⏸ Trading paused. Open positions held.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    context.bot_data["paused"] = False
    await update.message.reply_text("▶️ Trading resumed.")


async def cmd_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    trades = db.last_n_trades(10)
    if not trades:
        await update.message.reply_text("No trades yet.")
        return
    lines = []
    for t in trades:
        status = f"{t['exit_reason']} {t['pnl_usdt']:+.4f}" if t["status"] == "closed" else "OPEN"
        lines.append(f"{t['ts'][:16]} {t['side'].upper()} ${t['size_usdt']:.2f} → {status}")
    await update.message.reply_text("\n".join(lines))


# ── Polling job ───────────────────────────────────────────────────────────────

async def poll_market(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]

    async def alert(text: str) -> None:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            pass

    try:
        if context.bot_data.get("paused"):
            return

        exchange = make_exchange()
        position = db.get_open_position()

        # ── In a position: check SL/TP ────────────────────────────────────
        if position:
            trigger = await executor.check_sl_tp(exchange, position)
            if trigger:
                result   = await executor.close_position(exchange, position, trigger)
                portfolio = await executor.get_balance(exchange)
                await alert(reporter.close_card(trigger, result["exit_price"], result["pnl_usdt"], portfolio))
                reporter.maybe_append_x_post("sold", result["exit_price"], result["pnl_usdt"], portfolio)
            return

        # ── No position: look for entry ───────────────────────────────────
        ohlcv  = await asyncio.to_thread(exchange.fetch_ohlcv, PAIR, TIMEFRAME, limit=CANDLES)
        signal = get_signal(ohlcv)
        logger.info("Signal: %s", signal)

        if signal != "BUY":
            return

        portfolio = await executor.get_balance(exchange)
        if portfolio < executor.MIN_ORDER * 2:
            await alert(f"⚠️ Balance below minimum (${portfolio:.2f}). Halting trades.")
            context.bot_data["paused"] = True
            return

        result = await executor.place_buy(exchange)
        if result is None:
            await alert("⚠️ Order failed — balance too low.")
            return

        portfolio = await executor.get_balance(exchange)
        reason    = f"RSI<45 + MACD bullish"
        await alert(reporter.trade_card("BUY", result["price"], result["size_usdt"], reason, portfolio))

    except ccxt.AuthenticationError:
        await alert("🔐 API auth error — check your Bybit API key.")
        logger.critical("AuthenticationError — halting")
        context.bot_data["paused"] = True

    except ccxt.InsufficientFunds:
        await alert("⚠️ Insufficient funds on exchange.")
        context.bot_data["paused"] = True

    except sqlite3.OperationalError as e:
        await alert(f"🚨 DB error — manual review needed: {e}")
        context.bot_data["paused"] = True

    except Exception as e:
        logger.error("Unhandled error in poll_market: %s", e, exc_info=True)
        await alert(f"⚠️ Error in polling cycle: {e}. Skipping.")


# ── Daily summary job ─────────────────────────────────────────────────────────

async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    try:
        exchange  = make_exchange()
        portfolio = await executor.get_balance(exchange)
        await context.bot.send_message(chat_id=chat_id, text=reporter.daily_summary_card(portfolio))
    except Exception as e:
        logger.error("Daily summary error: %s", e)


# ── Startup ───────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    chat_id  = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    exchange = make_exchange()
    testnet  = os.environ.get("BYBIT_TESTNET", "true").lower() == "true"

    # Reconcile spot position on restart
    mismatch = await executor.reconcile(exchange)
    if mismatch:
        await app.bot.send_message(chat_id=chat_id, text=f"⚠️ Position mismatch on startup: {mismatch}. Check Bybit manually.")

    portfolio = await executor.get_balance(exchange)
    mode      = "TESTNET" if testnet else "LIVE"
    await app.bot.send_message(
        chat_id=chat_id,
        text=(
            f"🤖 Bot online [{mode}]\n"
            f"Strategy: RSI14+MACD on BTC/USDT 15m\n"
            f"Portfolio: ${portfolio:.2f} USDT\n"
            f"Goal: $40.00\n"
            f"SL: -5% | TP: +8% | Poll: every 15 min\n"
            f"Commands: /status /pause /resume /log"
        ),
    )


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
    app.bot_data["paused"] = False

    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pause",  cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("log",    cmd_log))

    app.job_queue.run_repeating(poll_market, interval=POLL_INTERVAL, first=10)
    app.job_queue.run_daily(daily_summary, time=__import__("datetime").time(DAILY_HOUR, DAILY_MIN))

    # Graceful shutdown on SIGTERM
    def _sigterm(*_):
        logger.info("SIGTERM received — shutting down")
        asyncio.get_event_loop().create_task(
            app.bot.send_message(
                chat_id=os.environ["TELEGRAM_ALLOWED_CHAT_ID"],
                text="🛑 Bot shutting down (SIGTERM). Check open positions manually.",
            )
        )
        app.stop_running()

    signal.signal(signal.SIGTERM, _sigterm)

    logger.info("Starting bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
