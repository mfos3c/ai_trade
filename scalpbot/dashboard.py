"""Kullanici dostu web dashboard — portfoy, sinyaller, pozisyonlar, coin arama."""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .config import ROOT, load_config
from .main import run_once

app = Flask(__name__, static_folder=None)
_CFG = load_config()
_WEB = Path(__file__).resolve().parent / "web"

# Tarama durumu kilidi (lock = token, running = gorsel durum)
_scan_lock = threading.Lock()
_scan_state: dict = {"running": False, "error": None}

# Coin analiz kilidi (ayni anda birden fazla analiz cagrisi)
_analyze_semaphore = threading.Semaphore(3)


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


# ── statik sayfa ─────────────────────────────────────────────────────────


@app.route("/")
def index():
    return send_from_directory(_WEB, "index.html")


# ── durum API'si ──────────────────────────────────────────────────────────


@app.route("/api/state")
def api_state():
    signals = _read_json(_data_path("signals.json"))
    state_name = Path(_CFG.run.get("state_file", "data/state.json")).name
    state = _read_json(_data_path(state_name))
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


# ── tarama API'si ─────────────────────────────────────────────────────────


def _do_scan(no_ai: bool) -> None:
    try:
        run_once(_CFG, no_ai=no_ai, verbose=False)
    except Exception as e:
        _scan_state["error"] = str(e)
    finally:
        _scan_state["running"] = False
        try:
            _scan_lock.release()
        except RuntimeError:
            pass  # zaten serbest


@app.route("/api/scan", methods=["POST"])
def api_scan():
    # Vercel serverless ortamında thread yerine sync çalıştır
    is_vercel = bool(os.environ.get("VERCEL_DATA_DIR") or os.environ.get("VERCEL"))

    acquired = _scan_lock.acquire(blocking=False)
    if not acquired:
        return jsonify({"ok": False, "error": "Tarama zaten suruyor"}), 409

    if _scan_state["running"]:
        _scan_lock.release()
        return jsonify({"ok": False, "error": "Tarama zaten suruyor"}), 409

    _scan_state["running"] = True
    _scan_state["error"] = None
    no_ai = not _CFG.ai_enabled

    if is_vercel:
        # Serverless: sync çalıştır, response hazır olunca döner
        _do_scan(no_ai)
        return jsonify({"ok": True, "sync": True})
    else:
        threading.Thread(target=_do_scan, args=(no_ai,), daemon=True).start()
        return jsonify({"ok": True})


# ── coin arama / MTF analiz ───────────────────────────────────────────────


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    """
    Tek coin icin 5 periyotlu MTF analiz, AI degerlendirmesi,
    kaldirac onerisi ve giris bolgesi.
    """
    body = request.get_json(force=True, silent=True) or {}
    symbol = str(body.get("symbol", "")).upper().strip().replace(" ", "")
    if not symbol:
        return jsonify({"ok": False, "error": "symbol gerekli"}), 400

    if not symbol.endswith("USDT"):
        symbol += "USDT"

    from .binance_client import BinanceFutures
    from .minimax import MiniMaxClient
    from .multi_timeframe import analyze_symbol

    client = BinanceFutures(_CFG.binance_fapi_base)

    # Sembol gecerliligi kontrolu
    if not client.validate_symbol(symbol):
        return jsonify({"ok": False, "error": f"{symbol} Binance Futures'ta bulunamadi"}), 404

    ai_client = None
    if _CFG.ai_enabled:
        ai_client = MiniMaxClient(
            _CFG.minimax_api_key, _CFG.minimax_base_url, _CFG.minimax_model
        )

    acquired = _analyze_semaphore.acquire(blocking=False)
    if not acquired:
        return jsonify({"ok": False, "error": "Cok fazla paralel analiz, lutfen bekleyin"}), 429

    try:
        result = analyze_symbol(symbol, client, ai_client, _CFG.strategy, _CFG.risk)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        _analyze_semaphore.release()

    tf_list = [
        {
            "tf": tf.tf,
            "label": tf.label,
            "direction": tf.direction,
            "confidence": tf.confidence,
            "score": round(tf.score, 3),
            "votes": tf.votes,
            "snapshot": {
                k: round(v, 8) if isinstance(v, float) else v
                for k, v in tf.snapshot.items()
                if k not in ("price",)  # price zaten ust seviyede var
            },
        }
        for tf in result.timeframes
    ]

    ai = result.ai_verdict
    return jsonify({
        "ok": True,
        "symbol": result.symbol,
        "direction": result.direction,
        "confluence": result.confluence,
        "leverage": result.leverage,
        "entry_low": result.entry_low,
        "entry_high": result.entry_high,
        "stop_loss": result.stop_loss,
        "take_profit": result.take_profit,
        "atr_pct": result.atr_pct,
        "rr_ratio": result.rr_ratio,
        "aligned_count": result.aligned_count,
        "total_tf": len(result.timeframes),
        "funding_rate": result.funding_rate,
        "timeframes": tf_list,
        "ai": {
            "direction": ai.direction,
            "confidence": ai.confidence,
            "reason": ai.reason,
            "risk_note": ai.risk_note,
            "ok": ai.ok,
        } if ai else None,
        "note": result.note,
    })


# ── basit backtest ────────────────────────────────────────────────────────


@app.route("/api/backtest", methods=["POST"])
def api_backtest():
    """
    Son N mum uzerinde strateji backtest'i calistirir.
    istek: {"symbol": "DOGEUSDT", "timeframe": "15m", "limit": 500}
    """
    body = request.get_json(force=True, silent=True) or {}
    symbol = str(body.get("symbol", "")).upper().strip()
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    timeframe = str(body.get("timeframe", "15m"))
    limit = min(int(body.get("limit", 500)), 1500)

    from .binance_client import BinanceFutures
    from .backtest import run as bt_run

    client = BinanceFutures(_CFG.binance_fapi_base)
    try:
        result = bt_run(symbol, client, _CFG, timeframe=timeframe, limit=limit)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, **result})


# ── uygulama giris noktasi ────────────────────────────────────────────────


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
