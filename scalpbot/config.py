"""Yapilandirma yukleme: config.yaml + .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv opsiyonel
    def load_dotenv(*_args, **_kwargs):  # type: ignore
        return False


ROOT = Path(__file__).resolve().parent.parent

# Vercel/serverless ortamında data dosyaları /tmp/ altında tutulur
_VERCEL_DATA = os.getenv("VERCEL_DATA_DIR", "")
DATA_ROOT: Path = Path(_VERCEL_DATA) if _VERCEL_DATA else ROOT


@dataclass
class Config:
    raw: dict[str, Any]
    # env
    minimax_api_key: str = ""
    minimax_base_url: str = ""
    minimax_model: str = ""
    binance_fapi_base: str = "https://fapi.binance.com"

    # alt erisim kisayollari
    market: dict = field(default_factory=dict)
    strategy: dict = field(default_factory=dict)
    risk: dict = field(default_factory=dict)
    run: dict = field(default_factory=dict)

    @property
    def ai_enabled(self) -> bool:
        return bool(self.minimax_api_key)


def load_config(config_path: str | Path | None = None) -> Config:
    load_dotenv(ROOT / ".env")

    path = Path(config_path) if config_path else ROOT / "config.yaml"
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    return Config(
        raw=raw,
        minimax_api_key=os.getenv("MINIMAX_API_KEY", "").strip(),
        minimax_base_url=os.getenv(
            "MINIMAX_BASE_URL", "https://api.minimaxi.chat/v1/text/chatcompletion_v2"
        ).strip(),
        minimax_model=os.getenv("MINIMAX_MODEL", "MiniMax-M3").strip(),
        binance_fapi_base=os.getenv("BINANCE_FAPI_BASE", "https://fapi.binance.com").strip(),
        market=raw.get("market", {}),
        strategy=raw.get("strategy", {}),
        risk=raw.get("risk", {}),
        run={
            **raw.get("run", {}),
            # Vercel ortamında data dizinini /tmp/ altına yönlendir
            **({"report_dir": str(DATA_ROOT / "data"), "state_file": str(DATA_ROOT / "data/state.json")}
               if _VERCEL_DATA else {}),
        },
    )
