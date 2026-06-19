"""Multi-timeframe (MTF) analiz motoru — coin arama icin 5 periyotta sinyal."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .binance_client import BinanceFutures
    from .minimax import MiniMaxClient, AIVerdict

from .strategy import TASignal, evaluate

# Her periyotun agirlik ve klines sayisi
TIMEFRAME_CONFIGS: list[dict] = [
    {"tf": "5m",  "weight": 0.15, "label": "5dk",  "klines": 120},
    {"tf": "15m", "weight": 0.30, "label": "15dk", "klines": 200},
    {"tf": "30m", "weight": 0.22, "label": "30dk", "klines": 150},
    {"tf": "1h",  "weight": 0.20, "label": "1sa",  "klines": 120},
    {"tf": "4h",  "weight": 0.13, "label": "4sa",  "klines": 100},
]


@dataclass
class TFAnalysis:
    tf: str
    label: str
    direction: str          # LONG / SHORT / NEUTRAL
    confidence: float       # 0..100
    score: float            # -1..+1
    price: float
    atr: float
    votes: dict = field(default_factory=dict)
    snapshot: dict = field(default_factory=dict)


@dataclass
class MTFResult:
    symbol: str
    direction: str          # LONG / SHORT / NEUTRAL (uzlasma)
    confluence: float       # 0..100 (MTF uyum skoru)
    timeframes: list[TFAnalysis] = field(default_factory=list)
    ai_verdict: AIVerdict | None = None
    leverage: int = 5       # onerilen kaldirac
    entry_low: float = 0.0  # giris bolgesi alt
    entry_high: float = 0.0 # giris bolgesi ust
    stop_loss: float = 0.0
    take_profit: float = 0.0
    atr_pct: float = 0.0    # ATR / fiyat (volatilite gostergesi)
    rr_ratio: float = 0.0   # risk/odul orani
    aligned_count: int = 0  # ayni yonu gosteren TF sayisi
    note: str = ""
    funding_rate: float = 0.0  # guncel funding rate (%)


def _recommend_leverage(confluence: float, atr_pct: float) -> int:
    """
    Guven skoru + volatiliteye gore kaldirac onerisi.
    Yuksek guven + dusuk volatilite = yuksek kaldirac.
    """
    if confluence >= 85:
        lev = 20
    elif confluence >= 75:
        lev = 15
    elif confluence >= 65:
        lev = 12
    elif confluence >= 60:
        lev = 10
    else:
        lev = 5  # 60 alti zaten NEUTRAL — sadece fallback

    # Volatilite cezasi: yuksek ATR → daha az kaldirac
    if atr_pct > 0.06:      # >6% ATR — cok volatil
        lev = max(3, lev // 3)
    elif atr_pct > 0.04:    # >4% ATR
        lev = max(5, lev // 2)
    elif atr_pct > 0.025:   # >2.5% ATR
        lev = max(7, int(lev * 0.75))

    return lev


def _trade_levels(
    price: float, atr: float, direction: str, risk_cfg: dict
) -> tuple[float, float, float, float]:
    """SL/TP ve giris bolgesi."""
    sl_mult = float(risk_cfg.get("atr_sl_mult", 1.5))
    rr = float(risk_cfg.get("risk_reward", 1.8))
    sl_dist = sl_mult * atr

    if direction == "LONG":
        stop_loss = price - sl_dist
        take_profit = price + sl_dist * rr
        entry_low = price - 0.25 * atr   # limit emir icin hafif altta
        entry_high = price + 0.10 * atr  # max giris siniri
    elif direction == "SHORT":
        stop_loss = price + sl_dist
        take_profit = price - sl_dist * rr
        entry_low = price - 0.10 * atr
        entry_high = price + 0.25 * atr
    else:
        stop_loss = take_profit = entry_low = entry_high = price

    return stop_loss, take_profit, entry_low, entry_high


def analyze_symbol(
    symbol: str,
    client: BinanceFutures,
    ai_client: MiniMaxClient | None,
    cfg_strategy: dict,
    cfg_risk: dict,
    requested_tfs: list[str] | None = None,
) -> MTFResult:
    """Sembol icin tam MTF analizi yapar ve MTFResult dondurur."""
    tf_configs = (
        TIMEFRAME_CONFIGS if requested_tfs is None
        else [t for t in TIMEFRAME_CONFIGS if t["tf"] in requested_tfs]
    )

    tf_results: list[TFAnalysis] = []
    weighted_score = 0.0
    total_weight = 0.0
    ref_price = 0.0
    ref_atr = 0.0

    for tfc in tf_configs:
        try:
            df = client.klines(symbol, tfc["tf"], tfc["klines"])
        except Exception:
            continue

        ta = evaluate(symbol, df, cfg_strategy)
        if ta is None:
            continue

        tf_results.append(TFAnalysis(
            tf=tfc["tf"],
            label=tfc["label"],
            direction=ta.direction,
            confidence=ta.confidence,
            score=ta.score,
            price=ta.price,
            atr=ta.atr,
            votes=ta.votes,
            snapshot=ta.snapshot,
        ))

        weighted_score += ta.score * tfc["weight"]
        total_weight += tfc["weight"]

        if tfc["tf"] == "15m":
            ref_price = ta.price
            ref_atr = ta.atr

    if not tf_results:
        return MTFResult(
            symbol=symbol, direction="NEUTRAL", confluence=0.0,
            note="Hicbir periyot icin veri alinamadi",
        )

    if ref_price == 0.0:
        ref_price = tf_results[0].price
        ref_atr = tf_results[0].atr

    combined = weighted_score / total_weight if total_weight > 0 else 0.0
    combined = max(-1.0, min(1.0, combined))

    if combined > 0.05:
        ta_direction = "LONG"
    elif combined < -0.05:
        ta_direction = "SHORT"
    else:
        ta_direction = "NEUTRAL"

    aligned = sum(1 for t in tf_results if t.direction == ta_direction)
    confluence = round(abs(combined) * 100, 1)

    # Funding rate (ek sinyal kirseyicisi)
    funding = 0.0
    try:
        funding = client.funding_rate(symbol)
    except Exception:
        pass

    # Funding rate cezasi: yuksek pozitif funding long'a, yuksek negatif short'a zarar verir
    funding_penalty = 0.0
    if ta_direction == "LONG" and funding > 0.001:   # >0.1% funding
        funding_penalty = min(10.0, funding * 5000)  # max -10 puan
    elif ta_direction == "SHORT" and funding < -0.001:
        funding_penalty = min(10.0, abs(funding) * 5000)
    confluence = max(0.0, confluence - funding_penalty)

    # AI analizi (MTF context ile)
    ai_verdict = None
    final_direction = ta_direction
    if ai_client and ta_direction != "NEUTRAL":
        ai_verdict = ai_client.analyze_mtf(symbol, tf_results, ta_direction)
        if ai_verdict and ai_verdict.ok:
            ai_sign = {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}[ai_verdict.direction]
            ai_weight = 0.35
            blended = (1 - ai_weight) * combined + ai_weight * ai_sign * (ai_verdict.confidence / 100)
            blended = max(-1.0, min(1.0, blended))
            confluence = round(abs(blended) * 100, 1)
            if blended > 0.05:
                final_direction = "LONG"
            elif blended < -0.05:
                final_direction = "SHORT"
            else:
                final_direction = "NEUTRAL"

    atr_pct = ref_atr / ref_price if ref_price > 0 else 0.0
    leverage = _recommend_leverage(confluence, atr_pct)
    stop_loss, take_profit, entry_low, entry_high = _trade_levels(
        ref_price, ref_atr, final_direction, cfg_risk
    )

    sl_dist = abs(ref_price - stop_loss)
    tp_dist = abs(ref_price - take_profit)
    rr_ratio = tp_dist / sl_dist if sl_dist > 0 else 0.0

    # Not: fund rate uyarisi
    note = ""
    if abs(funding) > 0.001:
        side = "pozitif" if funding > 0 else "negatif"
        note = f"Funding rate {side} ({funding*100:.3f}%) — {('SHORT' if funding > 0 else 'LONG')} icin ek maliyet"

    # 60 alti MTF uyumu: isleme girilmez, NEUTRAL dondur
    MTF_MIN_CONFLUENCE = 60
    if confluence < MTF_MIN_CONFLUENCE and final_direction != "NEUTRAL":
        not_ekle = f" | MTF confluence ({confluence:.0f}) < {MTF_MIN_CONFLUENCE} — isleme girme"
        note = (note + not_ekle).strip(" | ")
        final_direction = "NEUTRAL"

    return MTFResult(
        symbol=symbol,
        direction=final_direction,
        confluence=confluence,
        timeframes=tf_results,
        ai_verdict=ai_verdict,
        leverage=leverage,
        entry_low=entry_low,
        entry_high=entry_high,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr_pct=round(atr_pct * 100, 3),
        rr_ratio=round(rr_ratio, 2),
        aligned_count=aligned,
        note=note,
        funding_rate=round(funding * 100, 4),
    )
