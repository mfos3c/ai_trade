"""Basit walk-forward backtest motoru — strateji tutarliligini hizlica degerlendirir."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .binance_client import BinanceFutures
    from .config import Config

from . import indicators
from .strategy import evaluate
from .analyzer import trade_levels


def run(
    symbol: str,
    client: BinanceFutures,
    cfg: Config,
    timeframe: str = "15m",
    limit: int = 1000,
    window: int = 200,
) -> dict:
    """
    Son `limit` mumu indir, `window` mumlu pencerelerle sinyaller uret,
    her sinyal icin SL/TP simule et, istatistik dondur.

    Strateji tutarliligi ve güven skoru dogrulamasi icin kullanilir.
    Gerçek backteste karsi lookahead biasiyla: her bar kapanisinda sinyal,
    sonraki barda giris, SL/TP deyince cikis.
    """
    try:
        df = client.klines(symbol, timeframe, limit)
    except Exception as e:
        return {"error": str(e), "symbol": symbol, "timeframe": timeframe}

    if len(df) < window + 10:
        return {"error": "Yeterli veri yok", "symbol": symbol, "timeframe": timeframe}

    trades: list[dict] = []
    open_pos: dict | None = None

    margin_per_trade = 1.0  # her trade icin $1 marjin (normalize edilmis)
    leverage = float(cfg.risk.get("leverage", 10))
    fee_rate = float(cfg.risk.get("fee_rate", 0.0005))

    for i in range(window, len(df)):
        window_df = df.iloc[i - window: i + 1]
        try:
            s = indicators.compute_all(window_df)
        except Exception:
            continue

        price = s["price"]
        if price <= 0:
            continue

        # Acik pozisyon varsa SL/TP kontrol et
        if open_pos is not None:
            d = open_pos["direction"]
            sl = open_pos["stop_loss"]
            tp = open_pos["take_profit"]

            outcome = None
            exit_p = price
            if d == "LONG":
                if price <= sl:
                    outcome, exit_p = "SL", sl
                elif price >= tp:
                    outcome, exit_p = "TP", tp
            else:
                if price >= sl:
                    outcome, exit_p = "SL", sl
                elif price <= tp:
                    outcome, exit_p = "TP", tp

            if outcome is not None:
                sign = 1.0 if d == "LONG" else -1.0
                notional = margin_per_trade * leverage
                qty = notional / open_pos["entry"]
                gross = sign * (exit_p - open_pos["entry"]) * qty
                fee = exit_p * qty * fee_rate
                net = gross - fee
                pnl_pct = net / margin_per_trade * 100

                trades.append({
                    "direction": d,
                    "entry": open_pos["entry"],
                    "exit": exit_p,
                    "outcome": outcome,
                    "pnl": round(net, 6),
                    "pnl_pct": round(pnl_pct, 2),
                    "confidence": open_pos["confidence"],
                })
                open_pos = None

        # Sinyal uret — min_confidence filtresi de uygulanir
        if open_pos is None:
            min_conf = float(cfg.strategy.get("min_confidence", 55))
            ta = evaluate(symbol, window_df, cfg.strategy)
            if ta and ta.direction != "NEUTRAL" and ta.confidence >= min_conf:
                sl, tp = trade_levels(price, s["atr"], ta.direction, cfg.risk)
                open_pos = {
                    "direction": ta.direction,
                    "entry": price,
                    "stop_loss": sl,
                    "take_profit": tp,
                    "confidence": ta.confidence,
                }

    if not trades:
        return {
            "symbol": symbol, "timeframe": timeframe,
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "total_pnl_pct": 0.0,
            "profit_factor": 0.0, "max_drawdown_pct": 0.0,
            "candles_tested": limit, "avg_confidence": 0.0,
        }

    wins = [t for t in trades if t["pnl"] > 0]
    losses = [t for t in trades if t["pnl"] <= 0]
    total = len(trades)
    win_rate = len(wins) / total * 100 if total else 0.0
    total_pnl_pct = sum(t["pnl_pct"] for t in trades)

    gross_profit = sum(t["pnl"] for t in wins) if wins else 0.0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 1e-9
    profit_factor = round(gross_profit / gross_loss, 2)

    # Max drawdown (bakiye yerine pnl_pct kumulatif)
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        running += t["pnl_pct"]
        peak = max(peak, running)
        dd = peak - running
        max_dd = max(max_dd, dd)

    avg_conf = sum(t["confidence"] for t in trades) / total if total else 0.0

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "candles_tested": limit,
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "profit_factor": profit_factor,
        "max_drawdown_pct": round(max_dd, 1),
        "avg_confidence": round(avg_conf, 1),
        "trades_preview": trades[-10:],  # son 10 islem ozeti
    }
