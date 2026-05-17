"""
テスト: 参照すべき一次情報ソースセクション（Issue #11）
- _build_info_sources_section() が正しいMarkdownテーブルを返すこと
- _build_weekly_report() のレポート末尾に情報ソースセクションが含まれること
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipelines.weekly_pipeline as wp


def _make_df(rows):
    return pd.DataFrame(rows)


def _make_analysis(ticker, name):
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
        "qualitative": None,
    }


class TestBuildInfoSourcesSection:
    def test_returns_markdown_table_header(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ自動車", "website": "https://toyota.com"}])
        lines = wp._build_info_sources_section(df)
        assert "## 参照すべき一次情報ソース" in lines
        assert "| 銘柄 | EDINET（有報） | TDnet（適時開示） | IR ページ |" in lines

    def test_edinet_link_appears_for_each_ticker(self):
        df = _make_df([
            {"ticker": "7203.T", "name": "トヨタ自動車", "website": ""},
            {"ticker": "6758.T", "name": "ソニー", "website": ""},
        ])
        lines = wp._build_info_sources_section(df)
        table_rows = [l for l in lines if l.startswith("|") and "有報を見る" in l]
        assert len(table_rows) == 2

    def test_edinet_url_is_correct(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ", "website": ""}])
        lines = wp._build_info_sources_section(df)
        assert any("https://disclosure.edinet-fsa.go.jp/" in l for l in lines)

    def test_tdnet_url_is_correct(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ", "website": ""}])
        lines = wp._build_info_sources_section(df)
        assert any("https://www.release.tdnet.info/" in l for l in lines)

    def test_ir_link_when_website_present(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ", "website": "https://toyota.com"}])
        lines = wp._build_info_sources_section(df)
        assert any("[IR](https://toyota.com)" in l for l in lines)

    def test_ir_dash_when_website_absent(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ", "website": ""}])
        lines = wp._build_info_sources_section(df)
        row_line = next(l for l in lines if "トヨタ" in l and l.startswith("|"))
        assert row_line.endswith("| - |")

    def test_ir_dash_when_website_column_missing(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ"}])
        lines = wp._build_info_sources_section(df)
        row_line = next(l for l in lines if "トヨタ" in l and l.startswith("|"))
        assert row_line.endswith("| - |")

    def test_ticker_name_appears_in_row(self):
        df = _make_df([{"ticker": "7203.T", "name": "トヨタ自動車", "website": ""}])
        lines = wp._build_info_sources_section(df)
        assert any("トヨタ自動車（7203.T）" in l for l in lines)


class TestBuildWeeklyReportInfoSourcesIntegration:
    def _build(self, df, analyses=None):
        analyses = analyses or [_make_analysis(row["ticker"], row.get("name", row["ticker"])) for _, row in df.iterrows()]
        return wp._build_weekly_report(df, analyses, dry_run=False)

    def test_info_sources_section_in_report(self):
        df = _make_df([{
            "ticker": "7203.T", "name": "トヨタ自動車",
            "sector": "製造業", "total_score_100": 80.0,
            "roe": 0.15, "revenue_annual_growth": 0.08,
            "operating_margins": 0.12, "net_debt_ebitda": 1.2,
            "fcf_positive_years": 3, "website": "https://toyota.com",
        }])
        report = self._build(df)
        assert "## 参照すべき一次情報ソース" in report

    def test_info_sources_section_appears_before_disclaimer(self):
        df = _make_df([{
            "ticker": "7203.T", "name": "トヨタ自動車",
            "sector": "製造業", "total_score_100": 80.0,
            "roe": 0.15, "revenue_annual_growth": 0.08,
            "operating_margins": 0.12, "net_debt_ebitda": 1.2,
            "fcf_positive_years": 3, "website": "",
        }])
        report = self._build(df)
        sources_pos = report.index("参照すべき一次情報ソース")
        disclaimer_pos = report.index("免責事項")
        assert sources_pos < disclaimer_pos

    def test_edinet_and_tdnet_urls_in_report(self):
        df = _make_df([{
            "ticker": "7203.T", "name": "トヨタ",
            "sector": "製造業", "total_score_100": 80.0,
            "roe": 0.15, "revenue_annual_growth": 0.08,
            "operating_margins": 0.12, "net_debt_ebitda": 1.2,
            "fcf_positive_years": 3, "website": "",
        }])
        report = self._build(df)
        assert "https://disclosure.edinet-fsa.go.jp/" in report
        assert "https://www.release.tdnet.info/" in report

    def test_ir_link_in_report_when_website_set(self):
        df = _make_df([{
            "ticker": "7203.T", "name": "トヨタ",
            "sector": "製造業", "total_score_100": 80.0,
            "roe": 0.15, "revenue_annual_growth": 0.08,
            "operating_margins": 0.12, "net_debt_ebitda": 1.2,
            "fcf_positive_years": 3, "website": "https://toyota.com",
        }])
        report = self._build(df)
        assert "[IR](https://toyota.com)" in report
