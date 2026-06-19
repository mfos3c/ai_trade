"""Indikatorleri agirlikli oya cevirip LONG/SHORT/NEUTRAL teknik sinyali uretir."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators


@dataclass
class TASignal:
    symbol: str
    direction: str          # LONG / SHORT / NEUTRAL
    score: float            # -1..+1 (negatif=short)
    confidence: float       # 0..100
    price: float
    atr: float
    votes: dict = field(default_factory=dict)   # indikator -> -1..+1
    snapshot: dict = field(default_factory=dict)  # ham indikator degerleri


def _ema_vote(s: dict) -> float:
    if s["ema9"] > s["ema21"] > s["ema50"]:
        return 1.0
    if s["ema9"] < s["ema21"] < s["ema50"]:
        return -1.0
    if s["ema9"] > s["ema21"]:
        return 0.5
    if s["ema9"] < s["ema21"]:
        return -0.5
    return 0.0


def _rsi_vote(s: dict, ob: float, os_: float) -> float:
    r = s["rsi"]
    if r <= os_:
        return 1.0          # asiri satim -> long firsati
    if r >= ob:
        return -1.0         # asiri alim -> short firsati
    # trend onayi: 50 ustu long egilimi
    return (r - 50) / 20.0  # ~ -1..+1 arasi yumusak


def _macd_vote(s: dict) -> float:
    rising = s["macd_hist"] > s["macd_hist_prev"]
    if s["macd"] > s["macd_signal"]:
        return 1.0 if rising else 0.5
    if s["macd"] < s["macd_signal"]:
        return -1.0 if not rising else -0.5
    return 0.0


def _bollinger_vote(s: dict) -> float:
    rng = s["bb_upper"] - s["bb_lower"]
    if rng <= 0:
        return 0.0
    pos = (s["price"] - s["bb_lower"]) / rng  # 0=alt band, 1=ust band
    if pos <= 0.1:
        return 1.0
    if pos >= 0.9:
        return -1.0
    return (0.5 - pos) * 2.0   # merkeze gore yumusak egilim


def _stoch_vote(s: dict) -> float:
    k, d = s["stoch_k"], s["stoch_d"]
    if k < 20 and k > d:
        return 1.0
    if k > 80 and k < d:
        return -1.0
    if k > d:
        return 0.3
    if k < d:
        return -0.3
    return 0.0


def _adx_vote(s: dict, adx_min: float) -> float:
    if s["adx"] < adx_min:
        return 0.0          # trend zayif -> yon teyidi yok
    return 1.0 if s["plus_di"] > s["minus_di"] else -1.0


def _volume_vote(s: dict) -> float:
    if s["vol_sma"] <= 0:
        return 0.0
    ratio = s["volume"] / s["vol_sma"]
    # yuksek hacim = teyit; yonu fiyat hareketinden cikar
    direction = 1.0 if s["price"] >= s["ema21"] else -1.0
    if ratio >= 1.5:
        return direction
    if ratio >= 1.0:
        return direction * 0.5
    return 0.0


def evaluate(symbol: str, df: pd.DataFrame, cfg_strategy: dict) -> TASignal | None:
    if df is None or len(df) < 60:
        return None

    s = indicators.compute_all(df)
    w = cfg_strategy["weights"]
    ob = cfg_strategy.get("rsi_overbought", 70)
    os_ = cfg_strategy.get("rsi_oversold", 30)
    adx_min = cfg_strategy.get("adx_min", 20)

    votes = {
        "ema_trend": _ema_vote(s),
        "rsi": _rsi_vote(s, ob, os_),
        "macd": _macd_vote(s),
        "bollinger": _bollinger_vote(s),
        "stochastic": _stoch_vote(s),
        "adx": _adx_vote(s, adx_min),
        "volume": _volume_vote(s),
    }

    score = sum(votes[k] * w.get(k, 0.0) for k in votes)
    total_w = sum(w.get(k, 0.0) for k in votes) or 1.0
    score = max(-1.0, min(1.0, score / total_w))
    confidence = round(abs(score) * 100, 1)

    if score > 0:
        direction = "LONG"
    elif score < 0:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    return TASignal(
        symbol=symbol,
        direction=direction,
        score=round(score, 4),
        confidence=confidence,
        price=s["price"],
        atr=s["atr"],
        votes={k: round(v, 2) for k, v in votes.items()},
        snapshot=s,
    )
