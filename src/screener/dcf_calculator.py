"""
簡易DCFモデル計算モジュール

計算フロー:
  1. WACC推定 (CAPM + 負債コスト)
  2. FCF予測 (過去FCFから成長率推定 → 5年予測)
  3. ターミナルバリュー (Gordon Growth Model)
  4. エンタープライズバリュー割引
  5. 1株当たりフェアバリュー算出
  6. WACC±1% × 成長率±2% の感度分析マトリクス出力
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger("dcf_calculator")

# --- デフォルトパラメータ ---
DEFAULT_RISK_FREE_RATE = 0.015      # 1.5% (日本10年国債利回り想定)
DEFAULT_MARKET_PREMIUM = 0.05       # 5%   (市場リスクプレミアム)
DEFAULT_COST_OF_DEBT = 0.03         # 3%   (借入コスト・フォールバック)
DEFAULT_TAX_RATE = 0.30             # 30%  (法人税率)
DEFAULT_TERMINAL_GROWTH = 0.01      # 1%   (永続成長率)
DEFAULT_PROJECTION_YEARS = 5        # 5年予測
FCF_GROWTH_CAP = (- 0.20, 0.30)    # FCF成長率の許容範囲


# ----------------------------------------------------------------
# WACC 推定
# ----------------------------------------------------------------

def estimate_wacc(
    dcf_data: dict,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    market_premium: float = DEFAULT_MARKET_PREMIUM,
    cost_of_debt: float = DEFAULT_COST_OF_DEBT,
    tax_rate: float = DEFAULT_TAX_RATE,
) -> float:
    """WACC (加重平均資本コスト) を推定する。

    Ke = Rf + β × (Rm - Rf)  [CAPM]
    WACC = (E / (E+D)) × Ke + (D / (E+D)) × Kd × (1 - t)
    """
    beta = dcf_data.get("beta") or 1.0
    market_cap = dcf_data.get("market_cap") or 0.0
    total_debt = dcf_data.get("total_debt") or 0.0

    cost_of_equity = risk_free_rate + beta * market_premium

    total_capital = market_cap + total_debt
    if total_capital <= 0:
        return cost_of_equity

    equity_weight = market_cap / total_capital
    debt_weight = total_debt / total_capital
    after_tax_cost_of_debt = cost_of_debt * (1 - tax_rate)

    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt
    return max(wacc, 0.01)   # 最低1%をフロアとする


# ----------------------------------------------------------------
# FCF 成長率推定
# ----------------------------------------------------------------

def estimate_fcf_growth(dcf_data: dict) -> float:
    """過去FCFリストからCAGR成長率を推定する。

    - 3期以上あれば CAGR 計算
    - データ不足・異常値はフォールバックとして revenue_growth を使用
    - 結果は FCF_GROWTH_CAP でクリップ
    """
    fcf_list: list[float] = dcf_data.get("fcf_list") or []
    revenue_growth: Optional[float] = dcf_data.get("revenue_growth")

    growth = None
    if len(fcf_list) >= 2:
        latest = fcf_list[0]
        oldest = fcf_list[min(len(fcf_list) - 1, 2)]   # 最大3期前まで
        n = min(len(fcf_list) - 1, 2)
        if oldest > 0 and latest > 0 and n > 0:
            growth = (latest / oldest) ** (1 / n) - 1

    if growth is None:
        growth = revenue_growth if revenue_growth is not None else 0.05

    return max(FCF_GROWTH_CAP[0], min(FCF_GROWTH_CAP[1], growth))


# ----------------------------------------------------------------
# DCF コア計算
# ----------------------------------------------------------------

def project_fcf(base_fcf: float, growth_rate: float, years: int = DEFAULT_PROJECTION_YEARS) -> list[float]:
    """FCFをgrowth_rateで years 年間予測する（最新年が先頭）。"""
    return [base_fcf * (1 + growth_rate) ** t for t in range(1, years + 1)]


def calculate_terminal_value(last_projected_fcf: float, wacc: float, terminal_growth: float) -> float:
    """Gordon Growth Model によるターミナルバリュー。

    TV = FCF_n × (1 + g) / (WACC - g)
    WACC > g でないと計算不能なため、差が 0.5% 未満の場合は 0.5% にクランプ。
    """
    spread = wacc - terminal_growth
    if spread < 0.005:
        logger.warning(
            f"WACC ({wacc:.2%}) が terminal_growth ({terminal_growth:.2%}) に近すぎます。"
            f"スプレッドを 0.50% にクランプします。TV が過大評価される可能性があります。"
        )
        spread = 0.005
    return last_projected_fcf * (1 + terminal_growth) / spread


def calculate_enterprise_value(
    projected_fcf: list[float],
    terminal_value: float,
    wacc: float,
) -> float:
    """投影FCFとターミナルバリューを現在価値に割引してエンタープライズバリューを算出。"""
    pv_fcf = sum(fcf / (1 + wacc) ** (t + 1) for t, fcf in enumerate(projected_fcf))
    n = len(projected_fcf)
    pv_tv = terminal_value / (1 + wacc) ** n
    return pv_fcf + pv_tv


def calculate_fair_value_per_share(
    enterprise_value: float,
    net_debt: float,
    shares_outstanding: int,
) -> Optional[float]:
    """エンタープライズバリュー → 1株フェアバリュー変換。"""
    if not shares_outstanding or shares_outstanding <= 0:
        return None
    equity_value = enterprise_value - net_debt
    if equity_value <= 0:
        return None
    return equity_value / shares_outstanding


# ----------------------------------------------------------------
# 感度分析
# ----------------------------------------------------------------

def sensitivity_matrix(
    base_fcf: float,
    base_wacc: float,
    base_growth: float,
    terminal_growth: float,
    net_debt: float,
    shares_outstanding: int,
    years: int = DEFAULT_PROJECTION_YEARS,
) -> dict:
    """WACC ±1% × FCF成長率 ±2% の3×3感度分析マトリクスを返す。

    Returns:
        {
            "wacc_labels": [wacc-1%, wacc, wacc+1%],
            "growth_labels": [g-2%, g, g+2%],
            "matrix": [[fair_value for each wacc] for each growth]
        }
    """
    wacc_deltas = [-0.01, 0.0, 0.01]
    growth_deltas = [-0.02, 0.0, 0.02]

    # WACC は terminal_growth + 0.005 以上を保証し、計算上の TV 歪みを防ぐ
    wacc_floor = terminal_growth + 0.005
    wacc_vals = [round(max(base_wacc + d, wacc_floor), 4) for d in wacc_deltas]

    # growth_labels はクランプ後の実際の計算値を使用してラベルと計算を一致させる
    growth_vals = [
        round(max(FCF_GROWTH_CAP[0], min(FCF_GROWTH_CAP[1], base_growth + d)), 4)
        for d in growth_deltas
    ]

    matrix = []
    for g in growth_vals:
        row = []
        for w in wacc_vals:
            proj = project_fcf(base_fcf, g, years)
            tv = calculate_terminal_value(proj[-1], w, terminal_growth)
            ev = calculate_enterprise_value(proj, tv, w)
            fv = calculate_fair_value_per_share(ev, net_debt, shares_outstanding)
            row.append(fv)
        matrix.append(row)

    return {
        "wacc_labels": wacc_vals,
        "growth_labels": growth_vals,
        "matrix": matrix,
    }


# ----------------------------------------------------------------
# Markdown レポート生成
# ----------------------------------------------------------------

def generate_dcf_report(
    target_ticker: str,
    yf_client,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    market_premium: float = DEFAULT_MARKET_PREMIUM,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
) -> str:
    """target_tickerのDCF分析レポート（Markdown）を生成して返す。"""
    logger.info(f"DCF分析開始: {target_ticker}")

    dcf_data = yf_client.get_dcf_data(target_ticker)
    name = dcf_data.get("name", target_ticker)
    current_price = dcf_data.get("current_price")
    shares_outstanding = dcf_data.get("shares_outstanding")
    net_debt = dcf_data.get("net_debt") or 0.0
    latest_fcf = dcf_data.get("latest_fcf")

    now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    header = [
        f"## {name}（{target_ticker}） DCF分析",
        "",
        f"生成日時: {now_str}",
        f"リスクフリーレート: {risk_free_rate * 100:.1f}%  "
        f"| 市場リスクプレミアム: {market_premium * 100:.1f}%  "
        f"| 永続成長率: {terminal_growth * 100:.1f}%",
        "",
    ]

    # FCFが取得できない場合は早期リターン
    if latest_fcf is None or latest_fcf <= 0:
        header += [
            "> ⚠️ FCFデータが取得できないか、直近FCFがマイナスです。",
            "> DCFモデルの算出を中止します（成長企業や赤字企業は適用外）。",
            "",
            "---",
            "",
        ]
        return "\n".join(header)

    if not shares_outstanding:
        header += [
            "> ⚠️ 発行済み株式数が取得できません。DCF算出を中止します。",
            "",
            "---",
            "",
        ]
        return "\n".join(header)

    # --- パラメータ計算 ---
    wacc = estimate_wacc(dcf_data, risk_free_rate, market_premium)
    fcf_growth = estimate_fcf_growth(dcf_data)
    projected = project_fcf(latest_fcf, fcf_growth)
    tv = calculate_terminal_value(projected[-1], wacc, terminal_growth)
    ev = calculate_enterprise_value(projected, tv, wacc)
    fair_value = calculate_fair_value_per_share(ev, net_debt, shares_outstanding)

    # --- 前提条件テーブル ---
    beta = dcf_data.get("beta") or 1.0
    market_cap_oku = (dcf_data.get("market_cap") or 0) / 1e8
    net_debt_oku = net_debt / 1e8
    latest_fcf_oku = latest_fcf / 1e8

    lines = header + [
        "### 前提パラメータ",
        "",
        "| パラメータ | 値 |",
        "|---|---|",
        f"| Beta | {beta:.2f} |",
        f"| WACC | {wacc * 100:.2f}% |",
        f"| FCF成長率（予測期間） | {fcf_growth * 100:.2f}% |",
        f"| 永続成長率 | {terminal_growth * 100:.1f}% |",
        f"| 直近FCF | {latest_fcf_oku:,.1f} 億円 |",
        f"| 時価総額 | {market_cap_oku:,.0f} 億円 |",
        f"| ネット有利子負債 | {net_debt_oku:,.1f} 億円 |",
        f"| 発行済み株式数 | {int(shares_outstanding):,} 株 |",
        "",
    ]

    # --- 5年FCF予測テーブル ---
    lines += [
        "### 5年FCF予測（億円）",
        "",
        "| 予測年 | FCF (億円) | 現在価値 (億円) |",
        "|---|---|---|",
    ]
    for t_idx, fcf in enumerate(projected, 1):
        pv = fcf / (1 + wacc) ** t_idx
        lines.append(f"| {t_idx}年後 | {fcf / 1e8:,.1f} | {pv / 1e8:,.1f} |")

    tv_pv = tv / (1 + wacc) ** len(projected)
    lines += [
        f"| ターミナルバリュー | {tv / 1e8:,.1f} | {tv_pv / 1e8:,.1f} |",
        f"| **エンタープライズバリュー合計** | | **{ev / 1e8:,.1f}** |",
        "",
    ]

    # --- フェアバリューと乖離率 ---
    if fair_value is not None:
        lines += [
            "### フェアバリュー試算",
            "",
            "| 項目 | 値 |",
            "|---|---|",
            f"| フェアバリュー（1株） | **¥{fair_value:,.0f}** |",
        ]
        if current_price and current_price > 0:
            upside = (fair_value - current_price) / current_price
            sign = "▲" if upside >= 0 else "▼"
            lines += [
                f"| 現在株価 | ¥{current_price:,.0f} |",
                f"| 乖離率（上値余地/下値リスク） | {sign} {abs(upside) * 100:.1f}% |",
            ]
        lines.append("")
    else:
        lines += [
            "> ⚠️ エクイティバリューがマイナスのため、フェアバリューを算出できません。",
            "",
        ]

    # --- 感度分析マトリクス ---
    sens = sensitivity_matrix(
        base_fcf=latest_fcf,
        base_wacc=wacc,
        base_growth=fcf_growth,
        terminal_growth=terminal_growth,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
    )

    lines += [
        "### 感度分析マトリクス（フェアバリュー ¥）",
        "",
        "> 行: FCF成長率、列: WACC",
        "",
    ]

    wacc_headers = " | ".join(f"WACC {w * 100:.1f}%" for w in sens["wacc_labels"])
    lines.append(f"| 成長率 \\\\ WACC | {wacc_headers} |")
    lines.append("|" + "|".join(["---"] * (len(sens["wacc_labels"]) + 1)) + "|")

    for g_val, row in zip(sens["growth_labels"], sens["matrix"]):
        cells = []
        for fv in row:
            if fv is None:
                cells.append("N/A")
            else:
                cells.append(f"¥{fv:,.0f}")
        lines.append(f"| {g_val * 100:.1f}% | " + " | ".join(cells) + " |")

    lines += [
        "",
        "> **注意**: 本試算は簡易モデルです。実際の投資判断には詳細な事業計画・業界調査を参照してください。",
        "",
        "---",
        "",
    ]

    return "\n".join(lines)
