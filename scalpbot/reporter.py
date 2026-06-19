"""Konsol ve markdown/CSV raporlama."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def write_signals_json(report_dir: str | Path, decisions: list, stats: dict) -> Path:
    """Dashboard'un okuyabilmesi icin sinyalleri ve portfoyu JSON olarak yazar."""
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "signals.json"

    rows = []
    for d in sorted(decisions, key=lambda x: x.confidence, reverse=True):
        rows.append({
            "symbol": d.symbol,
            "direction": d.direction,
            "confidence": d.confidence,
            "leverage": getattr(d, "leverage", 10),
            "price": d.price,
            "atr": d.atr,
            "stop_loss": d.stop_loss,
            "take_profit": d.take_profit,
            "ai_direction": (d.ai.direction if d.ai and d.ai.ok else None),
            "ai_reason": (d.ai.reason if d.ai and d.ai.ok else None),
            "note": d.note,
            "votes": d.votes,
        })

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scanned": len(decisions),
        "active": sum(1 for d in decisions if d.direction != "NEUTRAL"),
        "stats": stats,
        "signals": rows,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def print_signals(decisions: list, top: int = 20) -> None:
    actionable = [d for d in decisions if d.direction != "NEUTRAL"]
    actionable.sort(key=lambda d: d.confidence, reverse=True)
    print(f"\n=== SINYALLER ({len(actionable)} aktif / {len(decisions)} taranan) — {_ts()} ===")
    if not actionable:
        print("  (esigi gecen sinyal yok)")
        return
    print(f"{'COIN':<14}{'YON':<7}{'GUVEN':<8}{'GIRIS':<12}{'STOP':<12}{'HEDEF':<12}{'AI':<7}NOT")
    for d in actionable[:top]:
        ai = d.ai.direction[:4] if (d.ai and d.ai.ok) else "-"
        print(
            f"{d.symbol:<14}{d.direction:<7}{d.confidence:<8.1f}"
            f"{d.price:<12.6f}{d.stop_loss:<12.6f}{d.take_profit:<12.6f}"
            f"{ai:<7}{(d.ai.reason if d.ai and d.ai.ok else d.note)[:30]}"
        )


def print_trade_events(opened: list, closed: list) -> None:
    for p in opened:
        print(f"  [AC]  {p.direction} {p.symbol} @ {p.entry:.6f} "
              f"SL={p.stop_loss:.6f} TP={p.take_profit:.6f} (marjin ${p.margin:.2f})")
    for t in closed:
        sign = "+" if t.pnl >= 0 else ""
        print(f"  [KAPAT] {t.direction} {t.symbol} @ {t.exit:.6f} "
              f"[{t.outcome}] PnL={sign}{t.pnl:.4f} USDT ({sign}{t.pnl_pct:.1f}%)")


def print_stats(stats: dict) -> None:
    print("\n=== PORTFOY ===")
    print(f"  Bakiye        : ${stats['balance']:.4f}  (baslangic ${stats['start_balance']:.2f})")
    print(f"  ROI           : {stats['roi_pct']:+.2f}%")
    print(f"  Toplam islem  : {stats['total_trades']}  "
          f"(W:{stats['wins']} / L:{stats['losses']}  win-rate {stats['win_rate']}%)")
    print(f"  Toplam PnL    : {stats['total_pnl']:+.4f} USDT")
    print(f"  Acik pozisyon : {stats['open_positions']}")


def write_markdown(report_dir: str | Path, decisions: list, state, stats: dict) -> Path:
    report_dir = Path(report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "report.md"

    actionable = sorted(
        [d for d in decisions if d.direction != "NEUTRAL"],
        key=lambda d: d.confidence, reverse=True,
    )
    lines = [
        "# Scalp Bot Raporu",
        f"_Guncelleme: {_ts()}_",
        "",
        "## Portfoy ($10 paper)",
        f"- **Bakiye:** ${stats['balance']:.4f} (baslangic ${stats['start_balance']:.2f}, ROI {stats['roi_pct']:+.2f}%)",
        f"- **Islem:** {stats['total_trades']} (W:{stats['wins']} / L:{stats['losses']}, win-rate {stats['win_rate']}%)",
        f"- **Toplam PnL:** {stats['total_pnl']:+.4f} USDT",
        f"- **Acik pozisyon:** {stats['open_positions']}",
        "",
        "## Aktif Sinyaller",
        "",
        "| Coin | Yon | Guven | Giris | Stop | Hedef | AI | Not |",
        "|------|-----|-------|-------|------|-------|----|----|",
    ]
    for d in actionable:
        ai = d.ai.direction if (d.ai and d.ai.ok) else "-"
        note = (d.ai.reason if d.ai and d.ai.ok else d.note).replace("|", "/")[:60]
        lines.append(f"| {d.symbol} | {d.direction} | {d.confidence:.1f} | {d.price:.6f} | "
                     f"{d.stop_loss:.6f} | {d.take_profit:.6f} | {ai} | {note} |")

    if state.open_positions:
        lines += ["", "## Acik Pozisyonlar", "",
                  "| Coin | Yon | Giris | SL | TP | Marjin |",
                  "|------|-----|-------|----|----|--------|"]
        for p in state.open_positions:
            lines.append(f"| {p.symbol} | {p.direction} | {p.entry:.6f} | "
                         f"{p.stop_loss:.6f} | {p.take_profit:.6f} | ${p.margin:.2f} |")

    if state.closed_trades:
        lines += ["", "## Son Kapanan Islemler", "",
                  "| Coin | Yon | Giris | Cikis | Sonuc | PnL | % |",
                  "|------|-----|-------|-------|-------|-----|---|"]
        for t in state.closed_trades[-15:][::-1]:
            lines.append(f"| {t.symbol} | {t.direction} | {t.entry:.6f} | {t.exit:.6f} | "
                         f"{t.outcome} | {t.pnl:+.4f} | {t.pnl_pct:+.1f} |")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_trades_csv(report_dir / "trades.csv", state.closed_trades)
    return path


def _write_trades_csv(path: Path, trades: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "direction", "entry", "exit", "qty",
                    "pnl", "pnl_pct", "outcome", "opened_at", "closed_at"])
        for t in trades:
            w.writerow([t.symbol, t.direction, t.entry, t.exit, t.qty,
                        t.pnl, t.pnl_pct, t.outcome, t.opened_at, t.closed_at])
