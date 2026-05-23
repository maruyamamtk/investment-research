"""
テスト: OrchestratorAgent
"""
import os
import sys
from unittest.mock import MagicMock

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.base import AgentContext, AgentResult
from src.agents.orchestrator import OrchestratorAgent


def _ok_agent(name: str, **side_effects):
    agent = MagicMock()
    agent.name = name

    def _run(ctx):
        ctx.shared.update(side_effects)
        return AgentResult.ok(**{k: v for k, v in side_effects.items() if isinstance(v, (int, float, str))})

    agent.run.side_effect = _run
    return agent


def _fail_agent(name: str, error: str):
    agent = MagicMock()
    agent.name = name
    agent.run.return_value = AgentResult.fail(error)
    return agent


class TestOrchestratorSuccess:
    def test_runs_all_agents_in_order(self):
        calls = []

        def make_agent(name):
            a = MagicMock()
            a.name = name
            def run(ctx, _n=name):
                calls.append(_n)
                return AgentResult.ok()
            a.run.side_effect = run
            return a

        researcher = make_agent("ResearcherAgent")
        screener = make_agent("ScreenerAgent")
        analyst = make_agent("AnalystAgent")

        orchestrator = OrchestratorAgent(researcher, screener, analyst)
        ctx = AgentContext()
        result = orchestrator.run(ctx)

        assert result.success
        assert calls == ["ResearcherAgent", "ScreenerAgent", "AnalystAgent"]

    def test_result_contains_counts(self):
        final_df = pd.DataFrame([{"ticker": "7203.T"}])
        analyses = [{"data": {}, "memo": "", "bear_case": "", "qualitative": {}}]

        researcher = _ok_agent("ResearcherAgent")
        screener = MagicMock()
        screener.name = "ScreenerAgent"

        def screener_run(ctx):
            ctx.shared["final_df"] = final_df
            return AgentResult.ok(final_count=1)

        screener.run.side_effect = screener_run

        analyst = MagicMock()
        analyst.name = "AnalystAgent"

        def analyst_run(ctx):
            ctx.shared["stock_analyses"] = analyses
            return AgentResult.ok(analyzed_count=1)

        analyst.run.side_effect = analyst_run

        orchestrator = OrchestratorAgent(researcher, screener, analyst)
        ctx = AgentContext()
        result = orchestrator.run(ctx)

        assert result.success
        assert result.data["final_count"] == 1
        assert result.data["analyzed_count"] == 1


class TestOrchestratorFailure:
    def test_stops_on_researcher_failure(self):
        researcher = _fail_agent("ResearcherAgent", "データ取得エラー")
        screener = MagicMock()
        analyst = MagicMock()

        orchestrator = OrchestratorAgent(researcher, screener, analyst)
        ctx = AgentContext()
        result = orchestrator.run(ctx)

        assert not result.success
        assert "ResearcherAgent" in result.error
        screener.run.assert_not_called()
        analyst.run.assert_not_called()

    def test_stops_on_screener_failure(self):
        researcher = _ok_agent("ResearcherAgent")
        screener = _fail_agent("ScreenerAgent", "スコアリングエラー")
        analyst = MagicMock()

        orchestrator = OrchestratorAgent(researcher, screener, analyst)
        ctx = AgentContext()
        result = orchestrator.run(ctx)

        assert not result.success
        assert "ScreenerAgent" in result.error
        analyst.run.assert_not_called()
