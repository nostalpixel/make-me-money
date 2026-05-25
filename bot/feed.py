"""
Read-only HTTP feed exposing trading metrics as JSON.
Bind: 0.0.0.0:FEED_PORT (default 8001)
Auth: optional Bearer token via FEED_TOKEN env var.
"""
import json
import logging
import os
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import db

logger = logging.getLogger(__name__)
_PORT  = int(os.environ.get("FEED_PORT", "8001"))
_TOKEN = os.environ.get("FEED_TOKEN", "")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress per-request stdout noise

    def _send_json(self, status: int, body: dict) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=30")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if not _TOKEN:
            return True
        return self.headers.get("Authorization", "") == f"Bearer {_TOKEN}"

    def do_GET(self) -> None:
        if self.path.rstrip("/") != "/feed":
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="feed"')
            self.end_headers()
            return
        try:
            self._send_json(200, _build_payload())
        except Exception as exc:
            logger.exception("Feed error: %s", exc)
            self._send_json(500, {"error": str(exc)})


def _build_payload() -> dict:
    today   = date.today().isoformat()
    trades  = db.last_n_trades(n=10)
    pos     = db.get_open_position()
    daily   = db.daily_pnl()
    total   = db.total_pnl()
    today_t = [t for t in trades if t["ts"][:10] == today]
    return {
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "date":              today,
        "daily_pnl":         round(daily, 4),
        "total_pnl":         round(total, 4),
        "trade_count_today": len(today_t),
        "open_position": {
            "pair":        pos["pair"],
            "side":        pos["side"],
            "entry_price": pos["entry_price"],
            "size_usdt":   pos["size_usdt"],
            "since":       pos["ts"],
        } if pos else None,
        "recent_trades": [
            {
                "ts":          t["ts"],
                "pair":        t["pair"],
                "side":        t["side"],
                "entry_price": t["entry_price"],
                "exit_price":  t["exit_price"],
                "pnl_usdt":    round(t["pnl_usdt"], 4) if t["pnl_usdt"] is not None else None,
                "exit_reason": t["exit_reason"],
                "status":      t["status"],
            }
            for t in trades[:5]
        ],
    }


def start() -> Thread:
    server = HTTPServer(("0.0.0.0", _PORT), _Handler)
    t = Thread(target=server.serve_forever, daemon=True, name="feed-server")
    t.start()
    logger.info("Feed server listening on :%d", _PORT)
    return t
