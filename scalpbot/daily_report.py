"""
Günlük rapor motoru:
  1. Dünkü sinyal logunu yükle
  2. Her sinyalin gerçekte ne olduğunu kontrol et (TP/SL/OPEN)
  3. Backtest çalıştır (tutarlılık ölçümü)
  4. Bugünkü aktif sinyalleri çek
  5. Telegram'dan kullanıcıya gönder

Kullanım:
  python -m scalpbot.daily_report              # tek seferlik
  python -m scalpbot.daily_report --setup-chat  # chat_id'yi keşfet ve .env'e yaz
"""
from __future__ import annotations

import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path


def _resolve_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _load_signals_json(report_dir: Path) -> list[dict]:
    path = report_dir / "signals.json"
    if path.exists():
        import json
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("signals", [])
        except Exception:
            pass
    return []


def _save_chat_id(root: Path, chat_id: int) -> None:
    env_path = root / ".env"
    lines = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    # Mevcut TELEGRAM_CHAT_ID satırını güncelle ya da ekle
    found = False
    for i, line in enumerate(lines):
        if line.startswith("TELEGRAM_CHAT_ID="):
            lines[i] = f"TELEGRAM_CHAT_ID={chat_id}"
            found = True
            break
    if not found:
        lines.append(f"TELEGRAM_CHAT_ID={chat_id}")

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(cfg=None, setup_chat: bool = False) -> None:
    root = _resolve_root()

    from .config import load_config
    from .binance_client import BinanceFutures
    from .backtest import run as bt_run
    from .signal_logger import load_signals_for_date, evaluate_past_signals
    from .telegram_notifier import TelegramNotifier

    if cfg is None:
        cfg = load_config()

    # Telegram token + chat_id
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token:
        print("HATA: TELEGRAM_BOT_TOKEN .env dosyasında tanımlı değil.")
        sys.exit(1)

    notifier = TelegramNotifier(token, chat_id or None)

    # Chat ID keşfet
    if setup_chat or not chat_id:
        print("Chat ID aranıyor... (bota /start gönderdiyseniz birkaç saniye bekleyin)")
        discovered = notifier.discover_chat_id()
        if discovered:
            notifier.chat_id = str(discovered)
            _save_chat_id(root, discovered)
            print(f"Chat ID bulundu ve kaydedildi: {discovered}")
        else:
            print(
                "Chat ID bulunamadı.\n"
                f"Lütfen Telegram'da @{_get_bot_username(token)} botuna /start gönderin,"
                " sonra bu komutu tekrar çalıştırın."
            )
            sys.exit(1)

    if not notifier.chat_id:
        print("HATA: TELEGRAM_CHAT_ID tanımlı değil. --setup-chat ile keşfet.")
        sys.exit(1)

    client = BinanceFutures(cfg.binance_fapi_base)
    report_dir = Path(cfg.run.get("report_dir", "data"))
    report_dir_abs = report_dir if report_dir.is_absolute() else root / report_dir

    # 1) Dünkü sinyalleri yükle
    yesterday_sigs = load_signals_for_date(report_dir_abs)
    print(f"Dünkü sinyal sayısı: {len(yesterday_sigs)}")

    # 2) Gerçek sonuçları hesapla (TP/SL/OPEN)
    signal_results = []
    if yesterday_sigs:
        print("Dünkü sinyallerin sonuçları kontrol ediliyor...")
        signal_results = evaluate_past_signals(yesterday_sigs, client)

    # 3) Backtest — en aktif sinyal coini için
    backtest_result = None
    if yesterday_sigs:
        # En yüksek güvenli coini backtest et
        best_sym = max(yesterday_sigs, key=lambda s: s["confidence"])["symbol"]
        print(f"Backtest çalışıyor: {best_sym}...")
        try:
            backtest_result = bt_run(best_sym, client, cfg, timeframe="15m", limit=500)
        except Exception as e:
            print(f"Backtest hatası: {e}")

    # 4) Bugünkü aktif sinyaller
    live_signals = _load_signals_json(report_dir_abs)

    # 5) Telegram raporu gönder
    date_str = datetime.now(timezone.utc).strftime("%d %B %Y")
    print("Telegram raporu gönderiliyor...")
    ok = notifier.send_daily_report(date_str, signal_results, backtest_result, live_signals)
    if ok:
        print("Rapor başarıyla gönderildi!")
    else:
        print("Telegram gönderimi başarısız. Token ve chat_id kontrolü yapın.")


def _get_bot_username(token: str) -> str:
    import requests
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        return r.json().get("result", {}).get("username", "bot")
    except Exception:
        return "bot"


def main() -> None:
    ap = argparse.ArgumentParser(description="Günlük sinyal raporu — Telegram bildirimi")
    ap.add_argument("--setup-chat", action="store_true",
                    help="Chat ID'yi keşfet ve .env'e kaydet")
    ap.add_argument("--config", default=None, help="config.yaml yolu")
    args = ap.parse_args()

    from .config import load_config
    cfg = load_config(args.config)
    run(cfg, setup_chat=args.setup_chat)


if __name__ == "__main__":
    main()
