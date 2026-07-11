"""determine_signal の重みパラメータ化のテスト"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.technical.signals import (
    add_all_indicators,
    determine_signal,
    DEFAULT_WEIGHTS,
    SIGNAL_SELL,
    SIGNAL_WATCH,
)


def _df_from_closes(closes):
    idx = pd.date_range("2026-01-01", periods=len(closes), freq="B")
    df = pd.DataFrame({"Close": closes, "Volume": [1_000_000] * len(closes)}, index=idx)
    return add_all_indicators(df)


def _fresh_dead_cross_df():
    # 緩やかな上昇後に直近2日で下落 → 最終日にSMA5がSMA20を下抜け（デッドクロス発生）
    closes = list(np.linspace(118, 122, 40)) + list(np.linspace(122, 128, 18)) + [122, 114]
    return _df_from_closes(closes)


class TestWeightsParameterization:
    def test_none_and_empty_and_default_weights_are_identical(self):
        df = _fresh_dead_cross_df()
        r_none = determine_signal(df)
        r_empty = determine_signal(df, weights={})
        r_default = determine_signal(df, weights=dict(DEFAULT_WEIGHTS))
        assert r_none["signal"] == r_empty["signal"] == r_default["signal"]
        assert r_none["strength"] == r_empty["strength"] == r_default["strength"]

    def test_partial_override_keeps_other_defaults(self):
        df = _fresh_dead_cross_df()
        # SELL側と無関係なBUY側の重みだけ変えてもSELL判定は不変
        r = determine_signal(df, weights={"gc_new": 5})
        assert r["signal"] == determine_signal(df)["signal"]

    def test_sell_threshold_override(self):
        df = _fresh_dead_cross_df()
        assert determine_signal(df)["signal"] == SIGNAL_SELL
        r = determine_signal(df, weights={"sell_threshold": 99})
        assert r["signal"] == SIGNAL_WATCH

    def test_zero_buy_weights_prevent_buy(self):
        # 全BUY側重みを0にすれば、どんな強気データでもBUYにならない
        closes = list(np.linspace(130, 100, 40)) + list(np.linspace(100, 125, 20))
        df = _df_from_closes(closes)
        zero_buy = {
            "gc_new": 0, "gc_hold": 0, "rsi_reversal": 0, "rsi_zone": 0,
            "macd_cross": 0, "macd_zone": 0, "bb_break": 0,
            "volume_confirm": 0, "pattern_scale": 0.0,
        }
        r = determine_signal(df, weights=zero_buy)
        assert r["signal"] != "BUY"

    def test_contrarian_components_disabled_by_default(self):
        # 2026-07のパネル分析で方向逆転が判明した逆張り成分はデフォルト0
        assert DEFAULT_WEIGHTS["rsi_reversal"] == 0
        assert DEFAULT_WEIGHTS["rsi_zone"] == 0
        assert DEFAULT_WEIGHTS["bb_break"] == 0
        assert DEFAULT_WEIGHTS["sell_threshold"] == 4

    def test_rsi_oversold_does_not_add_buy_score(self):
        # 急落でRSI売られすぎ+BB下限ブレイクの状態を作る（旧仕様なら買い加点された状況）
        closes = list(np.linspace(120, 122, 40)) + [121, 118, 112, 105, 99, 95]
        df = _df_from_closes(closes)
        rsi = df["rsi14"].iloc[-1]
        assert rsi < 35, f"前提: RSI売られすぎ圏のはず (rsi={rsi})"
        default = determine_signal(df)
        legacy = determine_signal(df, weights={"rsi_reversal": 2, "rsi_zone": 1, "bb_break": 1})
        # デフォルトでは逆張り加点がないため、買いスコア（=BUY強度）は旧仕様以下
        assert default["signal"] != "BUY"
        assert legacy["strength"] >= default["strength"]

    def test_disabled_components_not_in_reasons(self):
        # 重み0の条件は成立していても判定理由に載らない（理由欄とロジックの整合性）
        closes = list(np.linspace(120, 122, 40)) + [121, 118, 112, 105, 99, 95]
        df = _df_from_closes(closes)
        assert df["rsi14"].iloc[-1] < 35
        assert df["Close"].iloc[-1] < df["bb_lower"].iloc[-1]
        reasons = " / ".join(determine_signal(df)["reasons"])
        assert "RSI" not in reasons
        assert "ボリンジャー" not in reasons
        # 重みを復活させれば理由にも載る
        legacy = determine_signal(df, weights={"rsi_reversal": 2, "rsi_zone": 1, "bb_break": 1})
        legacy_reasons = " / ".join(legacy["reasons"])
        assert "RSI" in legacy_reasons
        assert "ボリンジャー" in legacy_reasons

    def test_pattern_scale_zero_removes_pattern_reasons(self):
        closes = list(np.linspace(130, 100, 40)) + list(np.linspace(100, 125, 30))
        df = _df_from_closes(closes)
        with_pat = determine_signal(df)
        without = determine_signal(df, weights={"pattern_scale": 0.0})
        assert not any("[パターン]" in r for r in without["reasons"])
        # デフォルトでパターンが検出されている前提の確認（検出されない形状なら意味がないため）
        if any("[パターン]" in r for r in with_pat["reasons"]):
            assert with_pat["strength"] >= without["strength"]

    def test_pattern_scale_scales_strength(self):
        # pattern_scale を上げるとBUY/SELLどちらかのスコアが単調に増える（strengthで観測）
        closes = list(np.linspace(130, 100, 40)) + list(np.linspace(100, 125, 20))
        df = _df_from_closes(closes)
        base = determine_signal(df)
        boosted = determine_signal(df, weights={"pattern_scale": 3.0})
        assert boosted["strength"] >= base["strength"]
