"""
テスト: ScreenerAgent
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.base import AgentContext, AgentResult
from src.agents.screener import ScreenerAgent


@pytest.fixture
def cfg():
    return {
        "data": {
            "cache_ttl_hours": {"fundamentals": 168},
            "batch_sleep_sec": 0,
        },
        "screener": {
            "step2": {"top_n_candidates": 20},
        },
    }


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get.return_value = None
    return cache


@pytest.fixture
def mock_yf():
    yf = MagicMock()
    yf.get_detailed_financials.return_value = {}
    return yf


def _stage1_df():
    return pd.DataFrame([
        {"ticker": "7203.T", "stage1_score": 7.0, "name": "トヨタ"},
        {"ticker": "6758.T", "stage1_score": 6.5, "name": "ソニー"},
    ])


def _final_df():
    return pd.DataFrame([
        {"ticker": "7203.T", "total_score_100": 75.0, "name": "トヨタ"},
    ])


class TestScreenerAgentNoStage1:
    def test_fails_without_stage1_filtered(self, cfg, mock_cache, mock_yf):
        agent = ScreenerAgent(cache=mock_cache, yf_client=mock_yf)
        ctx = AgentContext(config=cfg)
        result = agent.run(ctx)

        assert not result.success
        assert "stage1_filtered" in result.error

    def test_fails_with_empty_stage1(self, cfg, mock_cache, mock_yf):
        agent = ScreenerAgent(cache=mock_cache, yf_client=mock_yf)
        ctx = AgentContext(config=cfg)
        ctx.shared["stage1_filtered"] = pd.DataFrame()
        result = agent.run(ctx)

        assert not result.success


class TestScreenerAgentSuccess:
    def test_run_success(self, cfg, mock_cache, mock_yf):
        with patch("src.agents.screener.calculate_stage2_scores") as mock_s2:
            with patch("src.agents.screener.calculate_total_score") as mock_total:
                mock_s2.return_value = _final_df()
                mock_total.return_value = _final_df()

                agent = ScreenerAgent(cache=mock_cache, yf_client=mock_yf)
                ctx = AgentContext(config=cfg)
                ctx.shared["stage1_filtered"] = _stage1_df()
                ctx.shared["eps_series_map"] = {}
                result = agent.run(ctx)

        assert result.success
        assert "final_df" in ctx.shared
        assert len(ctx.shared["final_df"]) == 1
        assert result.data["final_count"] == 1

    def test_uses_cache_when_available(self, cfg, mock_cache, mock_yf):
        mock_cache.get.return_value = _final_df().to_dict(orient="records")

        agent = ScreenerAgent(cache=mock_cache, yf_client=mock_yf)
        ctx = AgentContext(config=cfg)
        ctx.shared["stage1_filtered"] = _stage1_df()
        ctx.shared["eps_series_map"] = {}
        result = agent.run(ctx)

        assert result.success
        mock_yf.get_detailed_financials.assert_not_called()

    def test_force_refresh_invalidates_cache(self, cfg, mock_cache, mock_yf):
        with patch("src.agents.screener.calculate_stage2_scores") as mock_s2:
            with patch("src.agents.screener.calculate_total_score") as mock_total:
                mock_s2.return_value = _final_df()
                mock_total.return_value = _final_df()

                agent = ScreenerAgent(cache=mock_cache, yf_client=mock_yf)
                ctx = AgentContext(config=cfg, force_refresh=True)
                ctx.shared["stage1_filtered"] = _stage1_df()
                ctx.shared["eps_series_map"] = {}
                agent.run(ctx)

        mock_cache.invalidate.assert_called_once_with("stage2_results")
