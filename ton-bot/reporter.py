import logging
from datetime import datetime, timezone

import db

logger = logging.getLogger(__name__)

START_USDT = 20.0   # approximate starting value in USDT


def trade_card(action: str, price: float, size_usdt: float, reason: str, portfolio: float) -> str:
    pnl_pct  = (portfolio - START_USDT) / START_USDT * 100
    return (
        f"🪙 TON {action}\n"
        f"Pair: TON/USDT (DeDust)\n"
        f"Size: ${size_usdt:.2f}\n"
        f"Price: ${price:.4f}\n"
        f"Reason: {reason}\n"
        f"Portfolio: ${portfolio:.2f} USDT ({pnl_pct:+.1f}%)"
    )


def close_card(reason: str, exit_price: float, pnl_usdt: float, portfolio: float) -> str:
    emoji    = "✅" if pnl_usdt >= 0 else "❌"
    label    = reason.replace("_", " ").upper()
    pnl_total = db.total_pnl()
    return (
        f"{emoji} TON {label}\n"
        f"TON/USDT exit: ${exit_price:.4f}\n"
        f"Trade P&L: ${pnl_usdt:+.4f}\n"
        f"Portfolio: ${portfolio:.2f}\n"
        f"Total P&L: ${pnl_total:+.4f}"
    )


def status_card(ton_bal: float, usdt_bal: float, ton_price: float, portfolio: float) -> str:
    pnl_total = db.total_pnl()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    position  = db.get_open_position()
    pos_line  = (
        f"Position: TON entry=${position['entry_price']:.4f} size=${position['size_usdt']:.2f}"
        if position else "Position: holding TON (no active trade)"
    )
    return (
        f"📊 TON BOT STATUS\n"
        f"TON: {ton_bal:.4f} (${ton_bal * ton_price:.2f})\n"
        f"USDT: {usdt_bal:.4f}\n"
        f"Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"TON price: ${ton_price:.4f}\n"
        f"Total P&L: ${pnl_total:+.4f}\n"
        f"{pos_line}"
    )


def daily_summary_card(portfolio: float, ton_price: float) -> str:
    pnl_day   = db.daily_pnl()
    pnl_total = db.total_pnl()
    today     = datetime.now(timezone.utc).date().isoformat()
    pnl_pct   = (portfolio - START_USDT) / START_USDT * 100
    return (
        f"☀️ TON BOT DAILY — {today}\n"
        f"Today P&L: ${pnl_day:+.4f}\n"
        f"Total P&L: ${pnl_total:+.4f}\n"
        f"Portfolio: ${portfolio:.2f} ({pnl_pct:+.1f}%)\n"
        f"TON price: ${ton_price:.4f}"
    )
