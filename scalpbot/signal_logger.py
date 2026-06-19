"""Günlük sinyal log yönetimi — her tarama sonrası kaydet, ertesi gün analiz et."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _yesterday() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _log_dir(report_dir: str | Path) -> Path:
    p = Path(report_dir) / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_daily_signals(decisions: list, report_dir: str | Path) -> Path:
    """
    Tarama sonrasındaki sinyalleri bugünün tarihiyle log dosyasına ekler.
    Aynı gün birden fazla tarama olursa en yüksek güvenli sinyal korunur.
    Dosya: data/logs/YYYY-MM-DD_signals.json
    """
    log_dir = _log_dir(report_dir)
    date = _today()
    path = log_dir / f"{date}_signals.json"

    # Mevcut logu oku (varsa)
    existing: dict[str, dict] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            existing = {s["symbol"]: s for s in loaded.get("signals", [])}
        except (ValueError, KeyError):
            pass

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # Sinyalleri işle: daha yüksek güven varsa güncelle
    for d in decisions:
        if d.direction == "NEUTRAL":
            continue
        sym = d.symbol
        new_entry = {
            "symbol": sym,
            "direction": d.direction,
            "confidence": d.confidence,
            "leverage": getattr(d, "leverage", 10),
            "price": d.price,
            "stop_loss": d.stop_loss,
            "take_profit": d.take_profit,
            "atr": d.atr,
            "ai_direction": (d.ai.direction if d.ai and d.ai.ok else None),
            "logged_at": now,
        }
        if sym not in existing or d.confidence > existing[sym]["confidence"]:
            existing[sym] = new_entry

    payload = {
        "date": date,
        "updated_at": now,
        "count": len(existing),
        "signals": list(existing.values()),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_signals_for_date(report_dir: str | Path, date: str | None = None) -> list[dict]:
    """
    Belirli tarihin (varsayılan: dün) sinyal logunu yükler.
    Bulunamazsa boş liste döner.
    """
    target_date = date or _yesterday()
    path = _log_dir(report_dir) / f"{target_date}_signals.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("signals", [])
    except (ValueError, OSError):
        return []


def evaluate_past_signals(
    signals: list[dict],
    client,
    timeframe: str = "15m",
    forward_candles: int = 50,
) -> list[dict]:
    """
    Dünkü sinyallerin gerçekte ne olduğunu kontrol eder.
    Her sinyal için forward_candles kadar mum çeker, SL veya TP'ye değip değmediğini analiz eder.
    """
    results = []
    for sig in signals:
        symbol = sig["symbol"]
        entry = sig["price"]
        sl = sig["stop_loss"]
        tp = sig["take_profit"]
        direction = sig["direction"]

        try:
            df = client.klines(symbol, timeframe, forward_candles + 10)
        except Exception:
            results.append({**sig, "outcome": "ERR", "pnl_pct": 0.0})
            continue

        outcome = "OPEN"
        exit_price = df["close"].iloc[-1]

        for _, row in df.iterrows():
            h = float(row["high"])
            lo = float(row["low"])
            if direction == "LONG":
                if lo <= sl:
                    outcome, exit_price = "SL", sl
                    break
                if h >= tp:
                    outcome, exit_price = "TP", tp
                    break
            else:  # SHORT
                if h >= sl:
                    outcome, exit_price = "SL", sl
                    break
                if lo <= tp:
                    outcome, exit_price = "TP", tp
                    break

        sign = 1.0 if direction == "LONG" else -1.0
        pnl_pct = sign * (exit_price - entry) / entry * 100 * sig.get("leverage", 10)
        results.append({
            **sig,
            "outcome": outcome,
            "exit_price": exit_price,
            "pnl_pct": round(pnl_pct, 2),
        })

    return results
