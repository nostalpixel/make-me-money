import sqlite3
from datetime import date
from typing import Optional

DB_PATH = "trade.db"


def init(path: str = DB_PATH) -> None:
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          TEXT    NOT NULL,
                pair        TEXT    NOT NULL,
                side        TEXT    NOT NULL,
                size_usdt   REAL    NOT NULL,
                entry_price REAL    NOT NULL,
                exit_price  REAL,
                exit_reason TEXT,
                pnl_usdt    REAL,
                status      TEXT    NOT NULL DEFAULT 'open'
            );
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date     TEXT PRIMARY KEY,
                pnl_usdt REAL NOT NULL DEFAULT 0
            );
        """)


def open_trade(ts: str, pair: str, side: str, size_usdt: float, entry_price: float, path: str = DB_PATH) -> int:
    with sqlite3.connect(path) as con:
        cur = con.execute(
            "INSERT INTO trades (ts, pair, side, size_usdt, entry_price) VALUES (?,?,?,?,?)",
            (ts, pair, side, size_usdt, entry_price),
        )
        return cur.lastrowid


def close_trade(trade_id: int, exit_price: float, exit_reason: str, pnl_usdt: float, path: str = DB_PATH) -> None:
    today = date.today().isoformat()
    with sqlite3.connect(path) as con:
        con.execute(
            "UPDATE trades SET exit_price=?, exit_reason=?, pnl_usdt=?, status='closed' WHERE id=?",
            (exit_price, exit_reason, pnl_usdt, trade_id),
        )
        con.execute(
            "INSERT INTO daily_pnl (date, pnl_usdt) VALUES (?,?) ON CONFLICT(date) DO UPDATE SET pnl_usdt=pnl_usdt+excluded.pnl_usdt",
            (today, pnl_usdt),
        )


def get_open_position(path: str = DB_PATH) -> Optional[dict]:
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM trades WHERE status='open' LIMIT 1").fetchone()
        return dict(row) if row else None


def last_n_trades(n: int = 5, path: str = DB_PATH) -> list[dict]:
    with sqlite3.connect(path) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM trades ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]


def daily_pnl(path: str = DB_PATH) -> float:
    today = date.today().isoformat()
    with sqlite3.connect(path) as con:
        row = con.execute("SELECT pnl_usdt FROM daily_pnl WHERE date=?", (today,)).fetchone()
        return row[0] if row else 0.0


def total_pnl(path: str = DB_PATH) -> float:
    with sqlite3.connect(path) as con:
        row = con.execute("SELECT COALESCE(SUM(pnl_usdt),0) FROM trades WHERE status='closed'").fetchone()
        return row[0]
