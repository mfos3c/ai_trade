"""TA sinyali + MiniMax AI gorusunu birlestirip nihai LONG/SHORT karari uretir."""
from __future__ import annotations

from dataclasses import dataclass, field

from .minimax import AIVerdict
from .strategy import TASignal

_DIR_SIGN = {"LONG": 1.0, "SHORT": -1.0, "NEUTRAL": 0.0}


@dataclass
class Decision:
    symbol: str
    direction: str          # LONG / SHORT / NEUTRAL
    confidence: float       # 0..100
    price: float
    atr: float
    ta: TASignal
    ai: AIVerdict | None = None
    note: str = ""
    votes: dict = field(default_factory=dict)
    stop_loss: float = 0.0
    take_profit: float = 0.0


def trade_levels(price: float, atr: float, direction: str, risk_cfg: dict) -> tuple[float, float]:
    """ATR tabanli stop-loss ve take-profit seviyeleri (entry = price)."""
    sl_mult = float(risk_cfg.get("atr_sl_mult", 1.5))
    rr = float(risk_cfg.get("risk_reward", 1.8))
    sl_dist = sl_mult * atr
    if direction == "LONG":
        return price - sl_dist, price + sl_dist * rr
    if direction == "SHORT":
        return price + sl_dist, price - sl_dist * rr
    return 0.0, 0.0


def combine(ta: TASignal, ai: AIVerdict | None, cfg_strategy: dict) -> Decision:
    ai_weight = cfg_strategy.get("ai_weight", 0.0)
    min_conf = cfg_strategy.get("min_confidence", 55)
    require_agreement = cfg_strategy.get("require_ai_agreement", False)

    ta_signed = ta.score  # zaten -1..+1
    use_ai = ai is not None and ai.ok and ai_weight > 0

    if use_ai:
        ai_signed = _DIR_SIGN[ai.direction] * (ai.confidence / 100.0)
        combined = (1 - ai_weight) * ta_signed + ai_weight * ai_signed
    else:
        combined = ta_signed

    combined = max(-1.0, min(1.0, combined))
    confidence = round(abs(combined) * 100, 1)

    if combined > 0:
        direction = "LONG"
    elif combined < 0:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    note = ""
    # AI ile TA celisiyorsa ve mutabakat sartsa sinyali iptal et
    if use_ai and require_agreement and ai.direction != "NEUTRAL" and ai.direction != ta.direction:
        direction = "NEUTRAL"
        note = f"AI ({ai.direction}) ile TA ({ta.direction}) celisiyor -> iptal"

    # Guven esigi
    if direction != "NEUTRAL" and confidence < min_conf:
        note = note or f"Guven {confidence} < esik {min_conf} -> elendi"
        direction = "NEUTRAL"

    return Decision(
        symbol=ta.symbol,
        direction=direction,
        confidence=confidence,
        price=ta.price,
        atr=ta.atr,
        ta=ta,
        ai=ai,
        note=note,
        votes=ta.votes,
    )
