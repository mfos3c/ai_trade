"""Kullanici dostu web dashboard — portfoy, sinyaller, pozisyonlar (Flask)."""
from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from .config import ROOT, load_config
from .main import run_once

app = Flask(__name__, static_folder=None)
_CFG = load_config()
_WEB = Path(__file__).resolve().parent / "web"

# tarama durumu (ayni anda tek tarama)
_scan_lock = threading.Lock()
_scan_state = {"running": False, "error": None}


def _data_path(name: str) -> Path:
    report_dir = _CFG.run.get("report_dir", "data")
    p = Path(report_dir)
    base = p if p.is_absolute() else ROOT / p
    return base / name


def _read_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


@app.route("/")
def index():
    return send_from_directory(_WEB, "index.html")


@app.route("/api/state")
def api_state():
    signals = _read_json(_data_path("signals.json"))
    state = _read_json(_data_path(Path(_CFG.run.get("state_file", "data/state.json")).name))
    return jsonify({
        "ai_enabled": _CFG.ai_enabled,
        "scan": _scan_state,
        "signals": signals,
        "open_positions": state.get("open_positions", []),
        "closed_trades": state.get("closed_trades", []),
        "balance": state.get("balance"),
        "start_balance": state.get("start_balance"),
        "state_updated_at": state.get("updated_at"),
    })


def _do_scan(no_ai: bool):
    try:
        run_once(_CFG, no_ai=no_ai, verbose=False)
    except Exception as e:  # noqa: BLE001
        _scan_state["error"] = str(e)
    finally:
        _scan_state["running"] = False


@app.route("/api/scan", methods=["POST"])
def api_scan():
    if not _scan_lock.acquire(blocking=False):
        return jsonify({"ok": False, "error": "Tarama zaten suruyor"}), 409
    try:
        if _scan_state["running"]:
            return jsonify({"ok": False, "error": "Tarama zaten suruyor"}), 409
        _scan_state["running"] = True
        _scan_state["error"] = None
        no_ai = not _CFG.ai_enabled
        threading.Thread(target=lambda: (_do_scan(no_ai), _scan_lock.release()), daemon=True).start()
        return jsonify({"ok": True})
    except Exception:
        _scan_lock.release()
        raise


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Scalp Bot dashboard")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    print(f"Dashboard: http://{args.host}:{args.port}  (Ctrl+C ile cik)")
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
