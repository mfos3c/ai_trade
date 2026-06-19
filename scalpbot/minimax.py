"""MiniMax M3 API istemcisi — coin'in teknik gorunumunu AI ile degerlendirir."""
from __future__ import annotations

import json
from dataclasses import dataclass

import requests


@dataclass
class AIVerdict:
    direction: str          # LONG / SHORT / NEUTRAL
    confidence: float       # 0..100
    reason: str
    ok: bool = True         # cagri basariliysa True


SYSTEM_PROMPT = (
    "Sen kisa vadeli (15 dakikalik grafik) bir kripto scalp analistisin. "
    "Sana verilen Binance Futures coininin teknik indikator ozetini incele ve "
    "SADECE su JSON formatinda cevap ver: "
    '{\"direction\": \"LONG|SHORT|NEUTRAL\", \"confidence\": 0-100, \"reason\": \"kisa gerekce\"}. '
    "Trend zayifsa veya sinyaller celisiyorsa NEUTRAL de. Asla JSON disinda metin yazma."
)


class MiniMaxClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: int = 30):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.timeout = timeout

    def analyze(self, symbol: str, snapshot: dict, ta_direction: str) -> AIVerdict:
        if not self.api_key:
            return AIVerdict("NEUTRAL", 0.0, "AI devre disi (anahtar yok)", ok=False)

        user_msg = (
            f"Coin: {symbol} (15m)\n"
            f"Fiyat: {snapshot.get('price')}\n"
            f"EMA9/21/50: {snapshot.get('ema9')}/{snapshot.get('ema21')}/{snapshot.get('ema50')}\n"
            f"RSI: {snapshot.get('rsi')}\n"
            f"MACD/sinyal/hist: {snapshot.get('macd')}/{snapshot.get('macd_signal')}/{snapshot.get('macd_hist')}\n"
            f"Bollinger ust/orta/alt: {snapshot.get('bb_upper')}/{snapshot.get('bb_mid')}/{snapshot.get('bb_lower')}\n"
            f"Stochastic K/D: {snapshot.get('stoch_k')}/{snapshot.get('stoch_d')}\n"
            f"ADX/+DI/-DI: {snapshot.get('adx')}/{snapshot.get('plus_di')}/{snapshot.get('minus_di')}\n"
            f"Hacim/Hacim-SMA: {snapshot.get('volume')}/{snapshot.get('vol_sma')}\n"
            f"Teknik analiz on gorusu: {ta_direction}\n"
            "Bu coin icin yon karari ver."
        )

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.2,
            "max_tokens": 300,
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
        # JSON blogunu yakala (modelin fazladan metin yazma ihtimaline karsi)
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start : end + 1]
        try:
            obj = json.loads(text)
            direction = str(obj.get("direction", "NEUTRAL")).upper()
            if direction not in ("LONG", "SHORT", "NEUTRAL"):
                direction = "NEUTRAL"
            conf = float(obj.get("confidence", 0) or 0)
            return AIVerdict(direction, max(0.0, min(100.0, conf)), str(obj.get("reason", ""))[:200])
        except (ValueError, TypeError):
            return AIVerdict("NEUTRAL", 0.0, "AI cevabi cozumlenemedi", ok=False)
