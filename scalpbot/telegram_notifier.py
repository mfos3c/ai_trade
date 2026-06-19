"""Telegram bot bildirimleri — günlük rapor ve sinyal uyarıları."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests


class TelegramNotifier:
    BASE = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: str, chat_id: str | int | None = None):
        self.token = token
        self.chat_id = str(chat_id) if chat_id else None
        self._session = requests.Session()

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    def _call(self, method: str, **params: Any) -> dict:
        try:
            r = self._session.post(self._url(method), json=params, timeout=15)
            return r.json()
        except requests.RequestException as e:
            return {"ok": False, "error": str(e)}

    def get_me(self) -> dict:
        return self._call("getMe")

    def discover_chat_id(self) -> int | None:
        """
        getUpdates ile son mesajdaki chat_id'yi al.
        Kullanıcının bota en az bir kez /start (veya herhangi bir mesaj) göndermesi gerekir.
        """
        data = self._call("getUpdates", limit=20, timeout=5)
        for update in reversed(data.get("result", [])):
            msg = update.get("message") or update.get("channel_post")
            if msg and "chat" in msg:
                return int(msg["chat"]["id"])
        return None

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.chat_id:
            return False
        result = self._call(
            "sendMessage",
            chat_id=self.chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )
        return bool(result.get("ok"))

    # ── yüksek seviye gönderim fonksiyonları ─────────────────────────────

    def send_daily_report(
        self,
        date_str: str,
        signal_results: list[dict],
        backtest: dict | None,
        live_signals: list[dict],
    ) -> bool:
        """
        Dünkü sinyal sonuçlarını + backtest istatistiklerini + bugünkü sinyalleri gönderir.
        """
        lines = [f"<b>📊 Scalp Bot — Günlük Rapor</b>", f"<i>📅 {date_str}</i>", ""]

        # Dünkü sinyal sonuçları
        if signal_results:
            lines.append("<b>📈 Dünkü Sinyaller:</b>")
            for s in signal_results[:10]:
                outcome = s.get("outcome", "?")
                emoji = "✅" if outcome == "TP" else ("❌" if outcome == "SL" else "⏳")
                pnl = s.get("pnl_pct", 0)
                pnl_str = f"{pnl:+.1f}%" if pnl != 0 else "açık"
                lines.append(
                    f"  {emoji} <code>{s['symbol']}</code> {s['direction']} "
                    f"({s['confidence']:.0f}%) → {outcome} {pnl_str}"
                )
            lines.append("")
        else:
            lines.append("<i>Dün kayıtlı sinyal yok.</i>")
            lines.append("")

        # Backtest özeti
        if backtest and backtest.get("total_trades", 0) > 0:
            wr = backtest["win_rate"]
            pf = backtest["profit_factor"]
            dd = backtest["max_drawdown_pct"]
            wr_emoji = "🟢" if wr >= 55 else ("🟡" if wr >= 45 else "🔴")
            pf_emoji = "🟢" if pf >= 1.3 else ("🟡" if pf >= 1.0 else "🔴")
            lines.append("<b>🔬 Backtest (15m, son 500 mum):</b>")
            lines.append(f"  {wr_emoji} Win Rate: <b>{wr}%</b>  ({backtest['wins']}W/{backtest['losses']}L)")
            lines.append(f"  {pf_emoji} Profit Factor: <b>{pf}x</b>")
            lines.append(f"  📉 Max Drawdown: <b>{dd}%</b>")
            lines.append(f"  📋 İşlem sayısı: {backtest['total_trades']}")
            lines.append("")

        # Bugünkü aktif sinyaller
        active = [s for s in live_signals if s.get("direction") != "NEUTRAL"]
        if active:
            lines.append(f"<b>🎯 Aktif Sinyaller ({len(active)} adet):</b>")
            for s in active[:8]:
                dir_emoji = "🟢" if s["direction"] == "LONG" else "🔴"
                lev = s.get("leverage", "?")
                lines.append(
                    f"  {dir_emoji} <code>{s['symbol']}</code> {s['direction']} "
                    f"güven:{s['confidence']:.0f}% kald:{lev}x"
                )
        else:
            lines.append("<i>Şu an eşiği geçen sinyal yok.</i>")

        lines.append("")
        lines.append("<i>⚠️ Bu simülasyon sinyalidir, gerçek işlem değildir.</i>")

        return self.send_message("\n".join(lines))

    def send_scan_alert(self, signals: list[dict]) -> bool:
        """Yeni güçlü sinyal geldiğinde anlık uyarı."""
        strong = [s for s in signals if s.get("confidence", 0) >= 70 and s.get("direction") != "NEUTRAL"]
        if not strong:
            return False

        lines = [f"<b>⚡ Güçlü Sinyal Uyarısı ({len(strong)} adet)</b>", ""]
        for s in strong[:5]:
            dir_emoji = "🟢" if s["direction"] == "LONG" else "🔴"
            lev = s.get("leverage", "?")
            lines.append(
                f"{dir_emoji} <code>{s['symbol']}</code>\n"
                f"   Yön: <b>{s['direction']}</b>  Güven: <b>{s['confidence']:.0f}%</b>  Kald: <b>{lev}x</b>\n"
                f"   Giriş: <code>{s['price']:.8g}</code>  TP: <code>{s['take_profit']:.8g}</code>"
            )
        return self.send_message("\n".join(lines))
