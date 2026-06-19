"""$10 bakiyeyle paper trading simulasyonu — pozisyon ac/kapat, PnL ve istatistik."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import trade_levels


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Position:
    symbol: str
    direction: str          # LONG / SHORT
    entry: float
    qty: float              # coin adedi
    notional: float         # entry * qty (USDT)
    margin: float           # ayrilan teminat
    leverage: float
    stop_loss: float
    take_profit: float
    opened_at: str
    confidence: float = 0.0
    reason: str = ""


@dataclass
class ClosedTrade:
    symbol: str
    direction: str
    entry: float
    exit: float
    qty: float
    pnl: float              # net (komisyon dusulmus)
    pnl_pct: float          # marjine gore %
    outcome: str            # TP / SL / CLOSE
    opened_at: str
    closed_at: str


@dataclass
class PaperState:
    balance: float
    start_balance: float
    open_positions: list[Position] = field(default_factory=list)
    closed_trades: list[ClosedTrade] = field(default_factory=list)


class PaperTrader:
    def __init__(self, state_path: str | Path, risk_cfg: dict):
        self.path = Path(state_path)
        self.risk = risk_cfg
        self.state = self._load()

    # ── persistence ────────────────────────────────────────────
    def _load(self) -> PaperState:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return PaperState(
                balance=raw["balance"],
                start_balance=raw["start_balance"],
                open_positions=[Position(**p) for p in raw.get("open_positions", [])],
                closed_trades=[ClosedTrade(**t) for t in raw.get("closed_trades", [])],
            )
        start = float(self.risk.get("start_balance", 10.0))
        return PaperState(balance=start, start_balance=start)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "balance": self.state.balance,
            "start_balance": self.state.start_balance,
            "updated_at": _now(),
            "open_positions": [asdict(p) for p in self.state.open_positions],
            "closed_trades": [asdict(t) for t in self.state.closed_trades],
        }
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ── yardimcilar ────────────────────────────────────────────
    def has_position(self, symbol: str) -> bool:
        return any(p.symbol == symbol for p in self.state.open_positions)

    @property
    def open_count(self) -> int:
        return len(self.state.open_positions)

    def _fee(self, notional: float) -> float:
        return notional * float(self.risk.get("fee_rate", 0.0005))

    # ── pozisyon acma ──────────────────────────────────────────
    def open_position(self, decision, atr: float) -> Position | None:
        if decision.direction not in ("LONG", "SHORT"):
            return None
        if self.has_position(decision.symbol):
            return None
        if self.open_count >= int(self.risk.get("max_open_positions", 5)):
            return None
        if atr <= 0 or decision.price <= 0:
            return None

        leverage = float(self.risk.get("leverage", 10))
        fixed_margin = float(self.risk.get("fixed_margin", 0))
        margin = fixed_margin if fixed_margin > 0 else self.state.balance * float(self.risk.get("risk_fraction", 0.25))
        if margin < 0.1:
            return None
        notional = margin * leverage
        qty = notional / decision.price

        stop_loss, take_profit = trade_levels(decision.price, atr, decision.direction, self.risk)

        # acilis komisyonu pesin dusulur
        self.state.balance -= self._fee(notional)

        pos = Position(
            symbol=decision.symbol,
            direction=decision.direction,
            entry=decision.price,
            qty=qty,
            notional=notional,
            margin=margin,
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=_now(),
            confidence=decision.confidence,
            reason=(decision.ai.reason if decision.ai and decision.ai.ok else decision.note),
        )
        self.state.open_positions.append(pos)
        return pos

    # ── acik pozisyonlari guncel fiyata gore degerlendir ───────
    def update_positions(self, prices: dict[str, float]) -> list[ClosedTrade]:
        """SL/TP'ye deyen pozisyonlari kapatir. Kapanan islemleri dondurur."""
        still_open: list[Position] = []
        closed: list[ClosedTrade] = []

        for p in self.state.open_positions:
            price = prices.get(p.symbol)
            if price is None:
                still_open.append(p)
                continue

            outcome = None
            exit_price = price
            if p.direction == "LONG":
                if price <= p.stop_loss:
                    outcome, exit_price = "SL", p.stop_loss
                elif price >= p.take_profit:
                    outcome, exit_price = "TP", p.take_profit
            else:  # SHORT
                if price >= p.stop_loss:
                    outcome, exit_price = "SL", p.stop_loss
                elif price <= p.take_profit:
                    outcome, exit_price = "TP", p.take_profit

            if outcome is None:
                still_open.append(p)
                continue

            closed.append(self._close(p, exit_price, outcome))

        self.state.open_positions = still_open
        return closed

    def force_close_all(self, prices: dict[str, float]) -> list[ClosedTrade]:
        closed = []
        for p in list(self.state.open_positions):
            price = prices.get(p.symbol, p.entry)
            closed.append(self._close(p, price, "CLOSE"))
        self.state.open_positions = []
        return closed

    def _close(self, p: Position, exit_price: float, outcome: str) -> ClosedTrade:
        sign = 1.0 if p.direction == "LONG" else -1.0
        gross = sign * (exit_price - p.entry) * p.qty
        exit_notional = exit_price * p.qty
        net = gross - self._fee(exit_notional)
        self.state.balance += net
        pnl_pct = (net / p.margin * 100) if p.margin else 0.0

        trade = ClosedTrade(
            symbol=p.symbol,
            direction=p.direction,
            entry=p.entry,
            exit=exit_price,
            qty=p.qty,
            pnl=round(net, 4),
            pnl_pct=round(pnl_pct, 2),
            outcome=outcome,
            opened_at=p.opened_at,
            closed_at=_now(),
        )
        self.state.closed_trades.append(trade)
        return trade

    # ── istatistik ─────────────────────────────────────────────
    def stats(self) -> dict:
        trades = self.state.closed_trades
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        total = len(trades)
        win_rate = (len(wins) / total * 100) if total else 0.0
        total_pnl = sum(t.pnl for t in trades)
        roi = ((self.state.balance - self.state.start_balance) / self.state.start_balance * 100)
        return {
            "balance": round(self.state.balance, 4),
            "start_balance": self.state.start_balance,
            "roi_pct": round(roi, 2),
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 1),
            "total_pnl": round(total_pnl, 4),
            "open_positions": self.open_count,
        }
