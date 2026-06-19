"""MiniMax M3 API istemcisi — tek TF veya MTF kripto scalp analizi."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .multi_timeframe import TFAnalysis


@dataclass
class AIVerdict:
    direction: str          # LONG / SHORT / NEUTRAL
    confidence: float       # 0..100
    reason: str
    risk_note: str = ""
    ok: bool = True         # cagri basariliysa True


_SINGLE_TF_SYSTEM = (
    "Sen uzman bir kripto futures scalp analistisin. "
    "Verilen zaman dilimindeki teknik indikator ozetini incele ve "
    "YALNIZCA su JSON formatinda cevap ver (asla JSON disinda metin yazma): "
    '{"direction":"LONG|SHORT|NEUTRAL","confidence":0-100,'
    '"reason":"kisa gerekce (maks 120 karakter)",'
    '"risk_note":"onemli risk varsa belirt, yoksa bos birak"}. '
    "Sinyaller celisiyorsa veya trend net degilse NEUTRAL sec."
)

_MTF_SYSTEM = (
    "Sen profesyonel bir kripto futures multi-timeframe scalp analistisin. "
    "Kisa vadeli (birkaç saat icinde kapanacak) islem odakli dusun. "
    "YALNIZCA su JSON formatinda cevap ver: "
    '{"direction":"LONG|SHORT|NEUTRAL","confidence":0-100,'
    '"reason":"tum zaman dilimlerini ozet gerekce (maks 150 karakter)",'
    '"risk_note":"funding, likidite, spread riski vb. (yoksa bos birak)"}. '
    "4h/1h trend 15m/5m girisine karsi ise NEUTRAL sec. JSON disinda metin yazma."
)


class MiniMaxClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    # ── tek zaman dilimi analizi (tarama icin) ────────────────────────────

    def analyze(self, symbol: str, snapshot: dict, ta_direction: str, timeframe: str = "15m") -> AIVerdict:
        if not self.api_key:
            return AIVerdict("NEUTRAL", 0.0, "AI devre disi (anahtar yok)", ok=False)

        user_msg = (
            f"Coin: {symbol} | Zaman dilimi: {timeframe}\n"
            f"Fiyat: {snapshot.get('price'):.8g}\n"
            f"EMA9/21/50: {snapshot.get('ema9'):.8g}/{snapshot.get('ema21'):.8g}/{snapshot.get('ema50'):.8g}\n"
            f"RSI: {snapshot.get('rsi'):.1f}  |  Uyusmazlik: {snapshot.get('rsi_divergence',0):+.0f}\n"
            f"MACD/sig/hist: {snapshot.get('macd'):.6g}/{snapshot.get('macd_signal'):.6g}/{snapshot.get('macd_hist'):.6g}\n"
            f"Bollinger ust/mid/alt: {snapshot.get('bb_upper'):.8g}/{snapshot.get('bb_mid'):.8g}/{snapshot.get('bb_lower'):.8g}\n"
            f"Stochastic K/D: {snapshot.get('stoch_k'):.1f}/{snapshot.get('stoch_d'):.1f}\n"
            f"ADX/+DI/-DI: {snapshot.get('adx'):.1f}/{snapshot.get('plus_di'):.1f}/{snapshot.get('minus_di'):.1f}\n"
            f"Supertrend: {'YUKARI (bull)' if snapshot.get('supertrend_bull') else 'ASAGI (bear)'}\n"
            f"VWAP: {snapshot.get('vwap'):.8g}  |  Fiyat VWAP {'ustunde' if snapshot.get('price',0) > snapshot.get('vwap',0) else 'altinda'}\n"
            f"Hacim/Hacim-SMA: {snapshot.get('volume'):.0f}/{snapshot.get('vol_sma'):.0f}\n"
            f"TA on gorusu: {ta_direction}\n"
            "Son karar ver."
        )

        return self._call(_SINGLE_TF_SYSTEM, user_msg)

    # ── multi-timeframe analizi (coin arama icin) ─────────────────────────

    def analyze_mtf(
        self,
        symbol: str,
        tf_results: list[TFAnalysis],
        ta_direction: str,
    ) -> AIVerdict:
        if not self.api_key:
            return AIVerdict("NEUTRAL", 0.0, "AI devre disi", ok=False)

        lines = []
        for tf in tf_results:
            s = tf.snapshot
            st = "+" if s.get("supertrend_bull") else "-"
            vwap_pos = "U" if s.get("price", 0) > s.get("vwap", 0) else "A"
            div = s.get("rsi_divergence", 0)
            div_str = "(BullDiv)" if div > 0 else ("(BearDiv)" if div < 0 else "")
            lines.append(
                f"[{tf.label:4s}] {tf.direction:<7} Guven:{tf.confidence:4.0f}% | "
                f"RSI:{s.get('rsi',0):4.1f}{div_str}  ADX:{s.get('adx',0):4.1f}  "
                f"MACD:{'pos' if s.get('macd',0) > s.get('macd_signal',0) else 'neg'}  "
                f"ST:{st}  VWAP:{vwap_pos}"
            )

        user_msg = (
            f"Coin: {symbol}\n"
            "Zaman dilimi analizi:\n" +
            "\n".join(lines) +
            f"\nTA ongorusu: {ta_direction}\n"
            "Tum periyotlari degerlendirip nihai karar ver."
        )

        return self._call(_MTF_SYSTEM, user_msg)

    # ── ortak HTTP cagri + parse ──────────────────────────────────────────

    def _call(self, system: str, user_msg: str) -> AIVerdict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.15,
            "max_tokens": 350,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            r = requests.post(self.base_url, headers=headers, json=payload, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            return self._parse(content)
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            return AIVerdict("NEUTRAL", 0.0, f"AI hata: {e}", ok=False)

    @staticmethod
    def _parse(content: str) -> AIVerdict:
        text = content.strip()
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start: end + 1]
        try:
            obj = json.loads(text)
            direction = str(obj.get("direction", "NEUTRAL")).upper()
            if direction not in ("LONG", "SHORT", "NEUTRAL"):
                direction = "NEUTRAL"
            conf = float(obj.get("confidence", 0) or 0)
            reason = str(obj.get("reason", ""))[:200]
            risk_note = str(obj.get("risk_note", ""))[:150]
            return AIVerdict(direction, max(0.0, min(100.0, conf)), reason, risk_note)
        except (ValueError, TypeError):
            return AIVerdict("NEUTRAL", 0.0, "AI cevabi cozumlenemedi", ok=False)
