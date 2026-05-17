"""
Step2: レポート出力ユーティリティ

旧バイナリフィルタ実装（filter_*関数群・apply_step2_analysis）は
unified_scorer.py の13次元統合スコアリングに移行済みのため削除。
"""
import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("step2_analysis")


def format_step2_table(df: pd.DataFrame) -> str:
    """上位銘柄のスコアランキング表をMarkdown形式で生成する。"""
    if df.empty:
        return "候補銘柄なし"

    cols = {
        "ticker": "銘柄コード",
        "name": "銘柄名",
        "sector": "セクター",
        "total_score_100": "総合スコア",
        "roe": "ROE",
        "revenue_annual_growth": "年次売上成長率",
        "peg_calc": "PEG比率",
        "net_debt_ebitda": "純負債/EBITDA",
        "operating_margins": "営業利益率",
        "ev_revenue": "EV/Revenue",
        "ev_ebitda": "EV/EBITDA",
        "pe_ratio": "PER",
        "pbr": "PBR",
        "data_quality_note": "データ品質",
    }
    display = df[[c for c in cols if c in df.columns]].copy()
    display = display.rename(columns=cols)

    for col in ["ROE", "年次売上成長率", "営業利益率"]:
        if col in display.columns:
            display[col] = display[col].apply(lambda x: f"{x:.1%}" if pd.notna(x) else "N/A")
    if "総合スコア" in display.columns:
        display["総合スコア"] = display["総合スコア"].apply(
            lambda x: f"{x:.1f}/100" if pd.notna(x) else "N/A"
        )
    if "純負債/EBITDA" in display.columns:
        display["純負債/EBITDA"] = display["純負債/EBITDA"].apply(
            lambda x: f"{x:.1f}x" if pd.notna(x) else "N/A"
        )
    if "PEG比率" in display.columns:
        display["PEG比率"] = display["PEG比率"].apply(
            lambda x: f"{x:.2f}" if pd.notna(x) else "N/A"
        )
    for col in ["EV/Revenue", "EV/EBITDA"]:
        if col in display.columns:
            display[col] = display[col].apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "N/A")
    if "PER" in display.columns:
        display["PER"] = display["PER"].apply(lambda x: f"{x:.1f}x" if pd.notna(x) else "N/A")
    if "PBR" in display.columns:
        display["PBR"] = display["PBR"].apply(lambda x: f"{x:.2f}x" if pd.notna(x) else "N/A")

    return display.to_markdown(index=False)
