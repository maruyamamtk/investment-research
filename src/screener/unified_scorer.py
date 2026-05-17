"""
統合スコアラー: 13次元重み付きスコアリング（REQUIREMENTS.md §3.1）

段階1（速報スコア）: yfinance basic info のみで5次元計算 → 上位200〜400社に絞り込み
段階2（精緻スコア）: J-Quants + yfinance詳細で残り8次元計算 → 最終順位決定
"""
import math
from typing import Optional

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("unified_scorer")


MISSING_SCORE = 5.0      # データ欠損時の代替スコア（0〜10の中間値）
MISSING_THRESHOLD = 4   # これ以上の次元が欠損なら "* データ欠損あり" を注記

# 全13次元の重み（合計 = 1.0 = 100%）
WEIGHTS: dict[str, float] = {
    # --- 段階1: yfinance basic info のみ ---
    "operating_margin":   0.07,   # 営業利益率
    "equity_ratio":       0.05,   # 自己資本比率
    "peg_ratio":          0.10,   # PEG比率（PER ÷ 売上成長率%）
    "market_cap":         0.03,   # 時価総額
    "payout_ratio":       0.02,   # 配当性向
    # --- 段階2: J-Quants + yfinance詳細 ---
    "eps_annual_growth":       0.13,   # 年次EPS成長率
    "eps_quarterly_growth":    0.12,   # 四半期EPS成長率
    "revenue_annual_growth":   0.08,   # 年次売上高成長率
    "revenue_quarterly_growth":0.07,   # 四半期売上高成長率
    "roe":                     0.10,   # ROE
    "cf_quality":              0.08,   # CF品質（OCF / 純利益）
    "fcf_years":               0.05,   # FCF継続年数
    "net_debt_ebitda":         0.10,   # 純負債 / EBITDA
}

assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9, "WEIGHTS の合計が 1.0 になっていません"


# ============================================================
# 個別次元スコア関数（0〜10点、欠損は MISSING_SCORE を返す）
# ============================================================

def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _linear_score(val: Optional[float], lo: float, hi: float, inverse: bool = False) -> float:
    """lo〜hi の範囲を 0〜10 に線形マッピング（inverse=True で逆順）。"""
    if val is None or not math.isfinite(val):
        return MISSING_SCORE
    if inverse:
        # 大きいほど悪い指標（PEG・配当性向）用: lo→10点（最良）, hi→0点（最悪）
        score = (hi - val) / (hi - lo) * 10.0
    else:
        score = (val - lo) / (hi - lo) * 10.0
    return round(_clamp(score, 0.0, 10.0), 4)


def score_operating_margin(val: Optional[float]) -> float:
    """営業利益率: ≤0%→0点, ≥25%→10点"""
    return _linear_score(val, lo=0.0, hi=0.25)


def score_equity_ratio(val: Optional[float]) -> float:
    """自己資本比率: ≤10%→0点, ≥50%→10点"""
    return _linear_score(val, lo=0.10, hi=0.50)


def score_peg_ratio(val: Optional[float]) -> float:
    """PEG比率: ≤0.5→10点, ≥5.0→0点（小さいほど高得点）"""
    return _linear_score(val, lo=0.5, hi=5.0, inverse=True)


def score_market_cap(val: Optional[float]) -> float:
    """時価総額: ≤100億JPY→0点, ≥1兆JPY→10点（対数スケール）。"""
    if val is None or val <= 0 or not math.isfinite(val):
        return MISSING_SCORE
    LOG_LO = math.log10(10_000_000_000)   # log10(100億) = 10
    LOG_HI = math.log10(1_000_000_000_000)  # log10(1兆)  = 12
    score = (math.log10(val) - LOG_LO) / (LOG_HI - LOG_LO) * 10.0
    return round(_clamp(score, 0.0, 10.0), 4)


def score_payout_ratio(val: Optional[float]) -> float:
    """配当性向: 0%→10点, ≥70%→0点（低いほど高得点）。"""
    return _linear_score(val, lo=0.0, hi=0.70, inverse=True)


# ============================================================
# ヘルパー
# ============================================================

def _calc_equity_ratio(info: dict) -> Optional[float]:
    """自己資本比率 = total_equity / total_assets を計算する。"""
    equity = info.get("total_equity")
    assets = info.get("total_assets")
    if equity is None or assets is None or assets == 0:
        return None
    try:
        e = float(equity)
        a = float(assets)
        return e / a if a > 0 else None
    except (TypeError, ValueError):
        return None


def _calc_peg(info: dict) -> Optional[float]:
    """PEG = PER ÷ 売上成長率（%）。revenue_growth は小数（例: 0.15 = 15%）。"""
    pe = info.get("pe_ratio")
    rev_growth = info.get("revenue_growth")
    if pe is None or rev_growth is None:
        return None
    try:
        pe = float(pe)
        rev_growth = float(rev_growth)
        if pe <= 0 or rev_growth <= 0:
            return None
        return pe / (rev_growth * 100.0)
    except (TypeError, ValueError):
        return None


# ============================================================
# 段階1: 速報スコア計算
# ============================================================

def calculate_stage1_scores(basic_info_list: list[dict]) -> pd.DataFrame:
    """
    段階1: yfinance basic info から5次元の速報スコアを計算する。

    Args:
        basic_info_list: yfinance_client.get_basic_info_batch() の返り値

    Returns:
        pd.DataFrame: 各銘柄に stage1_score 列を付与した DataFrame（降順ソート済み）
    """
    records = []
    missing_logged: set[str] = set()

    for info in basic_info_list:
        ticker = info.get("ticker", "")

        equity_ratio = _calc_equity_ratio(info)
        peg = _calc_peg(info)

        s_op_margin  = score_operating_margin(info.get("operating_margins"))
        s_eq_ratio   = score_equity_ratio(equity_ratio)
        s_peg        = score_peg_ratio(peg)
        s_mktcap     = score_market_cap(info.get("market_cap"))
        s_payout     = score_payout_ratio(info.get("payout_ratio"))

        # 欠損カウントとログ（初回のみ）
        dim_vals = {
            "operating_margins": info.get("operating_margins"),
            "equity_ratio": equity_ratio,
            "peg_ratio": peg,
            "market_cap": info.get("market_cap"),
            "payout_ratio": info.get("payout_ratio"),
        }
        missing = [k for k, v in dim_vals.items() if v is None]
        s1_missing_count = len(missing)
        if missing and ticker not in missing_logged:
            logger.debug(f"{ticker}: 段階1欠損次元（MISSING_SCORE={MISSING_SCORE}で補完）= {missing}")
            missing_logged.add(ticker)

        # 段階1の重み付き合算（5次元のみ）
        stage1_raw = (
            s_op_margin * WEIGHTS["operating_margin"]
            + s_eq_ratio * WEIGHTS["equity_ratio"]
            + s_peg * WEIGHTS["peg_ratio"]
            + s_mktcap * WEIGHTS["market_cap"]
            + s_payout * WEIGHTS["payout_ratio"]
        )

        records.append({
            **info,
            "equity_ratio": equity_ratio,
            "peg_calc": peg,
            "s1_operating_margin": s_op_margin,
            "s1_equity_ratio":     s_eq_ratio,
            "s1_peg":              s_peg,
            "s1_market_cap":       s_mktcap,
            "s1_payout_ratio":     s_payout,
            "stage1_raw":          round(stage1_raw, 5),
            "s1_missing_count":    s1_missing_count,
        })

    df = pd.DataFrame(records)
    if df.empty:
        return df

    df = df.sort_values("stage1_raw", ascending=False).reset_index(drop=True)
    logger.info(f"段階1スコア計算完了: {len(df)}銘柄")
    return df


def filter_stage1_candidates(
    df: pd.DataFrame,
    top_n_min: int = 200,
    top_n_max: int = 400,
) -> pd.DataFrame:
    """
    段階1スコア降順で上位 top_n_min〜top_n_max 社を段階2の入力として返す。

    全銘柄数が少ない場合（dry-run など）は全件を返す。
    """
    n = min(top_n_max, max(top_n_min, len(df) // 4))
    n = min(n, len(df))
    result = df.head(n).reset_index(drop=True)
    logger.info(f"段階1絞り込み: {len(df)}銘柄 → {len(result)}銘柄（top {n}）")
    return result


# ============================================================
# 段階2: 個別次元スコア関数（J-Quants + yfinance詳細）
# ============================================================

def score_eps_annual_growth(val: Optional[float]) -> float:
    """年次EPS成長率: ≤0%→0点、≥30%→10点"""
    return _linear_score(val, lo=0.0, hi=0.30)


def score_eps_quarterly_growth(val: Optional[float], is_monotone: bool = False) -> float:
    """四半期EPS成長率: ≤0%→0点、≥25%→9点（単調増加で+1点ボーナス、最大10点）"""
    if val is None or not math.isfinite(val):
        return MISSING_SCORE
    if val <= 0:
        return 0.0
    base = round(_clamp((val / 0.25) * 9.0, 0.0, 9.0), 4)
    if is_monotone:
        return min(10.0, round(base + 1.0, 4))
    return base


def score_revenue_annual_growth(val: Optional[float]) -> float:
    """年次売上高成長率: ≤0%→0点、≥20%→10点"""
    return _linear_score(val, lo=0.0, hi=0.20)


def score_revenue_quarterly_growth(val: Optional[float]) -> float:
    """四半期売上高成長率: ≤0%→0点、≥25%→10点"""
    return _linear_score(val, lo=0.0, hi=0.25)


def score_roe(val: Optional[float]) -> float:
    """ROE: ≤0%→0点、≥30%→10点"""
    return _linear_score(val, lo=0.0, hi=0.30)


def score_cf_quality(val: Optional[float]) -> float:
    """CF品質（OCF/純利益）: ≤0→0点、≥2.0→10点"""
    return _linear_score(val, lo=0.0, hi=2.0)


def score_fcf_years(val: Optional[float]) -> float:
    """FCF継続年数: 0年→0点、3年→10点"""
    if val is None or not math.isfinite(val):
        return MISSING_SCORE
    return round(_clamp((val / 3.0) * 10.0, 0.0, 10.0), 4)


def score_net_debt_ebitda(val: Optional[float]) -> float:
    """純負債/EBITDA: ≤0x→10点、≥5x→0点（小さいほど高得点）"""
    return _linear_score(val, lo=0.0, hi=5.0, inverse=True)


# ============================================================
# 段階2: ヘルパー（J-Quantsデータからの指標計算）
# ============================================================

def _calc_eps_annual_growth(annual: list[dict]) -> Optional[float]:
    """直近3期の平均EPS yoy成長率を計算する。"""
    valid = [a for a in annual if a.get("eps") is not None]
    if len(valid) < 2:
        return None
    growth_rates = []
    for i in range(min(3, len(valid) - 1)):
        curr = valid[i]["eps"]
        prev = valid[i + 1]["eps"]
        if prev is not None and prev != 0:
            growth_rates.append((curr - prev) / abs(prev))
    return sum(growth_rates) / len(growth_rates) if growth_rates else None


def _calc_eps_quarterly_growth(quarterly: list[dict]) -> tuple[Optional[float], bool]:
    """最新四半期EPS yoy成長率と単調増加フラグを返す。

    単調増加: 直近3四半期の yoy 成長率が古い→新しい順に非減少。
    Returns: (growth_rate, is_monotone)
    """
    valid = [q for q in quarterly if q.get("eps") is not None]
    if len(valid) < 2:
        return None, False

    # 最新四半期のyoy成長率
    latest = valid[0]
    period_type = latest.get("period_type")
    yoy_match = next((q for q in valid[1:] if q.get("period_type") == period_type), None)
    growth: Optional[float] = None
    if yoy_match and yoy_match["eps"] not in (None, 0):
        growth = (latest["eps"] - yoy_match["eps"]) / abs(yoy_match["eps"])

    # 単調増加チェック: 直近3四半期の yoy 成長率が加速傾向か
    is_monotone = False
    if len(valid) >= 4:
        recent3 = valid[:3]
        older = valid[3:]
        growths = []
        for q in recent3:
            pt = q.get("period_type")
            yoy_q = next((o for o in older if o.get("period_type") == pt), None)
            if yoy_q and yoy_q["eps"] not in (None, 0):
                g = (q["eps"] - yoy_q["eps"]) / abs(yoy_q["eps"])
                growths.append(g)
        # growths[0]=最新, growths[-1]=最古 → 最新 >= 直前 >= 最古 で単調増加
        if len(growths) >= 2:
            is_monotone = all(growths[i] >= growths[i + 1] for i in range(len(growths) - 1))

    return growth, is_monotone


def _calc_revenue_annual_growth(annual: list[dict]) -> Optional[float]:
    """直近2期の平均売上高 yoy 成長率を計算する。"""
    valid = [a for a in annual if a.get("net_sales") is not None and a["net_sales"] > 0]
    if len(valid) < 2:
        return None
    growth_rates = []
    for i in range(min(2, len(valid) - 1)):
        curr = valid[i]["net_sales"]
        prev = valid[i + 1]["net_sales"]
        if prev and prev > 0:
            growth_rates.append((curr - prev) / prev)
    return sum(growth_rates) / len(growth_rates) if growth_rates else None


def _calc_revenue_quarterly_growth(quarterly: list[dict]) -> Optional[float]:
    """最新四半期売上高 yoy 成長率を計算する。"""
    valid = [q for q in quarterly if q.get("net_sales") is not None and q["net_sales"] > 0]
    if len(valid) < 2:
        return None
    latest = valid[0]
    period_type = latest.get("period_type")
    yoy_match = next((q for q in valid[1:] if q.get("period_type") == period_type), None)
    if yoy_match and yoy_match["net_sales"] and yoy_match["net_sales"] > 0:
        return (latest["net_sales"] - yoy_match["net_sales"]) / yoy_match["net_sales"]
    return None


# ============================================================
# 段階2: 精緻スコア計算
# ============================================================

def calculate_stage2_scores(
    stage1_df: pd.DataFrame,
    eps_series_map: dict[str, dict],
    detailed_fins_map: dict[str, dict],
) -> pd.DataFrame:
    """
    段階2: J-Quants財務諸表 + yfinance詳細で8次元の精緻スコアを計算し、
    段階1スコアと合算して最終総合スコア（0〜10点）を確定する。

    Args:
        stage1_df: calculate_stage1_scores() + filter_stage1_candidates() の返り値
        eps_series_map: JQuantsClient.get_statements_batch() の返り値
            {ticker: {"annual": [...], "quarterly": [...]}}
        detailed_fins_map: {ticker: YFinanceClient.get_detailed_financials(ticker)} の辞書

    Returns:
        pd.DataFrame: 段階2スコア列と total_score 列を付与した DataFrame（total_score 降順ソート）
    """
    records = []

    for _, row in stage1_df.iterrows():
        ticker = row["ticker"]
        eps_data = eps_series_map.get(ticker, {"annual": [], "quarterly": []})
        fins = detailed_fins_map.get(ticker, {})

        annual = eps_data.get("annual", [])
        quarterly = eps_data.get("quarterly", [])

        # --- 各指標の計算 ---
        eps_annual_growth = _calc_eps_annual_growth(annual)
        eps_qtr_growth, is_monotone = _calc_eps_quarterly_growth(quarterly)
        rev_annual_growth = _calc_revenue_annual_growth(annual)
        rev_qtr_growth = _calc_revenue_quarterly_growth(quarterly)

        # ROE: J-Quants優先、取得不可の場合はyfinance補完
        roe = annual[0].get("roe") if annual else None
        if roe is None:
            roe = fins.get("roe")

        cf_quality = fins.get("cf_quality")
        fcf_years = fins.get("fcf_positive_years")
        net_debt_ebitda = fins.get("net_debt_ebitda")

        # 欠損カウントとログ
        s2_dim_vals = {
            "eps_annual_growth":       eps_annual_growth,
            "eps_quarterly_growth":    eps_qtr_growth,
            "revenue_annual_growth":   rev_annual_growth,
            "revenue_quarterly_growth":rev_qtr_growth,
            "roe":                     roe,
            "cf_quality":              cf_quality,
            "fcf_positive_years":      fcf_years,
            "net_debt_ebitda":         net_debt_ebitda,
        }
        s2_missing = [k for k, v in s2_dim_vals.items() if v is None]
        s2_missing_count = len(s2_missing)
        if s2_missing:
            logger.debug(f"{ticker}: 段階2欠損次元（MISSING_SCORE={MISSING_SCORE}で補完）= {s2_missing}")

        # --- 段階2スコア計算 ---
        s2_eps_annual = score_eps_annual_growth(eps_annual_growth)
        s2_eps_quarterly = score_eps_quarterly_growth(eps_qtr_growth, is_monotone)
        s2_rev_annual = score_revenue_annual_growth(rev_annual_growth)
        s2_rev_quarterly = score_revenue_quarterly_growth(rev_qtr_growth)
        s2_roe = score_roe(roe)
        s2_cf_quality = score_cf_quality(cf_quality)
        s2_fcf_years = score_fcf_years(fcf_years)
        s2_net_debt = score_net_debt_ebitda(net_debt_ebitda)

        stage2_raw = round(
            s2_eps_annual    * WEIGHTS["eps_annual_growth"]
            + s2_eps_quarterly * WEIGHTS["eps_quarterly_growth"]
            + s2_rev_annual    * WEIGHTS["revenue_annual_growth"]
            + s2_rev_quarterly * WEIGHTS["revenue_quarterly_growth"]
            + s2_roe           * WEIGHTS["roe"]
            + s2_cf_quality    * WEIGHTS["cf_quality"]
            + s2_fcf_years     * WEIGHTS["fcf_years"]
            + s2_net_debt      * WEIGHTS["net_debt_ebitda"],
            5,
        )

        stage1_raw = row.get("stage1_raw", 0.0)
        total_score = round(stage1_raw + stage2_raw, 5)

        records.append({
            **row.to_dict(),
            # 段階2の計算値
            "eps_annual_growth": eps_annual_growth,
            "eps_quarterly_growth": eps_qtr_growth,
            "eps_quarterly_monotone": is_monotone,
            "revenue_annual_growth": rev_annual_growth,
            "revenue_quarterly_growth": rev_qtr_growth,
            "roe": roe,
            "cf_quality": cf_quality,
            "fcf_positive_years": fcf_years,
            "net_debt_ebitda": net_debt_ebitda,
            # 段階2スコア
            "s2_eps_annual": s2_eps_annual,
            "s2_eps_quarterly": s2_eps_quarterly,
            "s2_revenue_annual": s2_rev_annual,
            "s2_revenue_quarterly": s2_rev_quarterly,
            "s2_roe": s2_roe,
            "s2_cf_quality": s2_cf_quality,
            "s2_fcf_years": s2_fcf_years,
            "s2_net_debt_ebitda": s2_net_debt,
            "stage2_raw": stage2_raw,
            "total_score": total_score,
            "s2_missing_count": s2_missing_count,
        })

    df = pd.DataFrame(records)
    if df.empty:
        return df

    df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
    logger.info(
        f"段階2スコア計算完了: {len(df)}銘柄, "
        f"total_score最大={df['total_score'].max():.3f}"
    )
    return df


def select_final_watchlist(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """段階2スコア確定済み DataFrame から上位 top_n 社を選定する。"""
    result = df.head(top_n).reset_index(drop=True)
    logger.info(f"最終ウォッチリスト選定: {len(df)}銘柄 → 上位{len(result)}銘柄")
    return result


# ============================================================
# 総合スコア計算（0〜100点）・上位20社選定
# ============================================================

def calculate_total_score(df: pd.DataFrame, top_n: int = 20) -> pd.DataFrame:
    """
    段階1＋段階2の total_score（0〜10）を 0〜100点にスケーリングして
    total_score_100 列を付与し、スコア降順で上位 top_n 社を返す。

    Args:
        df: calculate_stage2_scores() の返り値（total_score 列を含む）
        top_n: 上位選定数（デフォルト 20）

    Returns:
        pd.DataFrame: total_score_100 列付きの上位 top_n 社（降順ソート済み）
    """
    if df.empty:
        return df

    result = df.copy()
    result["total_score_100"] = (result["total_score"] * 10.0).round(2)

    s1_missing = result.get("s1_missing_count", pd.Series(0, index=result.index))
    s2_missing = result.get("s2_missing_count", pd.Series(0, index=result.index))
    result["total_missing_count"] = (s1_missing + s2_missing).astype(int)
    result["data_quality_note"] = result["total_missing_count"].apply(
        lambda n: "* データ欠損あり" if n >= MISSING_THRESHOLD else ""
    )

    result = result.sort_values("total_score_100", ascending=False).reset_index(drop=True)
    top = result.head(top_n)

    best = top["total_score_100"].max() if not top.empty else 0.0
    missing_any = (top["total_missing_count"] >= MISSING_THRESHOLD).sum()
    logger.info(
        f"総合スコア計算完了: {len(df)}銘柄 → 上位{len(top)}銘柄選定, "
        f"最高スコア={best:.1f}/100, データ欠損あり={missing_any}銘柄"
    )
    return top
