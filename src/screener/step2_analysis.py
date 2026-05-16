"""
Step2: 精緻なモート・成長性分析
Desktop/日本株分析 のロジックを統合した2段階フィルタ + スコアリング

【フィルタ構成】
  2-A: 年次EPS成長 ≥ 25%（直近3期連続）
  2-B: 四半期EPS成長 ≥ 25%（単調増加）
  2-C: 四半期売上高成長（3四半期連続プラス OR 最新25%以上）
  2-D: ROE > 15%（J-Quants 財務諸表から計算）
  2-E: FCFプラス継続（直近2期）
  2-F: ネット有利子負債/EBITDA ≤ 3.0x
  → スコアリングで上位20銘柄を選定
  → 分類: 全条件銘柄 / EPS条件銘柄
"""
from typing import Optional
import pandas as pd
import numpy as np

from src.utils.logger import get_logger

logger = get_logger("step2_analysis")

DEFAULT_WEIGHTS = {
    "roe": 0.25,
    "revenue_cagr": 0.20,
    "fcf_quality": 0.20,
    "net_debt_ebitda": 0.15,
    "operating_margin": 0.10,
    "payout_ratio": 0.10,
}

# 銘柄分類ラベル
LABEL_ALL_CONDITIONS = "全条件"
LABEL_EPS_ONLY = "EPS条件のみ"


# ============================================================
# 2-A: 年次EPS成長フィルタ
# ============================================================

def filter_eps_annual(eps_series_map: dict[str, dict], min_growth: float = 0.25) -> set[str]:
    """
    直近3期のEPSがすべてプラス かつ 各期成長率が min_growth 以上の銘柄コードを返す。
    eps_series_map: {ticker: {"annual": [...], "quarterly": [...]}}
    """
    passed = set()
    for ticker, series in eps_series_map.items():
        annual = series.get("annual", [])
        # 最低3期分のデータが必要
        valid = [a for a in annual if a.get("eps") is not None]
        if len(valid) < 3:
            continue

        recent3 = valid[:3]
        eps_vals = [r["eps"] for r in recent3]

        # 全てプラス
        if min(eps_vals) <= 0:
            continue

        # 成長率計算（最新 / 1期前 - 1）
        # recent3[0] = 最新, recent3[1] = 1年前, recent3[2] = 2年前
        growth_rates = []
        for i in range(len(recent3) - 1):
            prev = recent3[i + 1]["eps"]
            curr = recent3[i]["eps"]
            if prev and prev > 0:
                growth_rates.append((curr - prev) / prev)
            else:
                growth_rates.append(None)

        valid_rates = [g for g in growth_rates if g is not None]
        if not valid_rates:
            continue

        if min(valid_rates) >= min_growth:
            passed.add(ticker)

    logger.debug(f"  年次EPSフィルタ通過: {len(passed)}件")
    return passed


# ============================================================
# 2-B: 四半期EPS成長フィルタ（単調性チェック付き）
# ============================================================

def filter_eps_quarterly(eps_series_map: dict[str, dict], min_growth: float = 0.25) -> set[str]:
    """
    直近3四半期のEPSがすべてプラス かつ 各四半期成長率が min_growth 以上
    かつ EPS成長が単調増加（加速または横ばい）の銘柄コードを返す。

    単調性チェック:
      - EPS成長差分（当期EPS - 前期EPS）の時系列が降順でないこと
      - Desktop/日本株分析 の filter_eps_quarterly_stocks() ロジックに準拠
    """
    passed = set()
    for ticker, series in eps_series_map.items():
        quarterly = series.get("quarterly", [])
        valid = [q for q in quarterly if q.get("eps") is not None]

        # 直近3四半期（同年度比較のため、1年前の同四半期と比較する必要がある）
        # yoy比較: 直近3四半期と1年前の対応する四半期を比較
        if len(valid) < 4:
            continue

        recent3 = valid[:3]   # 直近3四半期
        older = valid[3:]     # それより古い四半期（yoy比較用）

        eps_vals = [r["eps"] for r in recent3]
        if min(eps_vals) <= 0:
            continue

        # yoy成長率計算（同じ期タイプで1年前と比較）
        growth_by_period = {}
        for q in recent3:
            pt = q.get("period_type")
            yoy = next((o for o in older if o.get("period_type") == pt), None)
            if yoy and yoy["eps"] and yoy["eps"] > 0:
                g = (q["eps"] - yoy["eps"]) / abs(yoy["eps"])
                growth_by_period[pt] = {"growth": g, "eps": q["eps"], "eps_diff": q["eps"] - yoy["eps"]}

        if len(growth_by_period) < 2:
            continue

        growth_vals = [v["growth"] for v in growth_by_period.values()]
        if min(growth_vals) < min_growth:
            continue

        # 単調性チェック: EPS成長差分の順序確認
        # Desktop/日本株分析 では四半期順に並べ、成長差分が単調増加かどうかを確認
        diffs = [v["eps_diff"] for v in growth_by_period.values()]
        is_monotone = all(diffs[i] <= diffs[i + 1] for i in range(len(diffs) - 1)) or \
                      all(diffs[i] >= diffs[i + 1] for i in range(len(diffs) - 1))
        if is_monotone:
            passed.add(ticker)

    logger.debug(f"  四半期EPSフィルタ通過: {len(passed)}件")
    return passed


# ============================================================
# 2-C: 四半期売上高フィルタ
# ============================================================

def filter_netsales_quarterly(
    eps_series_map: dict[str, dict],
    min_growth_latest: float = 0.25,
) -> set[str]:
    """
    以下のいずれかを満たす銘柄を返す（OR条件）:
    (A) 直近3四半期の売上高yoy成長率がすべてプラス
    (B) 直近四半期の売上高yoy成長率が min_growth_latest 以上
    """
    passed = set()
    for ticker, series in eps_series_map.items():
        quarterly = series.get("quarterly", [])
        valid = [q for q in quarterly if q.get("net_sales") is not None]

        if len(valid) < 4:
            continue

        recent3 = valid[:3]
        older = valid[3:]

        # yoy成長率計算
        yoy_growths = []
        for q in recent3:
            pt = q.get("period_type")
            yoy = next((o for o in older if o.get("period_type") == pt), None)
            if yoy and yoy["net_sales"] and yoy["net_sales"] > 0:
                g = (q["net_sales"] - yoy["net_sales"]) / yoy["net_sales"]
                yoy_growths.append(g)

        if not yoy_growths:
            continue

        # (A) 全3四半期プラス
        if len(yoy_growths) >= 3 and all(g > 0 for g in yoy_growths):
            passed.add(ticker)
            continue

        # (B) 直近四半期が min_growth_latest 以上
        if yoy_growths[0] >= min_growth_latest:
            passed.add(ticker)

    logger.debug(f"  四半期売上高フィルタ通過: {len(passed)}件")
    return passed


# ============================================================
# 2-D: ROEフィルタ
# ============================================================

def filter_roe(eps_series_map: dict[str, dict], min_roe: float = 0.15) -> set[str]:
    """直近1年のROEが min_roe 以上の銘柄を返す"""
    passed = set()
    for ticker, series in eps_series_map.items():
        annual = series.get("annual", [])
        if not annual:
            continue
        roe = annual[0].get("roe")
        if roe is not None and roe >= min_roe:
            passed.add(ticker)
    logger.debug(f"  ROEフィルタ通過: {len(passed)}件")
    return passed


# ============================================================
# Step2 メイン実行
# ============================================================

def apply_step2_analysis(
    detailed_fins_list: list[dict],
    eps_series_map: dict[str, dict] = None,
    min_roe: float = 0.15,
    min_eps_annual_growth: float = 0.25,
    min_eps_quarterly_growth: float = 0.25,
    min_revenue_growth_latest: float = 0.25,
    min_fcf_positive_years: int = 2,
    min_cf_quality: float = 0.80,
    max_net_debt_ebitda: float = 3.0,
    max_payout_ratio: float = 0.70,
    top_n: int = 20,
    weights: dict = None,
) -> pd.DataFrame:
    """
    精緻なファンダメンタルズ分析を行い、スコアリングで上位銘柄を返す。

    eps_series_map が提供されない場合は EPS/売上条件をスキップし、
    yfinanceベースの指標のみでフィルタリングする（後方互換）。

    銘柄分類:
      - "全条件": EPS・売上・ROE・FCF・財務健全性すべてを満たす
      - "EPS条件のみ": 年次EPS・四半期EPSは満たすが、他条件は未達
    """
    df = pd.DataFrame(detailed_fins_list)
    original_count = len(df)
    logger.info(f"Step2開始: {original_count}銘柄")

    # --- J-Quants EPS/売上フィルタ（データがある場合のみ）---
    tickers = df["ticker"].tolist()
    has_jquants = eps_series_map is not None and len(eps_series_map) > 0

    if has_jquants:
        # EPS時系列は対応するtickerのみ抽出
        series_for_tickers = {t: eps_series_map.get(t, {"annual": [], "quarterly": []}) for t in tickers}

        eps_annual_set = filter_eps_annual(series_for_tickers, min_eps_annual_growth)
        eps_quarterly_set = filter_eps_quarterly(series_for_tickers, min_eps_quarterly_growth)
        netsales_set = filter_netsales_quarterly(series_for_tickers, min_revenue_growth_latest)
        roe_jq_set = filter_roe(series_for_tickers, min_roe)

        eps_only_set = (eps_annual_set & eps_quarterly_set) - (netsales_set & roe_jq_set)
        all_cond_set = eps_annual_set & eps_quarterly_set & netsales_set & roe_jq_set

        logger.info(
            f"  J-Quantsフィルタ結果: 年次EPS={len(eps_annual_set)}, 四半期EPS={len(eps_quarterly_set)}, "
            f"売上={len(netsales_set)}, ROE={len(roe_jq_set)}"
        )
        logger.info(f"  全条件: {len(all_cond_set)}件 / EPS条件のみ: {len(eps_only_set)}件")

        # 全条件 + EPS条件のみ を対象に絞る
        target_tickers = all_cond_set | eps_only_set
        df = df[df["ticker"].isin(target_tickers)].copy()
        df["classification"] = df["ticker"].apply(
            lambda t: LABEL_ALL_CONDITIONS if t in all_cond_set else LABEL_EPS_ONLY
        )
    else:
        logger.info("  J-Quants EPS/売上データなし: yfinanceベースフィルタのみ適用")
        df["classification"] = LABEL_EPS_ONLY

    if df.empty:
        logger.warning("Step2: EPS/売上フィルタ後の銘柄が0件です。")
        return pd.DataFrame()

    # --- yfinanceベースのハードフィルタ ---
    passed = df.copy()

    # ROE（yfinanceベース補完）
    before = len(passed)
    if not has_jquants:
        roe_mask = passed["roe"].isna() | (passed["roe"] >= min_roe)
        passed = passed[roe_mask]
        logger.info(f"  ROEフィルタ(>={min_roe:.0%}): {before} → {len(passed)}件")

    # FCFプラス継続年数
    before = len(passed)
    fcf_mask = passed["fcf_positive_years"].isna() | (passed["fcf_positive_years"] >= min_fcf_positive_years)
    passed = passed[fcf_mask]
    logger.info(f"  FCFフィルタ(直近{min_fcf_positive_years}期連続+): {before} → {len(passed)}件")

    # ネット有利子負債/EBITDA
    before = len(passed)
    nd_mask = passed["net_debt_ebitda"].isna() | (passed["net_debt_ebitda"] <= max_net_debt_ebitda)
    passed = passed[nd_mask]
    logger.info(f"  ネット有利子負債/EBITDAフィルタ(≤{max_net_debt_ebitda}x): {before} → {len(passed)}件")

    if passed.empty:
        logger.warning("Step2: フィルタ後の銘柄が0件です。閾値を緩めることを検討してください。")
        return pd.DataFrame()

    # --- スコアリング ---
    w = weights or DEFAULT_WEIGHTS
    passed = _score_stocks(passed, w)

    # 全条件銘柄を優先し、その後EPS条件のみ銘柄を追加
    all_cond_df = passed[passed.get("classification", pd.Series()) == LABEL_ALL_CONDITIONS].sort_values("total_score", ascending=False)
    eps_only_df = passed[passed.get("classification", pd.Series()) != LABEL_ALL_CONDITIONS].sort_values("total_score", ascending=False)
    result = pd.concat([all_cond_df, eps_only_df], ignore_index=True).head(top_n)

    logger.info(
        f"Step2完了: {original_count}銘柄 → 上位{len(result)}銘柄を選定 "
        f"（全条件:{len(all_cond_df)}件, EPS条件のみ:{len(eps_only_df)}件）"
    )
    return result.reset_index(drop=True)


def _score_stocks(df: pd.DataFrame, weights: dict) -> pd.DataFrame:
    df = df.copy()
    df["score_roe"] = _normalize(df["roe"], lo=0.0, hi=0.30)
    df["score_cagr"] = _normalize(df["revenue_cagr"], lo=0.0, hi=0.20)
    df["score_cf_quality"] = _normalize(df["cf_quality"], lo=0.0, hi=2.0)
    df["score_net_debt"] = _normalize(-df["net_debt_ebitda"].fillna(5), lo=-5, hi=0)
    df["score_margin"] = _normalize(df["operating_margins"], lo=0.0, hi=0.25)
    df["score_payout"] = _normalize(-df["payout_ratio"].fillna(1.0), lo=-1.0, hi=0)

    df["total_score"] = (
        df["score_roe"].fillna(0) * weights.get("roe", 0)
        + df["score_cagr"].fillna(0) * weights.get("revenue_cagr", 0)
        + df["score_cf_quality"].fillna(0) * weights.get("fcf_quality", 0)
        + df["score_net_debt"].fillna(0) * weights.get("net_debt_ebitda", 0)
        + df["score_margin"].fillna(0) * weights.get("operating_margin", 0)
        + df["score_payout"].fillna(0) * weights.get("payout_ratio", 0)
    ) * 10
    return df


def _normalize(series: pd.Series, lo: float, hi: float) -> pd.Series:
    clipped = series.clip(lower=lo, upper=hi)
    if hi == lo:
        return pd.Series(5.0, index=series.index)
    return (clipped - lo) / (hi - lo) * 10


def format_step2_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "候補銘柄なし"

    cols = {
        "ticker": "銘柄コード",
        "name": "銘柄名",
        "sector": "セクター",
        "classification": "分類",
        "total_score": "総合スコア",
        "roe": "ROE",
        "revenue_cagr": "売上CAGR",
        "net_debt_ebitda": "純負債/EBITDA",
        "operating_margins": "営業利益率",
    }
    display = df[[c for c in cols if c in df.columns]].copy()
    display = display.rename(columns=cols)

    for col in ["ROE", "売上CAGR", "営業利益率"]:
        if col in display.columns:
            display[col] = display[col].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "N/A")
    if "総合スコア" in display.columns:
        display["総合スコア"] = display["総合スコア"].apply(lambda x: f"{x:.1f}" if pd.notna(x) else "N/A")
    if "純負債/EBITDA" in display.columns:
        display["純負債/EBITDA"] = display["純負債/EBITDA"].apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "N/A")

    return display.to_markdown(index=False)
