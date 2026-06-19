"""Teknik indikatorler — saf pandas/numpy (TA-Lib bagimliligi yok)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder yumusatmasi
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(100)


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def bollinger(
    series: pd.Series, period: int = 20, std_mult: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = sma(series, period)
    std = series.rolling(period).std(ddof=0)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(alpha=1 / period, adjust=False).mean()


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3
) -> tuple[pd.Series, pd.Series]:
    lowest = low.rolling(k).min()
    highest = high.rolling(k).max()
    rng = (highest - lowest).replace(0, np.nan)
    percent_k = 100 * (close - lowest) / rng
    percent_d = percent_k.rolling(d).mean()
    return percent_k.fillna(50), percent_d.fillna(50)


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX, +DI, -DI dondurur."""
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=high.index)
    minus_dm = pd.Series(minus_dm, index=high.index)

    atr_ = true_range(high, low, close).ewm(alpha=1 / period, adjust=False).mean()
    atr_safe = atr_.replace(0, np.nan)
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_safe)
    di_sum = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / di_sum
    adx_ = dx.ewm(alpha=1 / period, adjust=False).mean()
    return adx_.fillna(0), plus_di.fillna(0), minus_di.fillna(0)


def compute_all(df: pd.DataFrame) -> dict:
    """Son mum icin tum indikator degerlerini bir sozlukte dondurur."""
    close, high, low, vol = df["close"], df["high"], df["low"], df["volume"]

    ema9, ema21, ema50 = ema(close, 9), ema(close, 21), ema(close, 50)
    rsi14 = rsi(close, 14)
    macd_line, macd_sig, macd_hist = macd(close)
    bb_up, bb_mid, bb_low = bollinger(close)
    atr14 = atr(high, low, close, 14)
    stoch_k, stoch_d = stochastic(high, low, close)
    adx14, plus_di, minus_di = adx(high, low, close)
    vol_sma = sma(vol, 20)

    i = -1  # son kapanmis mum

    def last(s: pd.Series) -> float:
        v = s.iloc[i]
        return float(v) if pd.notna(v) else 0.0

    return {
        "price": last(close),
        "ema9": last(ema9),
        "ema21": last(ema21),
        "ema50": last(ema50),
        "rsi": last(rsi14),
        "macd": last(macd_line),
        "macd_signal": last(macd_sig),
        "macd_hist": last(macd_hist),
        "macd_hist_prev": float(macd_hist.iloc[i - 1]) if len(macd_hist) > 1 else 0.0,
        "bb_upper": last(bb_up),
        "bb_mid": last(bb_mid),
        "bb_lower": last(bb_low),
        "atr": last(atr14),
        "stoch_k": last(stoch_k),
        "stoch_d": last(stoch_d),
        "adx": last(adx14),
        "plus_di": last(plus_di),
        "minus_di": last(minus_di),
        "volume": last(vol),
        "vol_sma": last(vol_sma),
    }
