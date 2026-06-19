"""Binance USDT-M Futures public market verisi (API anahtari gerekmez)."""
from __future__ import annotations

import time
from typing import Any

import pandas as pd
import requests


class BinanceFutures:
    def __init__(self, base_url: str = "https://fapi.binance.com", timeout: int = 15):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "scalp-bot/0.2"})

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.base}{path}"
        last_err = None
        for attempt in range(4):
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as e:
                last_err = e
                if attempt < 3:
                    time.sleep(min(2 ** attempt, 8))
        raise RuntimeError(f"Binance istegi basarisiz: {url} ({last_err})")

    def exchange_info(self) -> dict:
        return self._get("/fapi/v1/exchangeInfo")

    def ticker_24h(self) -> list[dict]:
        """Tum semboller icin 24s istatistik (fiyat + hacim)."""
        return self._get("/fapi/v1/ticker/24hr")

    def tradable_usdt_symbols(self) -> set[str]:
        """Aktif olarak islem goren PERPETUAL USDT pariteleri."""
        info = self.exchange_info()
        out: set[str] = set()
        for s in info.get("symbols", []):
            if (
                s.get("quoteAsset") == "USDT"
                and s.get("contractType") == "PERPETUAL"
                and s.get("status") == "TRADING"
            ):
                out.add(s["symbol"])
        return out

    def screen_symbols(
        self,
        max_price: float,
        min_quote_volume: float,
        quote_asset: str = "USDT",
    ) -> list[dict]:
        """Fiyati < max_price ve hacmi yeterli coinleri dondurur (hacme gore sirali)."""
        tradable = self.tradable_usdt_symbols()
        rows = []
        for t in self.ticker_24h():
            sym = t.get("symbol", "")
            if sym not in tradable or not sym.endswith(quote_asset):
                continue
            try:
                price = float(t["lastPrice"])
                qvol = float(t["quoteVolume"])
            except (KeyError, ValueError):
                continue
            if 0 < price < max_price and qvol >= min_quote_volume:
                rows.append(
                    {
                        "symbol": sym,
                        "price": price,
                        "quote_volume": qvol,
                        "change_pct": float(t.get("priceChangePercent", 0) or 0),
                    }
                )
        rows.sort(key=lambda r: r["quote_volume"], reverse=True)
        return rows

    def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> pd.DataFrame:
        data = self._get(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
        )
        cols = [
            "open_time", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore",
        ]
        df = pd.DataFrame(data, columns=cols)
        for c in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms")
        return df

    def funding_rate(self, symbol: str) -> float:
        """Sembol icin guncel funding rate (ondalik, ornek: 0.0001 = 0.01%)."""
        try:
            data = self._get("/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1})
            if isinstance(data, list) and data:
                return float(data[0].get("fundingRate", 0))
        except Exception:
            pass
        return 0.0

    def open_interest(self, symbol: str) -> float:
        """Sembol icin acik faiz miktari (coin cinsinden)."""
        try:
            data = self._get("/fapi/v1/openInterest", {"symbol": symbol})
            return float(data.get("openInterest", 0))
        except Exception:
            return 0.0

    def validate_symbol(self, symbol: str) -> bool:
        """Sembolun Binance Futures'ta gecerli olup olmadigini kontrol eder."""
        try:
            tradable = self.tradable_usdt_symbols()
            return symbol in tradable
        except Exception:
            return False
