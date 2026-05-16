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

MISSING_SCORE = 5.0  # データ欠損時の代替スコア（0〜10の中間値）

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

# 段階1で使用する次元キー
_STAGE1_KEYS = ("operating_margin", "equity_ratio", "peg_ratio", "market_cap", "payout_ratio")

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
        # lo（最悪）→ 0点、hi（最良）→ 10点  ← 反転なし
        # ここでは「大きいほど悪い」場合: hi〜lo を 0〜10 にマップ
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

        # 欠損ログ（初回のみ）
        dim_vals = {
            "operating_margins": info.get("operating_margins"),
            "equity_ratio": equity_ratio,
            "peg_ratio": peg,
            "market_cap": info.get("market_cap"),
            "payout_ratio": info.get("payout_ratio"),
        }
        missing = [k for k, v in dim_vals.items() if v is None]
        if missing and ticker not in missing_logged:
            logger.debug(f"{ticker}: 欠損次元（MISSING_SCORE={MISSING_SCORE}で補完）= {missing}")
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
