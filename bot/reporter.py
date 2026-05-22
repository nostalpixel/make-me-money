import logging
from datetime import datetime, timezone
from pathlib import Path

import db

logger = logging.getLogger(__name__)

SOCIAL_FILE = Path(__file__).parent.parent / "social" / "X.md"
GOAL_USDT   = 40.0
START_USDT  = 20.0
SIG_THRESHOLD = 5.0  # % P&L to trigger X post draft


async def send(context, text: str) -> None:
    """Send a Telegram message. Catch Forbidden silently."""
    try:
        await context.bot.send_message(
            chat_id=context.job.chat_id if hasattr(context, "job") else context._chat_id,
            text=text,
        )
    except Exception as e:
        if "Forbidden" in str(e):
            logger.error("Telegram bot blocked by user — continuing silently")
        else:
            logger.error("Telegram send error: %s", e)


def rsi_zone(rsi: float, rsi_buy: float = 45, rsi_sell: float = 65) -> str:
    if rsi < rsi_buy:
        return "oversold"
    if rsi > rsi_sell:
        return "overbought"
    return "neutral"


def signal_card(signal: str, rsi: float, macd_hist: float, reason: str, price: float, portfolio: float,
                regime: str = "unknown", funding_bias: str = "neutral",
                adx: float = 0.0, book_healthy: bool = True) -> str:
    from strategy import RSI_BUY, RSI_SELL, ADX_TREND_MIN
    emoji         = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}.get(signal, "❓")
    pnl_pct       = (portfolio - START_USDT) / START_USDT * 100
    hist_arrow    = "↑" if macd_hist > 0 else "↓"
    regime_emoji  = {"trending": "📊", "choppy": "〰️", "panic": "⚡", "unknown": "❓"}.get(regime, "❓")
    funding_emoji = {"crowded_long": "🔴", "crowded_short": "🟢", "neutral": "⚪"}.get(funding_bias, "⚪")

    # Decision trace: which BUY conditions passed/failed
    c_rsi     = "✅" if rsi < RSI_BUY     else "❌"
    c_macd    = "✅" if macd_hist > 0      else "❌"
    c_regime  = "✅" if regime == "trending" else "❌"
    c_funding = "✅" if funding_bias != "crowded_long" else "❌"
    c_book    = "✅" if book_healthy       else "❌"
    zone      = rsi_zone(rsi, RSI_BUY, RSI_SELL)

    trace = (
        f"🔍 RSI {rsi:.0f} ({zone}) {c_rsi}  MACD {macd_hist:+.2f} {c_macd}  "
        f"Trend {c_regime}  Fund {c_funding}  Book {c_book}"
    )

    return (
        f"{emoji} {signal}  —  BTC/USDT ${price:,.2f}\n"
        f"📈 RSI: {rsi:.1f}  |  MACD: {macd_hist:+.2f} {hist_arrow}  |  ADX: {adx:.1f}\n"
        f"{regime_emoji} Regime: {regime}  |  {funding_emoji} Funding: {funding_bias}\n"
        f"{trace}\n"
        f"💬 {reason}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)"
    )


def trade_card(action: str, price: float, size_usdt: float, reason: str, portfolio: float) -> str:
    pnl_pct  = (portfolio - START_USDT) / START_USDT * 100
    distance = GOAL_USDT - portfolio
    return (
        f"🚀 BUY executed  —  BTC/USDT\n"
        f"💵 Spent: ${size_usdt:.2f}  |  Price: ${price:,.2f}\n"
        f"💬 {reason}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"🎯 Goal: ${GOAL_USDT:.0f}  |  Remaining: ${distance:.2f}"
    )


def close_card(reason: str, exit_price: float, pnl_usdt: float, portfolio: float) -> str:
    win       = pnl_usdt >= 0
    emoji     = "✅" if win else "❌"
    label     = "TAKE PROFIT" if reason == "take_profit" else "ALERT THRESHOLD HIT"
    pnl_pct_total = (portfolio - START_USDT) / START_USDT * 100
    return (
        f"{emoji} {label}  —  BTC/USDT\n"
        f"💵 Exit price: ${exit_price:,.2f}\n"
        f"{'📈' if win else '📉'} Trade P&L: ${pnl_usdt:+.4f}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct_total:+.1f}%)\n"
        f"📅 Today's P&L: ${db.daily_pnl():+.4f}"
    )


def status_card(portfolio: float, position: dict | None) -> str:
    pnl_total = db.total_pnl()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    pos_line  = (
        f"📍 BTC/USDT  entry=${position['entry_price']:,.2f}  size=${position['size_usdt']:.2f}"
        if position else "📍 No open position"
    )
    return (
        f"📊 STATUS\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"📈 Total P&L: ${pnl_total:+.4f}\n"
        f"📅 Today's P&L: ${db.daily_pnl():+.4f}\n"
        f"{pos_line}\n"
        f"🎯 Goal: ${GOAL_USDT:.0f}"
    )


def daily_summary_card(portfolio: float) -> str:
    pnl_day   = db.daily_pnl()
    pnl_total = db.total_pnl()
    trades    = db.last_n_trades(n=5)
    today     = datetime.now(timezone.utc).date().isoformat()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    distance  = GOAL_USDT - portfolio
    day_emoji = "📈" if pnl_day >= 0 else "📉"
    return (
        f"☀️ DAILY SUMMARY  —  {today}\n"
        f"{day_emoji} Today: ${pnl_day:+.4f}\n"
        f"📊 Total P&L: ${pnl_total:+.4f}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"🎯 Goal: ${GOAL_USDT:.0f}  |  Distance: ${distance:.2f}\n"
        f"🔁 Trades today: {sum(1 for t in trades if t['ts'][:10] == today)}"
    )


def maybe_append_x_post(action: str, price: float, pnl_usdt: float, portfolio: float) -> None:
    """Appends a tweet-length draft to social/X.md if |P&L%| >= threshold."""
    if abs(pnl_usdt) / portfolio * 100 < SIG_THRESHOLD:
        return
    sign    = "+" if pnl_usdt >= 0 else ""
    pnl_pct = pnl_usdt / (portfolio - pnl_usdt) * 100
    today   = datetime.now(timezone.utc).date()
    post    = (
        f"\n**{today}**\n"
        f"> Claude bot {action} BTC/USDT @ ${price:,.0f}. "
        f"P&L: {sign}{pnl_pct:.1f}% (${sign}{pnl_usdt:.2f}). "
        f"Portfolio: ${portfolio:.2f}/${GOAL_USDT:.0f}. "
        f"#ClaudeTrader #AIExperiment\n"
    )
    try:
        with open(SOCIAL_FILE, "a") as f:
            f.write(post)
    except Exception as e:
        logger.warning("Could not write X post: %s", e)
