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

import aiohttp
import ccxt
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

import db
import executor
import reporter
from reporter import START_USDT
from strategy import get_signal, get_regime

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
    import datetime as dt
    exchange  = make_exchange()
    portfolio = await executor.get_total_portfolio(exchange)
    usdt_bal  = await executor.get_balance(exchange)
    btc_bal   = await executor.get_btc_balance(exchange)
    position  = db.get_open_position()
    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    price     = float(ticker["last"])
    paused    = context.bot_data.get("paused", False)

    pnl_from_start = portfolio - 10.0  # vs $10 starting capital
    pnl_pct_start  = pnl_from_start / 10.0 * 100

    lines = [
        f"📊 STATUS  {'⏸ PAUSED' if paused else '▶️ TRADING'}",
        f"BTC/USDT: ${price:,.2f}",
        f"",
        f"💰 Portfolio: ${portfolio:.4f} ({pnl_pct_start:+.1f}% vs start)",
        f"  USDT: ${usdt_bal:.4f}",
        f"  BTC:  {btc_bal:.6f} (${btc_bal * price:.4f})",
    ]

    if position:
        entry      = position["entry_price"]
        pnl_pct    = (price - entry) / entry * 100
        pnl_usdt   = (price - entry) / entry * position["size_usdt"]
        tp_price   = entry * (1 + executor.TP_PCT)
        entry_time = dt.datetime.fromisoformat(position["ts"].replace("Z", "+00:00"))
        now        = dt.datetime.now(dt.timezone.utc)
        elapsed    = now - entry_time
        hours, rem = divmod(int(elapsed.total_seconds()), 3600)
        mins       = rem // 60
        lines += [
            f"",
            f"📍 Open position",
            f"  Bought at: ${entry:,.2f} | {hours}h {mins}m ago",
            f"  Profit/Loss: {pnl_pct:+.2f}% (${pnl_usdt:+.4f})",
            f"  Auto-sell at: ${tp_price:,.2f} (+8%)",
        ]
    else:
        lines += ["", "📍 No open position — watching for entry signal"]

    await update.message.reply_text("\n".join(lines))


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


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    exchange = make_exchange()
    try:
        ticker  = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
        price   = float(ticker["last"])
        change  = float(ticker.get("percentage") or 0)
        high24  = float(ticker.get("high") or 0)
        low24   = float(ticker.get("low") or 0)
        bid     = float(ticker.get("bid") or price)
        ask     = float(ticker.get("ask") or price)
        spread  = (ask - bid) / bid * 100 if bid > 0 else 0

        ohlcv   = await asyncio.to_thread(exchange.fetch_ohlcv, PAIR, TIMEFRAME, limit=CANDLES)
        signal, rsi, macd_hist, _ = get_signal(ohlcv)
        signal_emoji = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(signal, "⚪")

        fg_label, fg_value = "Unknown", "?"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://api.alternative.me/fng/?limit=1", timeout=aiohttp.ClientTimeout(total=5)) as r:
                    data = await r.json()
                    fg_value = int(data["data"][0]["value"])
                    fg_raw   = data["data"][0]["value_classification"]
                    fg_label = fg_raw
                    fg_emoji = "😱" if fg_value < 25 else "😨" if fg_value < 45 else "😐" if fg_value < 55 else "😊" if fg_value < 75 else "🤑"
        except Exception:
            fg_emoji = "❓"

        change_sign = "+" if change >= 0 else ""
        lines = [
            f"₿ BTC/USDT  ${price:,.2f}  ({change_sign}{change:.1f}%)",
            f"24h: ${low24:,.0f} – ${high24:,.0f}",
            f"Spread: {spread:.3f}%",
            f"",
            f"{signal_emoji} Signal: {signal}",
            f"RSI: {rsi:.1f} | MACD hist: {macd_hist:+.2f}",
            f"",
            f"{fg_emoji} Fear & Greed: {fg_value}/100 ({fg_label})",
        ]
        if fg_value < 30:
            lines.append("Historically: extreme fear = potential buying opportunity")
        elif fg_value > 75:
            lines.append("Historically: extreme greed = consider taking profit")

        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"⚠️ Error fetching price: {e}")


async def cmd_glossary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    await update.message.reply_text(
        "📖 Glossary\n"
        "\n"
        "P&L — Profit & Loss. How much you made or lost on a trade.\n"
        "  +$0.50 = you're up 50 cents\n"
        "  -$0.50 = you're down 50 cents\n"
        "\n"
        "TP — Take Profit. The price where the bot automatically sells to lock in a gain.\n"
        "  Currently set at +8% above entry price.\n"
        "\n"
        "SL — Stop Loss. The price where the bot would normally sell to cut a loss.\n"
        "  This bot alerts instead of auto-selling — you decide when to exit.\n"
        "  Currently alerts at -5%, -10%, -15%.\n"
        "\n"
        "Entry — The price you bought BTC at.\n"
        "\n"
        "Portfolio — Total value of everything: USDT cash + BTC you're holding.\n"
        "\n"
        "RSI — Relative Strength Index. Measures if BTC is overbought or oversold.\n"
        "  Below 45 = possibly oversold (bot looks to buy)\n"
        "  Above 65 = possibly overbought (bot stays out)\n"
        "\n"
        "MACD — Momentum indicator. Confirms the RSI signal.\n"
        "  Positive histogram = upward momentum (supports buying)\n"
        "  Negative histogram = downward momentum (supports waiting)\n"
        "\n"
        "Signal — Bot's decision each poll: BUY / HOLD / SELL.\n"
        "  Bot only acts on BUY. HOLD = wait. SELL = not used (we hold BTC).\n"
        "\n"
        "Commands: /status /log /pause /resume /glossary"
    )


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

        # ── In a position: check SL/TP ────────────────────────────────────
        if position:
            trigger = await executor.check_sl_tp(exchange, position)
            if trigger:
                result    = await executor.close_position(exchange, position, trigger)
                portfolio = await executor.get_total_portfolio(exchange)
                await alert(reporter.close_card(trigger, result["exit_price"], result["pnl_usdt"], portfolio))
                reporter.maybe_append_x_post("sold", result["exit_price"], result["pnl_usdt"], portfolio)
            else:
                # Send hourly hold update (every 4 polls at 15-min interval)
                polls = context.bot_data.get("hold_polls", 0) + 1
                context.bot_data["hold_polls"] = polls
                if polls % 4 == 0:
                    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
                    price     = float(ticker["last"])
                    entry     = position["entry_price"]
                    pnl_pct   = (price - entry) / entry * 100
                    pnl_usdt  = (price - entry) / entry * position["size_usdt"]
                    portfolio = await executor.get_total_portfolio(exchange)
                    sl_price  = entry * (1 + executor.SL_PCT)
                    tp_price  = entry * (1 + executor.TP_PCT)
                    await alert(
                        f"📍 HOLDING BTC/USDT\n"
                        f"Bought at: ${entry:,.2f} | Now: ${price:,.2f}\n"
                        f"Profit/Loss: {pnl_pct:+.2f}% (${pnl_usdt:+.4f})\n"
                        f"Auto-sell target (TP): ${tp_price:,.2f} (+8%)\n"
                        f"Alert threshold: ${sl_price:,.2f} (-5%)\n"
                        f"Total portfolio: ${portfolio:.2f}\n"
                        f"Type /glossary to explain terms"
                    )
            return

        # ── No position: look for entry ───────────────────────────────────
        ohlcv     = await asyncio.to_thread(exchange.fetch_ohlcv, PAIR, TIMEFRAME, limit=CANDLES)
        signal, rsi, macd_hist, reason = get_signal(ohlcv)
        regime, adx = get_regime(ohlcv)
        portfolio = await executor.get_total_portfolio(exchange)

        ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
        price     = float(ticker["last"])

        # Fetch market context (non-blocking — failures just return defaults)
        funding_bias, funding_rate = await executor.get_funding_bias(exchange)
        book_healthy, spread_pct, book_imbalance = await executor.get_book_health(exchange)

        # Store context for Mission Control
        context.bot_data["regime"]         = regime
        context.bot_data["adx"]            = adx
        context.bot_data["funding_bias"]   = funding_bias
        context.bot_data["funding_rate"]   = funding_rate
        context.bot_data["spread_pct"]     = spread_pct
        context.bot_data["book_imbalance"] = book_imbalance
        context.bot_data["last_rsi"]       = rsi
        context.bot_data["last_macd"]      = macd_hist
        context.bot_data["last_price"]     = price

        logger.info("Signal: %s | RSI=%.1f MACD=%.4f | Regime=%s ADX=%.1f | Funding=%s",
                    signal, rsi, macd_hist, regime, adx, funding_bias)
        await alert(reporter.signal_card(signal, rsi, macd_hist, reason, price, portfolio,
                                         regime=regime, funding_bias=funding_bias))

        if signal != "BUY":
            return

        if context.bot_data.get("paused"):
            logger.info("Paused — skipping BUY entry")
            return

        # Regime filter — skip in choppy or panic
        if regime == "panic":
            await alert(f"⚡ BUY signal suppressed — market in PANIC mode (ATR spike). Waiting for calm.")
            return
        if regime == "choppy":
            await alert(f"⚠️ BUY signal suppressed — market CHOPPY (ADX {adx:.1f}). Waiting for trend.")
            return

        # Funding filter — skip if longs are crowded
        if funding_bias == "crowded_long":
            await alert(f"⚠️ BUY signal suppressed — perp funding rate {funding_rate*100:.4f}% (crowded longs). Waiting.")
            return

        # Book health filter — skip on wide spread
        if not book_healthy:
            await alert(f"⚠️ BUY signal suppressed — spread {spread_pct:.3f}% too wide. Waiting for liquidity.")
            return

        if portfolio < executor.MIN_ORDER * 2:
            await alert(f"⚠️ Balance below minimum (${portfolio:.2f}). Halting trades.")
            context.bot_data["paused"] = True
            return

        result = await executor.place_buy(exchange)
        if result is None:
            await alert("⚠️ Order failed — balance too low.")
            return

        context.bot_data["hold_polls"] = 0
        portfolio = await executor.get_total_portfolio(exchange)
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


# ── Heartbeat job ─────────────────────────────────────────────────────────────

async def heartbeat(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    try:
        exchange  = make_exchange()
        portfolio = await executor.get_total_portfolio(exchange)
        position  = db.get_open_position()
        paused    = "⏸ paused" if context.bot_data.get("paused") else "▶️ trading"
        if position:
            ticker   = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
            price    = float(ticker["last"])
            pnl_pct  = (price - position["entry_price"]) / position["entry_price"] * 100
            pos_str  = f"holding BTC @ ${position['entry_price']:,.0f} ({pnl_pct:+.1f}%)"
        else:
            pos_str = "no open position"
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"💓 Alive | ${portfolio:.2f} | {pos_str} | {paused}",
        )
    except Exception as e:
        logger.error("Heartbeat error: %s", e)


# ── Daily summary job ─────────────────────────────────────────────────────────

async def daily_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    try:
        exchange  = make_exchange()
        portfolio = await executor.get_total_portfolio(exchange)
        await context.bot.send_message(chat_id=chat_id, text=reporter.daily_summary_card(portfolio))
    except Exception as e:
        logger.error("Daily summary error: %s", e)


# ── Mission Control ───────────────────────────────────────────────────────────

async def _build_mc_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    import datetime as dt
    exchange  = make_exchange()
    portfolio = await executor.get_total_portfolio(exchange)
    usdt_bal  = await executor.get_balance(exchange)
    btc_bal   = await executor.get_btc_balance(exchange)
    position  = db.get_open_position()
    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    price     = float(ticker["last"])
    change    = float(ticker.get("percentage") or 0)

    regime       = context.bot_data.get("regime", "—")
    funding_bias = context.bot_data.get("funding_bias", "—")
    rsi          = context.bot_data.get("last_rsi", 0.0)
    macd         = context.bot_data.get("last_macd", 0.0)
    spread       = context.bot_data.get("spread_pct", 0.0)
    paused       = context.bot_data.get("paused", False)

    regime_emoji  = {"trending": "📊", "choppy": "〰️", "panic": "⚡"}.get(regime, "❓")
    funding_emoji = {"crowded_long": "🔴", "crowded_short": "🟢", "neutral": "⚪"}.get(funding_bias, "⚪")
    change_sign   = "+" if change >= 0 else ""
    pnl_from_start = (portfolio - START_USDT) / START_USDT * 100

    lines = [
        f"🖥️  MISSION CONTROL  —  {dt.datetime.now(dt.timezone.utc).strftime('%H:%M UTC')}",
        f"",
        f"₿ ${price:,.2f} ({change_sign}{change:.1f}%)  |  {regime_emoji} {regime}  |  {funding_emoji} {funding_bias}",
        f"📈 RSI: {rsi:.1f}  MACD: {macd:+.2f}  Spread: {spread:.3f}%",
        f"",
    ]

    if position:
        entry   = position["entry_price"]
        pnl_pct = (price - entry) / entry * 100
        pnl_usd = (price - entry) / entry * position["size_usdt"]
        tp      = entry * (1 + executor.TP_PCT)
        entry_dt = dt.datetime.fromisoformat(position["ts"].replace("Z", "+00:00"))
        elapsed  = dt.datetime.now(dt.timezone.utc) - entry_dt
        h, rem   = divmod(int(elapsed.total_seconds()), 3600)
        m        = rem // 60
        lines += [
            f"📍 Holding  {h}h {m}m",
            f"  Bought ${entry:,.2f} → ${price:,.2f}  ({pnl_pct:+.2f}%  ${pnl_usd:+.4f})",
            f"  Auto-sell at: ${tp:,.2f}",
            f"",
        ]
    else:
        lines += [f"📍 No position  |  {'⏸ PAUSED' if paused else '▶️ watching'}", ""]

    lines += [
        f"💼 ${portfolio:.4f}  ({pnl_from_start:+.1f}% vs start)",
        f"  USDT ${usdt_bal:.4f}  |  BTC {btc_bal:.6f} (${btc_bal*price:.4f})",
    ]
    return "\n".join(lines)


async def mission_control_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Silently edit the Mission Control message every 15 min."""
    mc_msg_id = context.bot_data.get("mc_msg_id")
    chat_id   = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    try:
        text = await _build_mc_text(context)
        if mc_msg_id:
            try:
                await context.bot.edit_message_text(chat_id=chat_id, message_id=mc_msg_id, text=text)
            except Exception:
                # Message too old or deleted — send a fresh one
                msg = await context.bot.send_message(chat_id=chat_id, text=text)
                context.bot_data["mc_msg_id"] = msg.message_id
        else:
            msg = await context.bot.send_message(chat_id=chat_id, text=text)
            context.bot_data["mc_msg_id"] = msg.message_id
    except Exception as e:
        logger.error("Mission Control update error: %s", e)


async def cmd_mc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a fresh Mission Control message and track its ID for auto-updates."""
    if str(update.effective_chat.id) != os.environ["TELEGRAM_ALLOWED_CHAT_ID"]:
        return
    try:
        text = await _build_mc_text(context)
        msg  = await update.message.reply_text(text)
        context.bot_data["mc_msg_id"] = msg.message_id
    except Exception as e:
        await update.message.reply_text(f"⚠️ {e}")


# ── Startup ───────────────────────────────────────────────────────────────────

async def on_startup(app: Application) -> None:
    chat_id  = os.environ["TELEGRAM_ALLOWED_CHAT_ID"]
    exchange = make_exchange()
    testnet  = os.environ.get("BYBIT_TESTNET", "true").lower() == "true"

    # Register Telegram command menu (shows in "/" popup)
    from telegram import BotCommand
    await app.bot.set_my_commands([
        BotCommand("status",   "Portfolio balance and open position"),
        BotCommand("price",    "BTC price, 24h range, RSI, Fear & Greed"),
        BotCommand("mc",       "Open Mission Control live dashboard"),
        BotCommand("log",      "Last 10 trades"),
        BotCommand("pause",    "Pause new entries"),
        BotCommand("resume",   "Resume trading"),
        BotCommand("glossary", "Explain P&L, TP, SL and other terms"),
    ])

    # Clock sync check — alert if local clock is >10s behind exchange
    try:
        server_ts = exchange.milliseconds()
        local_ts  = int(__import__("time").time() * 1000)
        drift_s   = abs(server_ts - local_ts) / 1000
        if drift_s > 10:
            await app.bot.send_message(chat_id=chat_id, text=f"⚠️ Clock drift {drift_s:.1f}s vs exchange. Check NTP.")
            logger.warning("Clock drift: %.1fs", drift_s)
    except Exception:
        pass

    # Reconcile spot position on restart
    mismatch = await executor.reconcile(exchange)
    if mismatch:
        await app.bot.send_message(chat_id=chat_id, text=f"⚠️ Position mismatch on startup: {mismatch}. Check Bybit manually.")

    usdt_bal  = await executor.get_balance(exchange)
    btc_bal   = await executor.get_btc_balance(exchange)
    ticker    = await asyncio.to_thread(exchange.fetch_ticker, PAIR)
    btc_price = float(ticker["last"])
    btc_value = btc_bal * btc_price
    portfolio = usdt_bal + btc_value
    position  = db.get_open_position()
    mode      = "TESTNET" if testnet else "LIVE"

    lines = [
        f"🤖 Bot online [{mode}]",
        f"BTC/USDT @ ${btc_price:,.2f}",
        f"",
        f"💰 Balance",
        f"  USDT: ${usdt_bal:.4f}",
        f"  BTC:  {btc_bal:.6f} (${btc_value:.4f})",
        f"  Total: ${portfolio:.4f}",
        f"",
    ]

    if position:
        entry    = position["entry_price"]
        pnl_pct  = (btc_price - entry) / entry * 100
        pnl_usdt = (btc_price - entry) / entry * position["size_usdt"]
        sl_price = entry * (1 + executor.SL_PCT)
        tp_price = entry * (1 + executor.TP_PCT)
        lines += [
            f"📍 Open position",
            f"  Entry: ${entry:,.2f} | Now: ${btc_price:,.2f}",
            f"  P&L: {pnl_pct:+.2f}% (${pnl_usdt:+.4f})",
            f"  SL: ${sl_price:,.2f} | TP: ${tp_price:,.2f}",
            f"",
        ]
    else:
        lines.append("📍 No open position")
        lines.append("")

    lines += [
        f"⚙️ RSI14+MACD | 15m | SL -5% TP +8%",
        f"Commands: /status /pause /resume /log",
    ]

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
    app.bot_data["paused"] = False

    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("price",    cmd_price))
    app.add_handler(CommandHandler("mc",       cmd_mc))
    app.add_handler(CommandHandler("pause",    cmd_pause))
    app.add_handler(CommandHandler("resume",   cmd_resume))
    app.add_handler(CommandHandler("log",      cmd_log))
    app.add_handler(CommandHandler("glossary", cmd_glossary))

    app.job_queue.run_repeating(poll_market,           interval=POLL_INTERVAL, first=10)
    app.job_queue.run_repeating(mission_control_update, interval=POLL_INTERVAL, first=20)
    app.job_queue.run_repeating(heartbeat,             interval=21600, first=21600)
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
