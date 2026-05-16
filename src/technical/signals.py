"""
テクニカル分析・売買シグナル判定エンジン
指標: SMA, EMA, MACD, RSI, ボリンジャーバンド, 出来高比率
"""
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("signals")

# シグナル定数
SIGNAL_BUY = "BUY"
SIGNAL_SELL = "SELL"
SIGNAL_HOLD = "HOLD"
SIGNAL_WATCH = "WATCH"


# ---- テクニカル指標計算 ----

def calc_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def calc_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(window=period).mean()
    loss = (-delta.clip(upper=0)).rolling(window=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def calc_macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = calc_ema(series, fast)
    ema_slow = calc_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calc_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return pd.DataFrame({
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }, index=series.index)


def calc_bollinger(series: pd.Series, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    mid = calc_sma(series, period)
    std = series.rolling(window=period).std()
    return pd.DataFrame({
        "bb_upper": mid + std_dev * std,
        "bb_mid": mid,
        "bb_lower": mid - std_dev * std,
    }, index=series.index)


def calc_volume_ratio(volume: pd.Series, period: int = 20) -> pd.Series:
    avg_vol = volume.rolling(window=period).mean()
    return volume / avg_vol.replace(0, np.nan)


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """OHLCVデータに全テクニカル指標を追加して返す"""
    close = df["Close"]
    volume = df["Volume"]

    df = df.copy()
    df["sma5"] = calc_sma(close, 5)
    df["sma20"] = calc_sma(close, 20)
    df["sma75"] = calc_sma(close, 75)
    df["ema12"] = calc_ema(close, 12)
    df["ema26"] = calc_ema(close, 26)
    df["rsi14"] = calc_rsi(close, 14)

    macd_df = calc_macd(close)
    df["macd"] = macd_df["macd"]
    df["macd_signal"] = macd_df["signal"]
    df["macd_hist"] = macd_df["histogram"]

    bb_df = calc_bollinger(close)
    df["bb_upper"] = bb_df["bb_upper"]
    df["bb_mid"] = bb_df["bb_mid"]
    df["bb_lower"] = bb_df["bb_lower"]

    df["volume_ratio"] = calc_volume_ratio(volume)
    return df


# ---- シグナル判定 ----

def determine_signal(
    df: pd.DataFrame,
    rsi_oversold: float = 35,
    rsi_overbought: float = 75,
    volume_threshold: float = 1.2,
    earnings_date: Optional[datetime] = None,
    earnings_hold_days: int = 3,
) -> dict:
    """
    最新日のテクニカルデータからシグナルを判定する。

    Returns:
        dict: {signal, strength, reasons, indicators}
    """
    if len(df) < 30:
        return _build_result(SIGNAL_WATCH, 0, ["データ不足（30営業日未満）"], df)

    latest = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else latest

    reasons = []
    buy_score = 0
    sell_score = 0

    # --- フェイクアウト回避: 決算前後はHOLD ---
    if earnings_date:
        now = datetime.now()
        days_to_earnings = (earnings_date - now).days
        if -earnings_hold_days <= days_to_earnings <= earnings_hold_days:
            reasons.append(f"決算発表が{days_to_earnings}日後（フェイクアウト回避でHOLD）")
            return _build_result(SIGNAL_HOLD, 0, reasons, df)

    # --- ゴールデンクロス / デッドクロス ---
    gc_now = latest["sma5"] > latest["sma20"]
    gc_prev = prev["sma5"] > prev["sma20"]

    if gc_now and not gc_prev:
        reasons.append("ゴールデンクロス発生（SMA5 > SMA20）")
        buy_score += 3
    elif gc_now:
        reasons.append("ゴールデンクロス維持（SMA5 > SMA20）")
        buy_score += 1
    elif not gc_now and gc_prev:
        reasons.append("デッドクロス発生（SMA5 < SMA20）")
        sell_score += 3
    else:
        reasons.append("デッドクロス維持（SMA5 < SMA20）")
        sell_score += 1

    # --- RSI ---
    rsi = latest["rsi14"]
    prev_rsi = prev["rsi14"]
    if rsi < rsi_oversold and rsi > prev_rsi:
        reasons.append(f"RSI売られすぎ({rsi:.1f})から反転上昇")
        buy_score += 2
    elif rsi > rsi_overbought and rsi < prev_rsi:
        reasons.append(f"RSI過熱({rsi:.1f})から反転下落")
        sell_score += 2
    elif rsi < rsi_oversold:
        reasons.append(f"RSI売られすぎ圏({rsi:.1f})")
        buy_score += 1
    elif rsi > rsi_overbought:
        reasons.append(f"RSI過熱圏({rsi:.1f})")
        sell_score += 1

    # --- MACD ヒストグラム ---
    hist = latest["macd_hist"]
    prev_hist = prev["macd_hist"]
    if hist > 0 and prev_hist <= 0:
        reasons.append("MACDヒストグラムがプラス転換（上昇モメンタム）")
        buy_score += 2
    elif hist < 0 and prev_hist >= 0:
        reasons.append("MACDヒストグラムがマイナス転換（下落モメンタム）")
        sell_score += 2
    elif hist > 0:
        reasons.append("MACDヒストグラムがプラス圏")
        buy_score += 1
    else:
        reasons.append("MACDヒストグラムがマイナス圏")
        sell_score += 1

    # --- ボリンジャーバンド ---
    close = latest["Close"]
    if close > latest["bb_upper"]:
        reasons.append("ボリンジャー上限ブレイク（過熱注意）")
        sell_score += 1
    elif close < latest["bb_lower"]:
        reasons.append("ボリンジャー下限ブレイク（反発期待）")
        buy_score += 1

    # --- 出来高 ---
    vol_ratio = latest["volume_ratio"]
    if vol_ratio >= volume_threshold:
        reasons.append(f"出来高比率 {vol_ratio:.1f}x（出来高増加で確度UP）")
        if buy_score > sell_score:
            buy_score += 1
        else:
            sell_score += 1

    # --- シグナル判定 ---
    if buy_score > sell_score and buy_score >= 3:
        signal = SIGNAL_BUY
        strength = min(buy_score, 10)
    elif sell_score > buy_score and sell_score >= 3:
        signal = SIGNAL_SELL
        strength = min(sell_score, 10)
    else:
        signal = SIGNAL_WATCH
        strength = 0

    return _build_result(signal, strength, reasons, df)


def _build_result(signal: str, strength: int, reasons: list, df: pd.DataFrame) -> dict:
    latest = df.iloc[-1]
    return {
        "signal": signal,
        "strength": strength,
        "reasons": reasons,
        "indicators": {
            "close": round(float(latest["Close"]), 1),
            "sma5": _safe_round(latest.get("sma5")),
            "sma20": _safe_round(latest.get("sma20")),
            "sma75": _safe_round(latest.get("sma75")),
            "rsi14": _safe_round(latest.get("rsi14"), 1),
            "macd": _safe_round(latest.get("macd"), 2),
            "macd_hist": _safe_round(latest.get("macd_hist"), 2),
            "bb_upper": _safe_round(latest.get("bb_upper")),
            "bb_lower": _safe_round(latest.get("bb_lower")),
            "volume_ratio": _safe_round(latest.get("volume_ratio"), 2),
        },
        "date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
    }


def _safe_round(val, decimals: int = 1):
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return None


def signal_emoji(signal: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "WATCH": "⚪"}.get(signal, "⚪")
