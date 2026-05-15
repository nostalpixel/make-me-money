"""
TON trading bot — RSI14+MACD on TON/USDT via DeDust DEX.
Shares the same Telegram bot token as the BTC bot; prefixes all messages with 🪙.
"""
import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db
import executor
import reporter
from strategy import fetch_ohlcv, get_signal, get_ton_price_usdt

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [ton] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 1800   # 30 minutes (matches 30m candles)
DAILY_HOUR    = 9
DAILY_MIN     = 15     # offset from BTC bot to avoid spam at same time


def _mnemonic() -> list[str]:
    raw = os.environ.get("TON_MNEMONIC", "")
    if not raw:
        sys.exit("Missing TON_MNEMONIC in .env")
    return raw.strip().split()


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_ton_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    provider = await executor.make_provider()
    try:
        wallet    = await executor.make_wallet(provider, _mnemonic())
        ton_price = await get_ton_price_usdt()
        ton_bal   = await executor.get_ton_balance(provider, wallet.address)
        usdt_bal  = await executor.get_usdt_balance(provider, wallet.address)
        portfolio = ton_bal * ton_price + usdt_bal
        await update.message.reply_text(reporter.status_card(ton_bal, usdt_bal, ton_price, portfolio))
    finally:
        await provider.close_all()


async def cmd_ton_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    context.bot_data["ton_paused"] = True
    await update.message.reply_text("⏸ TON trading paused.")


async def cmd_ton_resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    context.bot_data["ton_paused"] = False
    await update.message.reply_text("▶️ TON trading resumed.")


async def cmd_ton_log(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    trades = db.last_n_trades(10)
    if not trades:
        await update.message.reply_text("🪙 No TON trades yet.")
        return
    lines = []
    for t in trades:
        status = f"{t['exit_reason']} {t['pnl_usdt']:+.4f}" if t["status"] == "closed" else "OPEN"
        lines.append(f"{t['ts'][:16]} {t['side'].upper()} ${t['size_usdt']:.2f} → {status}")
    await update.message.reply_text("🪙 TON trades:\n" + "\n".join(lines))


# ── Polling job ───────────────────────────────────────────────────────────────

async def poll_market(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]

    async def alert(text: str) -> None:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            pass

    if context.bot_data.get("ton_paused"):
        return

    provider = await executor.make_provider()
    try:
        wallet    = await executor.make_wallet(provider, _mnemonic())
        ton_price = await get_ton_price_usdt()
        ohlcv     = await fetch_ohlcv()
        signal    = get_signal(ohlcv)
        logger.info("TON signal: %s | price=%.4f", signal, ton_price)

        position = db.get_open_position()

        if signal == "SELL" and not position:
            # Not in a trade — exit TON to USDT to protect value
            result = await executor.exit_to_usdt(provider, wallet, ton_price)
            if result:
                portfolio = await executor.get_portfolio_usdt(provider, wallet, ton_price)
                await alert(reporter.trade_card(
                    "SELL (exit to USDT)", ton_price,
                    result["size_usdt"], "RSI>65 + MACD bearish", portfolio,
                ))

        elif signal == "BUY" and position and position["side"] == "sell":
            # We previously sold TON; buy back in
            ton_price2 = ton_price
            pnl        = (position["entry_price"] - ton_price2) / position["entry_price"] * position["size_usdt"]
            db.close_trade(position["id"], ton_price2, "take_profit" if pnl >= 0 else "stop_loss", round(pnl, 4))
            result = await executor.enter_ton(provider, wallet, ton_price2)
            if result:
                portfolio = await executor.get_portfolio_usdt(provider, wallet, ton_price2)
                await alert(reporter.close_card(
                    "take_profit" if pnl >= 0 else "stop_loss",
                    ton_price2, pnl, portfolio,
                ))

    except Exception as e:
        logger.error("TON poll error: %s", e, exc_info=True)
        await alert(f"⚠️ TON bot error: {e}")
    finally:
        await provider.close_all()


async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    provider = await executor.make_provider()
    try:
        wallet    = await executor.make_wallet(provider, _mnemonic())
        ton_price = await get_ton_price_usdt()
        portfolio = await executor.get_portfolio_usdt(provider, wallet, ton_price)
        await context.bot.send_message(
            chat_id=chat_id,
            text=reporter.daily_summary_card(portfolio, ton_price),
        )
    except Exception as e:
        logger.error("TON daily summary error: %s", e)
    finally:
        await provider.close_all()


# ── Startup ───────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    chat_id  = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    provider = await executor.make_provider()
    try:
        wallet    = await executor.make_wallet(provider, _mnemonic())
        ton_price = await get_ton_price_usdt()
        ton_bal   = await executor.get_ton_balance(provider, wallet.address)
        usdt_bal  = await executor.get_usdt_balance(provider, wallet.address)
        portfolio = ton_bal * ton_price + usdt_bal
        await app.bot.send_message(
            chat_id=chat_id,
            text=(
                f"🪙 TON Bot online [MAINNET]\n"
                f"Strategy: RSI14+MACD on TON/USDT 30m (DeDust)\n"
                f"TON: {ton_bal:.4f} | USDT: {usdt_bal:.4f}\n"
                f"Portfolio: ${portfolio:.2f}\n"
                f"Commands: /tonstatus /tonpause /tonresume /tonlog"
            ),
        )
    finally:
        await provider.close_all()


def main() -> None:
    required = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "TON_MNEMONIC"]
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
    app.bot_data["ton_paused"] = False

    app.add_handler(CommandHandler("tonstatus", cmd_ton_status))
    app.add_handler(CommandHandler("tonpause",  cmd_ton_pause))
    app.add_handler(CommandHandler("tonresume", cmd_ton_resume))
    app.add_handler(CommandHandler("tonlog",    cmd_ton_log))

    app.job_queue.run_repeating(poll_market, interval=POLL_INTERVAL, first=30)
    app.job_queue.run_daily(
        daily_summary,
        time=__import__("datetime").time(DAILY_HOUR, DAILY_MIN),
    )

    def _sigterm(*_):
        logger.info("SIGTERM — TON bot shutting down")
        app.stop_running()

    signal.signal(signal.SIGTERM, _sigterm)

    logger.info("Starting TON bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
