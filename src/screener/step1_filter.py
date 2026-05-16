"""
Step1: 基本財務フィルタ
全プライム市場銘柄（約1,600社）を基本指標で絞り込み（不良銘柄の除外）
"""
from typing import Any

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("step1_filter")


def apply_step1_filter(
    basic_info_list: list[dict],
    min_market_cap: float = 10_000_000_000,
    min_revenue_growth: float = -0.10,
    min_operating_margin: float = 0.0,
    min_pbr: float = 0.0,
    min_equity_ratio: float = 0.10,
) -> pd.DataFrame:
    """
    基本財務フィルタを適用し、通過した銘柄のDataFrameを返す。

    フィルタ条件:
    - 時価総額 >= min_market_cap（デフォルト 100億円）
    - 売上高成長率 >= min_revenue_growth（デフォルト -10%）
    - 営業利益率 > min_operating_margin（デフォルト 0%）
    - PBR > min_pbr（デフォルト 0）
    - 自己資本比率 >= min_equity_ratio（デフォルト 10%）
    """
    df = pd.DataFrame(basic_info_list)
    original_count = len(df)
    logger.info(f"Step1開始: {original_count}銘柄")

    passed = df.copy()

    # --- 時価総額フィルタ ---
    before = len(passed)
    passed = passed[passed["market_cap"].notna() & (passed["market_cap"] >= min_market_cap)]
    logger.info(f"  時価総額フィルタ: {before} → {len(passed)}件（除外 {before - len(passed)}件）")

    # --- 営業利益率フィルタ（赤字除外）---
    before = len(passed)
    margin_mask = passed["operating_margins"].isna() | (passed["operating_margins"] > min_operating_margin)
    passed = passed[margin_mask]
    logger.info(f"  営業利益率フィルタ: {before} → {len(passed)}件（除外 {before - len(passed)}件）")

    # --- PBRフィルタ（債務超過除外）---
    before = len(passed)
    pbr_mask = passed["pbr"].isna() | (passed["pbr"] > min_pbr)
    passed = passed[pbr_mask]
    logger.info(f"  PBRフィルタ: {before} → {len(passed)}件（除外 {before - len(passed)}件）")

    # --- 売上高成長率フィルタ ---
    before = len(passed)
    growth_mask = passed["revenue_growth"].isna() | (passed["revenue_growth"] >= min_revenue_growth)
    passed = passed[growth_mask]
    logger.info(f"  売上高成長率フィルタ: {before} → {len(passed)}件（除外 {before - len(passed)}件）")

    # --- 自己資本比率フィルタ ---
    before = len(passed)
    passed["equity_ratio"] = _calc_equity_ratio(passed)
    eq_mask = passed["equity_ratio"].isna() | (passed["equity_ratio"] >= min_equity_ratio)
    passed = passed[eq_mask]
    logger.info(f"  自己資本比率フィルタ: {before} → {len(passed)}件（除外 {before - len(passed)}件）")

    logger.info(f"Step1完了: {original_count}銘柄 → {len(passed)}銘柄（通過率 {len(passed)/original_count:.1%}）")
    return passed.reset_index(drop=True)


def _calc_equity_ratio(df: pd.DataFrame) -> pd.Series:
    """自己資本比率 = 自己資本 / 総資産"""
    equity = pd.to_numeric(df.get("total_equity", pd.Series(dtype=float)), errors="coerce")
    assets = pd.to_numeric(df.get("total_assets", pd.Series(dtype=float)), errors="coerce")
    ratio = equity / assets
    return ratio.where(assets > 0, other=None)


def filter_summary(df_before: pd.DataFrame, df_after: pd.DataFrame) -> str:
    """Step1フィルタ結果のサマリー文字列を生成"""
    return (
        f"Step1スクリーニング結果: {len(df_before)}銘柄 → {len(df_after)}銘柄\n"
        f"（通過率: {len(df_after)/len(df_before):.1%}）"
    )
