"""
テスト: AnalystAgent
"""
import os
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.analyst import AnalystAgent
from src.agents.base import AgentContext


def _make_final_df(n=5):
    return pd.DataFrame([
        {"ticker": f"{7000 + i:04d}.T", "name": f"テスト株{i}", "total_score_100": 80.0 - i}
        for i in range(n)
    ])


@pytest.fixture
def mock_analyzer():
    analyzer = MagicMock()
    analyzer.generate_investment_memo.return_value = "テスト投資メモ"
    analyzer.generate_bear_case.return_value = "テストベアケース"
    analyzer.analyze_qualitative.return_value = {
        "q1": {"label": "Strong", "comment": "強い"},
        "q2": {"label": "Moderate", "comment": "普通"},
        "q3": {"label": "Strong", "comment": "良い"},
        "q4": {"label": "Weak", "comment": "弱い"},
        "q5": {"label": "Unknown", "comment": "不明"},
        "overall_score": 7.0,
        "label_score": 6.5,
        "overall_comment": "総合評価テスト",
    }
    return analyzer


class TestAnalystAgentNoData:
    def test_fails_without_final_df(self, mock_analyzer):
        agent = AnalystAgent(analyzer=mock_analyzer)
        ctx = AgentContext()
        result = agent.run(ctx)

        assert not result.success
        assert "final_df" in result.error

    def test_fails_with_empty_df(self, mock_analyzer):
        agent = AnalystAgent(analyzer=mock_analyzer)
        ctx = AgentContext()
        ctx.shared["final_df"] = pd.DataFrame()
        result = agent.run(ctx)

        assert not result.success


class TestAnalystAgentSuccess:
    def test_analyzes_top_n_from_config(self, mock_analyzer):
        agent = AnalystAgent(analyzer=mock_analyzer)
        ctx = AgentContext(config={"screener": {"step2": {"ai_analysis_top_n": 5}}})
        ctx.shared["final_df"] = _make_final_df(10)
        result = agent.run(ctx)

        assert result.success
        assert "stock_analyses" in ctx.shared
        # 設定値 ai_analysis_top_n=5 に従い5銘柄のみ分析
        assert len(ctx.shared["stock_analyses"]) == 5
        assert result.data["analyzed_count"] == 5

    def test_analyzes_top20_by_default(self, mock_analyzer):
        agent = AnalystAgent(analyzer=mock_analyzer)
        ctx = AgentContext()  # config 未設定 → デフォルト20
        ctx.shared["final_df"] = _make_final_df(20)
        result = agent.run(ctx)

        assert result.success
        # デフォルトは20銘柄
        assert len(ctx.shared["stock_analyses"]) == 20
        assert result.data["analyzed_count"] == 20

    def test_analysis_structure(self, mock_analyzer):
        agent = AnalystAgent(analyzer=mock_analyzer)
        ctx = AgentContext()
        ctx.shared["final_df"] = _make_final_df(3)
        agent.run(ctx)

        for analysis in ctx.shared["stock_analyses"]:
            assert "data" in analysis
            assert "memo" in analysis
            assert "bear_case" in analysis
            assert "qualitative" in analysis
            assert analysis["memo"] == "テスト投資メモ"
            assert analysis["bear_case"] == "テストベアケース"

    def test_calls_analyzer_for_each_stock(self, mock_analyzer):
        agent = AnalystAgent(analyzer=mock_analyzer)
        ctx = AgentContext()
        n = 3
        ctx.shared["final_df"] = _make_final_df(n)
        agent.run(ctx)

        assert mock_analyzer.generate_investment_memo.call_count == n
        assert mock_analyzer.generate_bear_case.call_count == n
        assert mock_analyzer.analyze_qualitative.call_count == n
