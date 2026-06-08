import logging
from datetime import datetime, timezone
from pathlib import Path

import db

logger = logging.getLogger(__name__)

GOAL_USDT  = 1000.0
START_USDT = 50.0


def signal_card(is_dip: bool, drop_pct: float, reason: str, price: float, portfolio: float) -> str:
    emoji   = "🔴" if is_dip else "⚪"
    label   = "DIP DETECTED" if is_dip else "WATCHING"
    pnl_pct = (portfolio - START_USDT) / START_USDT * 100
    return (
        f"{emoji} AGG: {label}  —  BTC/USDT ${price:,.2f}\n"
        f"📉 4h move: {drop_pct*100:+.1f}%\n"
        f"💬 {reason}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)"
    )


def trade_card(price: float, size_usdt: float, reason: str, portfolio: float) -> str:
    pnl_pct  = (portfolio - START_USDT) / START_USDT * 100
    distance = GOAL_USDT - portfolio
    return (
        f"🚀 AGG BUY executed  —  BTC/USDT\n"
        f"💵 Spent: ${size_usdt:.2f}  |  Price: ${price:,.2f}\n"
        f"💬 {reason}\n"
        f"🎯 TP target: +20% (${price * 1.20:,.2f})\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"🏆 Goal: ${GOAL_USDT:.0f}  |  Remaining: ${distance:.2f}"
    )


def close_card(exit_price: float, pnl_usdt: float, portfolio: float) -> str:
    win       = pnl_usdt >= 0
    emoji     = "✅" if win else "❌"
    pnl_total = (portfolio - START_USDT) / START_USDT * 100
    return (
        f"{emoji} AGG TAKE PROFIT  —  BTC/USDT\n"
        f"💵 Exit: ${exit_price:,.2f}\n"
        f"{'📈' if win else '📉'} Trade P&L: ${pnl_usdt:+.4f}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_total:+.1f}%)\n"
        f"📅 Today's P&L: ${db.daily_pnl():+.4f}"
    )


def status_card(portfolio: float, position: dict | None, price: float, enabled: bool) -> str:
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    state     = "🟢 ENABLED" if enabled else "🔴 DISABLED"
    pos_lines = []
    if position:
        entry    = position["entry_price"]
        pnl_p    = (price - entry) / entry * 100
        pnl_u    = (price - entry) / entry * position["size_usdt"]
        tp_price = entry * 1.20
        pos_lines = [
            f"",
            f"📍 Holding BTC",
            f"  Entry: ${entry:,.2f} | Now: ${price:,.2f}",
            f"  P&L: {pnl_p:+.2f}% (${pnl_u:+.4f})",
            f"  TP at: ${tp_price:,.2f} (+20%)",
            f"  No stop-loss — holding through dips",
        ]
    else:
        pos_lines = ["", "📍 No position — watching for ≥5% dip"]

    lines = [
        f"📊 AGG BOT STATUS  {state}",
        f"BTC/USDT: ${price:,.2f}",
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}% vs start)",
    ] + pos_lines
    return "\n".join(lines)


def daily_summary_card(portfolio: float) -> str:
    pnl_day   = db.daily_pnl()
    pnl_total = db.total_pnl()
    today     = datetime.now(timezone.utc).date().isoformat()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    day_emoji = "📈" if pnl_day >= 0 else "📉"
    return (
        f"☀️ AGG DAILY  —  {today}\n"
        f"{day_emoji} Today: ${pnl_day:+.4f}\n"
        f"📊 Total P&L: ${pnl_total:+.4f}\n"
        f"💼 Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"🏆 Goal: ${GOAL_USDT:.0f}"
    )
