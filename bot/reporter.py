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


def trade_card(action: str, price: float, size_usdt: float, reason: str, portfolio: float) -> str:
    pnl_total = db.total_pnl()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    distance  = GOAL_USDT - portfolio
    return (
        f"🤖 {action}\n"
        f"Pair: BTC/USDT\n"
        f"Size: ${size_usdt:.2f}\n"
        f"Price: ${price:,.2f}\n"
        f"Reason: {reason}\n"
        f"Portfolio: ${portfolio:.2f} USDT ({pnl_pct:+.1f}%)\n"
        f"Target: ${GOAL_USDT:.0f} | Distance: ${distance:.2f}"
    )


def close_card(reason: str, exit_price: float, pnl_usdt: float, portfolio: float) -> str:
    emoji  = "✅" if pnl_usdt >= 0 else "❌"
    label  = reason.replace("_", " ").upper()
    pnl_pct_total = (portfolio - START_USDT) / START_USDT * 100
    return (
        f"{emoji} {label}\n"
        f"BTC/USDT exit: ${exit_price:,.2f}\n"
        f"Trade P&L: ${pnl_usdt:+.4f}\n"
        f"Portfolio: ${portfolio:.2f} ({pnl_pct_total:+.1f}%)\n"
        f"Daily P&L: ${db.daily_pnl():+.4f}"
    )


def status_card(portfolio: float, position: dict | None) -> str:
    pnl_total = db.total_pnl()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    pos_line  = (
        f"Position: BTC/USDT entry=${position['entry_price']:,.2f} size=${position['size_usdt']:.2f}"
        if position else "Position: none (holding USDT)"
    )
    return (
        f"📊 STATUS\n"
        f"Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"Total P&L: ${pnl_total:+.4f}\n"
        f"Daily P&L: ${db.daily_pnl():+.4f}\n"
        f"{pos_line}\n"
        f"Goal: ${GOAL_USDT:.0f}"
    )


def daily_summary_card(portfolio: float) -> str:
    pnl_day   = db.daily_pnl()
    pnl_total = db.total_pnl()
    trades    = db.last_n_trades(n=5)
    today     = datetime.now(timezone.utc).date().isoformat()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    distance  = GOAL_USDT - portfolio
    return (
        f"☀️ DAILY SUMMARY — {today}\n"
        f"Today P&L: ${pnl_day:+.4f}\n"
        f"Total P&L: ${pnl_total:+.4f}\n"
        f"Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"Target: ${GOAL_USDT:.0f} | Distance: ${distance:.2f}\n"
        f"Trades today: {sum(1 for t in trades if t['ts'][:10] == today)}"
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
