"""
インテグレーションテスト: _build_weekly_report() の定性分析セクション統合検証（Issue #10）
- Top5 各社の定性分析テーブルが watch_list.md に出力されること
- Gemini API 障害時（qualitative=None）はセクションをスキップしてもレポートが生成されること
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipelines.weekly_pipeline as wp


def _make_final_df(tickers=None):
    """最低限の final_df を生成する。"""
    tickers = tickers or ["7203.T"]
    records = [
        {
            "ticker": t,
            "name": f"テスト企業{i}",
            "sector": "製造業",
            "total_score_100": 80.0 - i * 5,
            "roe": 0.15,
            "revenue_annual_growth": 0.08,
            "operating_margins": 0.12,
            "net_debt_ebitda": 1.2,
            "fcf_positive_years": 3,
        }
        for i, t in enumerate(tickers)
    ]
    return pd.DataFrame(records)


def _make_analysis(ticker, name, qualitative):
    """stock_analyses の1要素を生成する。"""
    return {
        "data": {
            "ticker": ticker,
            "name": name,
            "sector": "製造業",
            "total_score_100": 80.0,
            "roe": 0.15,
            "revenue_annual_growth": 0.08,
            "operating_margins": 0.12,
            "net_debt_ebitda": 1.2,
            "fcf_positive_years": 3,
        },
        "memo": "テスト投資メモ",
        "bear_case": "テストベアケース",
        "qualitative": qualitative,
    }


def _sample_qualitative():
    return {
        "q1": {"label": "Strong", "comment": "参入障壁が高い"},
        "q2": {"label": "Moderate", "comment": "プロ経営者"},
        "q3": {"label": "Strong", "comment": "DX需要"},
        "q4": {"label": "Moderate", "comment": "顧客集中度あり"},
        "q5": {"label": "Weak", "comment": "R&D比率低い"},
        "overall_score": 7.0,
        "overall_comment": "総合的に良好",
    }


# ============================================================
# 定性分析セクションが週次レポートに含まれることを検証
# ============================================================

class TestBuildWeeklyReportQualitativeIntegration:
    def _build(self, qualitative):
        final_df = _make_final_df(["7203.T"])
        analyses = [_make_analysis("7203.T", "テスト企業0", qualitative)]
        return wp._build_weekly_report(final_df, analyses, dry_run=False)

    def test_qualitative_table_appears_in_report(self):
        report = self._build(_sample_qualitative())
        assert "| 評価軸 | 評価 | 根拠 |" in report

    def test_all_q_labels_appear_in_report(self):
        report = self._build(_sample_qualitative())
        for label in ("Q1 事業モデル", "Q2 経営陣", "Q3 市場環境", "Q4 顧客基盤", "Q5 組織力"):
            assert label in report, f"{label} がレポートに含まれていない"

    def test_overall_score_appears_in_report(self):
        report = self._build(_sample_qualitative())
        assert "7.0 / 10" in report

    def test_qualitative_none_skips_section_without_crash(self):
        """Gemini API 障害時（None）はセクションをスキップしてレポートを正常生成する。"""
        report = self._build(None)
        assert "テスト企業0" in report
        assert "| 評価軸 | 評価 | 根拠 |" not in report

    def test_qualitative_skipped_dict_also_renders(self):
        """APIキー未設定の _qualitative_skipped() 形式でも出力がクラッシュしない。"""
        from src.ai_analyst.claude_analyzer import _qualitative_skipped
        report = self._build(_qualitative_skipped())
        assert "テスト企業0" in report
        assert "| 評価軸 | 評価 | 根拠 |" in report

    def test_report_contains_detail_section_heading(self):
        report = self._build(_sample_qualitative())
        assert "全銘柄 詳細分析" in report

    def test_report_contains_disclaimer(self):
        report = self._build(_sample_qualitative())
        assert "免責事項" in report

    def test_multiple_stocks_each_have_qualitative(self):
        """Top5 各社それぞれに定性分析テーブルが含まれることを検証する。"""
        tickers = [f"{7200 + i}.T" for i in range(3)]
        final_df = _make_final_df(tickers)
        analyses = [
            _make_analysis(t, f"テスト企業{i}", _sample_qualitative())
            for i, t in enumerate(tickers)
        ]
        report = wp._build_weekly_report(final_df, analyses, dry_run=False)
        # テーブルヘッダーが銘柄数分出現すること
        assert report.count("| 評価軸 | 評価 | 根拠 |") == 3

    def test_dry_run_label_in_report(self):
        report = self._build(_sample_qualitative())
        # dry_run=False なのでラベルなし
        assert "DRY-RUN" not in report

    def test_dry_run_true_adds_label(self):
        final_df = _make_final_df(["7203.T"])
        analyses = [_make_analysis("7203.T", "テスト企業0", _sample_qualitative())]
        report = wp._build_weekly_report(final_df, analyses, dry_run=True)
        assert "DRY-RUN" in report
