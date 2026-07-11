"""
テクニカル分析・売買シグナル判定エンジン
指標: SMA, EMA, MACD, RSI, ボリンジャーバンド, 出来高比率
追加: 市場レジーム判定（強気/弱気/中立）, チャートパターン認識
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

# 市場レジーム定数
REGIME_BULL = "BULL"
REGIME_BEAR = "BEAR"
REGIME_NEUTRAL = "NEUTRAL"

# シグナルスコアの重み（settings.yaml の technical.signal_weights で上書き可能）
#
# 2026-07 に11,296銘柄日のパネル分析（方向性検証・OLS回帰）と18ヶ月×38銘柄の
# バックテスト（学習2025/検証2026分割）で再調整した。詳細は
# output/algorithm_evaluation_20260711.md 第2弾・第3弾を参照。
#   - RSI逆張り（売られすぎ買い/過熱売り）はこのユニバースでは方向が逆
#     （売られすぎ反転買いの以後10日は市場平均比-0.99%、過熱反転は+0.60%）→ 0点
#   - ボリンジャー下限ブレイクの「反発期待」買いも逆（同-1.74%、t=-4.0）→ 0点
#   - SELL閾値4 = デッドクロス発生（3点）単独では売らず、もう1つの弱気要素で確定
#   - 上記の組で全期間平均 +2.22% → +4.10%/トレード（テール5%分位も-11.1%→-9.7%に改善）
DEFAULT_WEIGHTS = {
    "gc_new": 3,          # ゴールデンクロス発生
    "gc_hold": 1,         # ゴールデンクロス維持（パネル分析で最も頑健な買い材料）
    "dc_new": 3,          # デッドクロス発生（SELL側）
    "dc_hold": 1,         # デッドクロス維持（SELL側）
    "rsi_reversal": 0,    # RSI反転（逆張り成分: 方向逆転のため無効化）
    "rsi_zone": 0,        # RSIゾーン滞留（同上）
    "macd_cross": 2,      # MACDヒストグラム転換
    "macd_zone": 1,       # MACDヒストグラム圏内滞留
    "bb_break": 0,        # ボリンジャーバンドブレイク（逆張り成分: 方向逆転のため無効化）
    "volume_confirm": 1,  # 出来高増加の確度加点
    "pattern_scale": 1.0, # チャートパターンスコアの倍率
    "sell_threshold": 4,  # SELL判定の閾値
}


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


# ---- 市場レジーム判定 ----

def detect_market_regime(index_df: pd.DataFrame) -> dict:
    """
    市場全体の強弱（強気/弱気/中立）を判定する。

    一般的なファンドマネージャーの判断基準:
    - 強気(BULL): 指数が200日SMA超 AND 50日SMAが上向き → BUY閾値3点
    - 弱気(BEAR): 指数が200日SMA割れ AND 50日SMAが下向き → BUY閾値5点
    - 中立(NEUTRAL): 中間状態 → BUY閾値4点

    Args:
        index_df: 市場指数の日足OHLCV（日経225: ^N225, TOPIX ETF: 1306.T 等）

    Returns:
        dict: {regime, buy_threshold, score, reasons}
    """
    if len(index_df) < 200:
        return {
            "regime": REGIME_NEUTRAL,
            "buy_threshold": 4,
            "score": 0,
            "reasons": ["市場指数データ不足（200日未満）— 中立とみなす"],
        }

    close = index_df["Close"] if "Close" in index_df.columns else index_df.iloc[:, 0]
    sma50_series = calc_sma(close, 50)
    sma200_series = calc_sma(close, 200)
    sma50 = sma50_series.iloc[-1]
    sma200 = sma200_series.iloc[-1]
    current = close.iloc[-1]

    # 50日SMAの傾き（20日前比）
    sma50_20d = sma50_series.iloc[-20]
    sma50_slope = (sma50 - sma50_20d) / sma50_20d if sma50_20d > 0 else 0.0

    score = 0
    reasons = []

    # 指数 vs 200日SMA（±2点）
    pct_200 = (current - sma200) / sma200 * 100
    if current > sma200:
        score += 2
        reasons.append(f"指数が200日SMA超（+{pct_200:.1f}%）: 中長期トレンド強気")
    else:
        score -= 2
        reasons.append(f"指数が200日SMA割れ（{pct_200:.1f}%）: 中長期トレンド弱気")

    # 指数 vs 50日SMA（±1点）
    pct_50 = (current - sma50) / sma50 * 100
    if current > sma50:
        score += 1
        reasons.append(f"指数が50日SMA超（+{pct_50:.1f}%）: 短期トレンド強気")
    else:
        score -= 1
        reasons.append(f"指数が50日SMA割れ（{pct_50:.1f}%）: 短期トレンド弱気")

    # 50日SMAの傾き（±2点）
    slope_pct = sma50_slope * 100
    if sma50_slope > 0.02:
        score += 2
        reasons.append(f"50日SMAが上昇傾向（+{slope_pct:.1f}%/20日）: モメンタム強気")
    elif sma50_slope > 0:
        score += 1
        reasons.append(f"50日SMAが緩やかに上昇（+{slope_pct:.1f}%/20日）")
    elif sma50_slope < -0.02:
        score -= 2
        reasons.append(f"50日SMAが下降傾向（{slope_pct:.1f}%/20日）: モメンタム弱気")
    else:
        score -= 1
        reasons.append(f"50日SMAが緩やかに下降（{slope_pct:.1f}%/20日）")

    if score >= 3:
        regime, buy_threshold = REGIME_BULL, 3
    elif score <= -3:
        regime, buy_threshold = REGIME_BEAR, 5
    else:
        regime, buy_threshold = REGIME_NEUTRAL, 4

    return {"regime": regime, "buy_threshold": buy_threshold, "score": score, "reasons": reasons}


# ---- チャートパターン認識 ----

def _find_local_extrema(series: pd.Series, window: int = 5) -> tuple[list[int], list[int]]:
    """ローカルな極大・極小のインデックスを返す（scipy不使用）"""
    values = series.values
    n = len(values)
    maxima: list[int] = []
    minima: list[int] = []
    for i in range(window, n - window):
        neighborhood = values[i - window: i + window + 1]
        if values[i] == max(neighborhood) and values[i] > values[i - 1] and values[i] > values[i + 1]:
            maxima.append(i)
        if values[i] == min(neighborhood) and values[i] < values[i - 1] and values[i] < values[i + 1]:
            minima.append(i)
    return maxima, minima


def detect_chart_patterns(df: pd.DataFrame) -> dict:
    """
    チャートの形状パターンを検出する。

    対応パターン（強気）:
    - ブレイクアウト: 直近200日高値を出来高急増で上抜け
    - ダブルボトム: 同水準の2回の底値 → 反転期待
    - ブルフラッグ: 急騰後の狭いレンジ（押し目買い）
    - カップ・アンド・ハンドル: U字回復後のハンドル形成

    対応パターン（弱気）:
    - ダブルトップ: 同水準の2回の高値 → 天井圏警戒
    - ヘッドアンドショルダーズ: 三山（中央最高）→ 下落転換

    Returns:
        dict: {
            "bullish": [{"pattern": str, "score": int, "reason": str}],
            "bearish": [{"pattern": str, "score": int, "reason": str}],
            "net_score": int,  # bullish合計 - bearish合計
            "summary": str
        }
    """
    bullish: list[dict] = []
    bearish: list[dict] = []

    if len(df) < 60:
        return {"bullish": bullish, "bearish": bearish, "net_score": 0, "summary": "データ不足"}

    close = df["Close"]
    volume = df["Volume"] if "Volume" in df.columns else None
    recent = close.iloc[-60:]

    # ---- ブレイクアウト ----
    high_200 = close.iloc[-200:].max() if len(close) >= 200 else close.max()
    latest_close = close.iloc[-1]
    vol_ratio_latest = df["volume_ratio"].iloc[-1] if "volume_ratio" in df.columns else 1.0
    if latest_close >= high_200 * 1.01 and vol_ratio_latest >= 1.5:
        bullish.append({
            "pattern": "ブレイクアウト",
            "score": 3,
            "reason": f"200日高値（{high_200:.0f}）を出来高急増（{vol_ratio_latest:.1f}x）で上抜け"
        })
    elif latest_close >= high_200 * 1.005:
        bullish.append({
            "pattern": "ブレイクアウト（出来高未確認）",
            "score": 1,
            "reason": f"200日高値付近まで上昇（{latest_close:.0f} / 高値{high_200:.0f}）"
        })

    # ---- ダブルボトム ----
    _, minima = _find_local_extrema(recent, window=5)
    if len(minima) >= 2:
        b1_idx, b2_idx = minima[-2], minima[-1]
        b1, b2 = recent.iloc[b1_idx], recent.iloc[b2_idx]
        bottom_avg = (b1 + b2) / 2
        diff_pct = abs(b1 - b2) / bottom_avg
        # 2つの底値が互いに5%以内、かつ底値から現在が5%以上回復
        recovery = (latest_close - bottom_avg) / bottom_avg
        if diff_pct < 0.05 and recovery >= 0.05 and b2_idx > b1_idx + 10:
            bullish.append({
                "pattern": "ダブルボトム",
                "score": 2,
                "reason": f"同水準の底値2回（{b1:.0f}/{b2:.0f}）から{recovery*100:.1f}%回復"
            })

    # ---- ブルフラッグ ----
    if len(df) >= 30:
        prior_20 = close.iloc[-30:-10]
        recent_10 = close.iloc[-10:]
        surge = (prior_20.iloc[-1] - prior_20.iloc[0]) / prior_20.iloc[0]
        if surge >= 0.10:  # 直近20日で10%以上急騰
            range_pct = (recent_10.max() - recent_10.min()) / recent_10.min()
            if range_pct <= 0.05:  # 直近10日のレンジが5%以内（狭い）
                bullish.append({
                    "pattern": "ブルフラッグ",
                    "score": 2,
                    "reason": f"急騰（+{surge*100:.1f}%）後の狭いレンジ（±{range_pct*100:.1f}%）: 押し目買い機会"
                })

    # ---- カップ・アンド・ハンドル ----
    if len(close) >= 90:
        cup_window = close.iloc[-90:-10]
        handle_window = close.iloc[-10:]
        cup_high = cup_window.max()
        cup_low = cup_window.min()
        depth = (cup_high - cup_low) / cup_high
        # カップの深さ15〜35%、ハンドルが高値付近（10%以内）
        handle_high = handle_window.max()
        if 0.15 <= depth <= 0.35 and handle_high >= cup_high * 0.90:
            handle_pullback = (handle_high - handle_window.min()) / handle_high
            if 0.03 <= handle_pullback <= 0.15:
                bullish.append({
                    "pattern": "カップ・アンド・ハンドル",
                    "score": 2,
                    "reason": f"カップ深さ{depth*100:.1f}%・ハンドル調整{handle_pullback*100:.1f}%: ブレイクアウト待機"
                })

    # ---- ダブルトップ ----
    maxima, _ = _find_local_extrema(recent, window=5)
    if len(maxima) >= 2:
        t1_idx, t2_idx = maxima[-2], maxima[-1]
        t1, t2 = recent.iloc[t1_idx], recent.iloc[t2_idx]
        top_avg = (t1 + t2) / 2
        diff_pct = abs(t1 - t2) / top_avg
        # 2つの高値が互いに5%以内、かつ現在が高値から5%以上下落
        decline = (top_avg - latest_close) / top_avg
        if diff_pct < 0.05 and decline >= 0.05 and t2_idx > t1_idx + 10:
            bearish.append({
                "pattern": "ダブルトップ",
                "score": 2,
                "reason": f"同水準の高値2回（{t1:.0f}/{t2:.0f}）から{decline*100:.1f}%下落: 天井圏警戒"
            })

    # ---- ヘッドアンドショルダーズ（簡易判定）----
    if len(close) >= 90:
        seg = close.iloc[-90:]
        peaks, _ = _find_local_extrema(seg, window=8)
        if len(peaks) >= 3:
            ls, head, rs = peaks[-3], peaks[-2], peaks[-1]
            head_price = seg.iloc[head]
            ls_price, rs_price = seg.iloc[ls], seg.iloc[rs]
            shoulder_avg = (ls_price + rs_price) / 2
            # ヘッドが両ショルダーより5%以上高く、両ショルダーが互いに10%以内
            if (head_price > shoulder_avg * 1.05
                    and abs(ls_price - rs_price) / shoulder_avg < 0.10
                    and latest_close < shoulder_avg * 0.97):
                bearish.append({
                    "pattern": "ヘッドアンドショルダーズ",
                    "score": 3,
                    "reason": f"三山パターン（肩:{shoulder_avg:.0f}/頭:{head_price:.0f}）ネックライン割れ"
                })

    net_score = sum(p["score"] for p in bullish) - sum(p["score"] for p in bearish)
    bullish_names = [p["pattern"] for p in bullish]
    bearish_names = [p["pattern"] for p in bearish]

    if bullish_names and not bearish_names:
        summary = f"強気パターン検出: {', '.join(bullish_names)}"
    elif bearish_names and not bullish_names:
        summary = f"弱気パターン検出: {', '.join(bearish_names)}"
    elif bullish_names and bearish_names:
        summary = f"強弱混在: 強気={', '.join(bullish_names)} / 弱気={', '.join(bearish_names)}"
    else:
        summary = "パターンなし（通常のチャート形状）"

    return {"bullish": bullish, "bearish": bearish, "net_score": net_score, "summary": summary}


# ---- シグナル判定 ----

def _apply_score(weight, reason: str, reasons: list):
    """重みが有効（>0）な場合のみ判定理由に記録し、重みを返す。

    理由欄は「スコアに寄与した条件」だけを列挙する契約とし、
    無効化された条件（重み0）が判定理由に紛れ込まないようにする。
    """
    if weight > 0:
        reasons.append(reason)
    return weight

def determine_signal(
    df: pd.DataFrame,
    rsi_oversold: float = 35,
    rsi_overbought: float = 75,
    volume_threshold: float = 1.2,
    earnings_date: Optional[datetime] = None,
    earnings_hold_days: int = 3,
    market_regime: Optional[dict] = None,
    weights: Optional[dict] = None,
) -> dict:
    """
    最新日のテクニカルデータからシグナルを判定する。

    market_regime が指定された場合、BUY判定の閾値を市場環境に応じて変動させる:
    - BULL相場: 閾値3点（通常）
    - NEUTRAL: 閾値4点（やや厳しく）
    - BEAR相場: 閾値5点（大幅に厳しく — 逆張りを避ける）

    weights で構成要素ごとのスコア重みを上書きできる（キーは DEFAULT_WEIGHTS 参照）。

    reasons（判定理由）には**スコアに実際に寄与した条件のみ**を記録する。
    重み0で無効化された条件は成立していても理由欄に載らない（理由欄とロジックの整合性を保証）。

    Returns:
        dict: {signal, strength, reasons, indicators, chart_patterns, market_regime}
    """
    if len(df) < 30:
        return _build_result(SIGNAL_WATCH, 0, ["データ不足（30営業日未満）"], df, {}, market_regime)

    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    buy_threshold = market_regime["buy_threshold"] if market_regime else 3

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
        buy_score += _apply_score(w["gc_new"], "ゴールデンクロス発生（SMA5 > SMA20）", reasons)
    elif gc_now:
        buy_score += _apply_score(w["gc_hold"], "ゴールデンクロス維持（SMA5 > SMA20）", reasons)
    elif not gc_now and gc_prev:
        sell_score += _apply_score(w["dc_new"], "デッドクロス発生（SMA5 < SMA20）", reasons)
    else:
        sell_score += _apply_score(w["dc_hold"], "デッドクロス維持（SMA5 < SMA20）", reasons)

    # --- RSI（デフォルト重み0: 方向逆転のため無効化。重みを設定した場合のみ寄与） ---
    rsi = latest["rsi14"]
    prev_rsi = prev["rsi14"]
    if rsi < rsi_oversold and rsi > prev_rsi:
        buy_score += _apply_score(w["rsi_reversal"], f"RSI売られすぎ({rsi:.1f})から反転上昇", reasons)
    elif rsi > rsi_overbought and rsi < prev_rsi:
        sell_score += _apply_score(w["rsi_reversal"], f"RSI過熱({rsi:.1f})から反転下落", reasons)
    elif rsi < rsi_oversold:
        buy_score += _apply_score(w["rsi_zone"], f"RSI売られすぎ圏({rsi:.1f})", reasons)
    elif rsi > rsi_overbought:
        sell_score += _apply_score(w["rsi_zone"], f"RSI過熱圏({rsi:.1f})", reasons)

    # --- MACD ヒストグラム ---
    hist = latest["macd_hist"]
    prev_hist = prev["macd_hist"]
    if hist > 0 and prev_hist <= 0:
        buy_score += _apply_score(w["macd_cross"], "MACDヒストグラムがプラス転換（上昇モメンタム）", reasons)
    elif hist < 0 and prev_hist >= 0:
        sell_score += _apply_score(w["macd_cross"], "MACDヒストグラムがマイナス転換（下落モメンタム）", reasons)
    elif hist > 0:
        buy_score += _apply_score(w["macd_zone"], "MACDヒストグラムがプラス圏", reasons)
    else:
        sell_score += _apply_score(w["macd_zone"], "MACDヒストグラムがマイナス圏", reasons)

    # --- ボリンジャーバンド（デフォルト重み0: 方向逆転のため無効化） ---
    close = latest["Close"]
    if close > latest["bb_upper"]:
        sell_score += _apply_score(w["bb_break"], "ボリンジャー上限ブレイク（過熱注意）", reasons)
    elif close < latest["bb_lower"]:
        buy_score += _apply_score(w["bb_break"], "ボリンジャー下限ブレイク（反発期待）", reasons)

    # --- 出来高 ---
    vol_ratio = latest["volume_ratio"]
    if vol_ratio >= volume_threshold and w["volume_confirm"] > 0:
        reasons.append(f"出来高比率 {vol_ratio:.1f}x（出来高増加で確度UP）")
        if buy_score > sell_score:
            buy_score += w["volume_confirm"]
        else:
            sell_score += w["volume_confirm"]

    # --- チャートパターン ---
    chart_patterns = detect_chart_patterns(df)
    for p in chart_patterns.get("bullish", []):
        buy_score += _apply_score(p["score"] * w["pattern_scale"], f"[パターン] {p['pattern']}: {p['reason']}", reasons)
    for p in chart_patterns.get("bearish", []):
        sell_score += _apply_score(p["score"] * w["pattern_scale"], f"[パターン] {p['pattern']}: {p['reason']}", reasons)

    # --- 市場レジームの情報を理由に追記 ---
    if market_regime:
        regime_label = {"BULL": "強気相場", "BEAR": "弱気相場", "NEUTRAL": "中立相場"}.get(
            market_regime["regime"], market_regime["regime"]
        )
        reasons.append(
            f"[市場環境] {regime_label}（BUY閾値: {buy_threshold}点）"
            f" — {', '.join(market_regime.get('reasons', [])[:1])}"
        )

    # --- シグナル判定（市場レジームによる動的閾値）---
    if buy_score > sell_score and buy_score >= buy_threshold:
        signal = SIGNAL_BUY
        strength = min(int(round(buy_score)), 10)
    elif sell_score > buy_score and sell_score >= w["sell_threshold"]:
        signal = SIGNAL_SELL
        strength = min(int(round(sell_score)), 10)
    else:
        signal = SIGNAL_WATCH
        strength = 0

    return _build_result(signal, strength, reasons, df, chart_patterns, market_regime)


def _build_result(
    signal: str,
    strength: int,
    reasons: list,
    df: pd.DataFrame,
    chart_patterns: Optional[dict] = None,
    market_regime: Optional[dict] = None,
) -> dict:
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
        "chart_patterns": chart_patterns or {"bullish": [], "bearish": [], "net_score": 0, "summary": ""},
        "market_regime": market_regime,
        "date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else str(df.index[-1]),
    }


def _safe_round(val, decimals: int = 1):
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return None


def signal_emoji(signal: str) -> str:
    return {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡", "WATCH": "⚪"}.get(signal, "⚪")
