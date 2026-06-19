"""Scalp Bot giris noktasi — tara, sinyal uret, paper trading yap, raporla."""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from . import reporter
from .analyzer import combine, trade_levels
from .binance_client import BinanceFutures
from .config import ROOT, load_config
from .minimax import MiniMaxClient
from .paper_trader import PaperTrader
from .strategy import evaluate


def _resolve(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def run_once(cfg, *, no_ai: bool = False, verbose: bool = True) -> dict:
    market = cfg.market
    client = BinanceFutures(cfg.binance_fapi_base)

    ai_client = None
    if cfg.ai_enabled and not no_ai:
        ai_client = MiniMaxClient(cfg.minimax_api_key, cfg.minimax_base_url, cfg.minimax_model)

    trader = PaperTrader(_resolve(cfg.run.get("state_file", "data/state.json")), cfg.risk)

    # 1) $1 alti coinleri tara
    candidates = client.screen_symbols(
        max_price=float(market.get("max_price", 1.0)),
        min_quote_volume=float(market.get("min_quote_volume", 5_000_000)),
        quote_asset=market.get("quote_asset", "USDT"),
    )
    max_symbols = int(market.get("max_symbols", 40))
    candidates = candidates[:max_symbols]
    if verbose:
        print(f"Taranacak coin: {len(candidates)} (fiyat < ${market.get('max_price', 1.0)})")

    # 2) Acik pozisyonlari guncel fiyata gore degerlendir (SL/TP)
    price_map = {c["symbol"]: c["price"] for c in candidates}
    closed_now = trader.update_positions(price_map)

    # 3) Her coin icin TA + AI sinyali
    decisions = []
    for c in candidates:
        sym = c["symbol"]
        try:
            df = client.klines(sym, market.get("timeframe", "15m"),
                               int(market.get("klines_limit", 200)))
        except Exception as e:  # tek coin hatasi tarama durdurmaz
            if verbose:
                print(f"  ! {sym} kline hatasi: {e}")
            continue

        ta = evaluate(sym, df, cfg.strategy)
        if ta is None:
            continue

        ai_verdict = None
        # AI cagrisini sadece TA bir yon gosterdiyse yap (kota tasarrufu)
        if ai_client and ta.direction != "NEUTRAL":
            ai_verdict = ai_client.analyze(sym, ta.snapshot, ta.direction)

        d = combine(ta, ai_verdict, cfg.strategy)
        if d.direction in ("LONG", "SHORT") and d.atr > 0:
            d.stop_loss, d.take_profit = trade_levels(d.price, d.atr, d.direction, cfg.risk)
        decisions.append(d)

    # 4) Aktif sinyallerden yeni pozisyon ac (guvene gore sirali)
    opened = []
    for d in sorted(decisions, key=lambda x: x.confidence, reverse=True):
        if d.direction == "NEUTRAL":
            continue
        pos = trader.open_position(d, d.atr)
        if pos:
            opened.append(pos)

    trader.save()
    stats = trader.stats()

    if verbose:
        reporter.print_signals(decisions)
        reporter.print_trade_events(opened, closed_now)
        reporter.print_stats(stats)

    report_dir = _resolve(cfg.run.get("report_dir", "data"))
    reporter.write_markdown(report_dir, decisions, trader.state, stats)
    reporter.write_signals_json(report_dir, decisions, stats)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Binance Futures $1-alti scalp sinyal + paper trading botu")
    ap.add_argument("--config", default=None, help="config.yaml yolu")
    ap.add_argument("--loop", action="store_true", help="surekli calistir (interval_seconds)")
    ap.add_argument("--interval", type=int, default=None, help="loop tarama araligi (saniye)")
    ap.add_argument("--no-ai", action="store_true", help="MiniMax AI katmanini atla (sadece TA)")
    ap.add_argument("--close-all", action="store_true", help="tum acik pozisyonlari kapat ve cik")
    args = ap.parse_args()

    cfg = load_config(args.config)

    if args.close_all:
        trader = PaperTrader(_resolve(cfg.run.get("state_file", "data/state.json")), cfg.risk)
        client = BinanceFutures(cfg.binance_fapi_base)
        prices = {t["symbol"]: float(t["lastPrice"]) for t in client.ticker_24h()}
        closed = trader.force_close_all(prices)
        trader.save()
        reporter.print_trade_events([], closed)
        reporter.print_stats(trader.stats())
        return

    if not cfg.ai_enabled and not args.no_ai:
        print("ℹ️  MINIMAX_API_KEY tanimsiz — AI katmani atlaniyor, sadece TA ile calisilacak.")

    if args.loop:
        interval = args.interval or int(cfg.run.get("interval_seconds", 900))
        print(f"Loop modu: her {interval}s'de bir tarama. (Ctrl+C ile cik)")
        while True:
            try:
                run_once(cfg, no_ai=args.no_ai)
            except KeyboardInterrupt:
                print("\nDurduruldu.")
                break
            except Exception as e:
                print(f"Tarama hatasi: {e}")
            time.sleep(interval)
    else:
        run_once(cfg, no_ai=args.no_ai)


if __name__ == "__main__":
    main()
