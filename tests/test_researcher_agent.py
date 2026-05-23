"""
テスト: ResearcherAgent
"""
import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.base import AgentContext
from src.agents.researcher import ResearcherAgent


@pytest.fixture
def cfg():
    return {
        "data": {
            "cache_ttl_hours": {"fundamentals": 168},
            "batch_sleep_sec": 0,
            "batch_size": 10,
        },
        "api": {
            "jquants": {"rate_limit_delay": 0},
        },
    }


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    cache.get.return_value = None  # キャッシュなし
    return cache


@pytest.fixture
def mock_yf():
    yf = MagicMock()
    yf.get_basic_info_batch.return_value = [
        {
            "ticker": "7203.T",
            "market_cap": 3e13,
            "operating_margins": 0.08,
            "pbr": 1.0,
            "revenue_growth": 0.05,
            "equity_ratio": 0.45,
            "peg_ratio": 1.2,
            "payout_ratio": 0.3,
        }
    ]
    return yf


def _make_stage1_df():
    return pd.DataFrame([
        {
            "ticker": "7203.T",
            "stage1_score": 6.0,
            "operating_margin": 6.0,
            "equity_ratio": 6.0,
            "peg_ratio": 6.0,
            "market_cap": 5.0,
            "payout_ratio": 5.0,
        }
    ])


class TestResearcherAgentWithoutJQ:
    """J-Quants未設定（フォールバック）でのテスト"""

    def test_run_success(self, cfg, mock_cache, mock_yf):
        with patch("src.agents.researcher.get_prime_tickers_fallback", return_value=["7203.T"]):
            with patch("src.agents.researcher.calculate_stage1_scores") as mock_s1:
                with patch("src.agents.researcher.filter_stage1_candidates") as mock_filt:
                    mock_s1.return_value = _make_stage1_df()
                    mock_filt.return_value = _make_stage1_df()

                    agent = ResearcherAgent(cache=mock_cache, yf_client=mock_yf, jq_client=None)
                    ctx = AgentContext(config=cfg)
                    result = agent.run(ctx)

        assert result.success
        assert "stage1_filtered" in ctx.shared
        assert ctx.shared["stage1_filtered"] is not None
        assert "tickers" in ctx.shared
        assert "eps_series_map" in ctx.shared
        assert ctx.shared["eps_series_map"] == {}

    def test_dry_run_limits_tickers(self, cfg, mock_cache, mock_yf):
        tickers = [f"{i:04d}.T" for i in range(100)]
        with patch("src.agents.researcher.get_prime_tickers_fallback", return_value=tickers):
            with patch("src.agents.researcher.calculate_stage1_scores") as mock_s1:
                with patch("src.agents.researcher.filter_stage1_candidates") as mock_filt:
                    mock_s1.return_value = _make_stage1_df()
                    mock_filt.return_value = _make_stage1_df()

                    agent = ResearcherAgent(cache=mock_cache, yf_client=mock_yf, jq_client=None)
                    ctx = AgentContext(config=cfg, dry_run=True)
                    result = agent.run(ctx)

        assert result.success
        # dry_run のとき最初の30銘柄のみ渡される
        mock_yf.get_basic_info_batch.assert_called_once()
        call_tickers = mock_yf.get_basic_info_batch.call_args[0][0]
        assert len(call_tickers) == 30

    def test_uses_cache_when_available(self, cfg, mock_cache, mock_yf):
        stage1_data = _make_stage1_df().to_dict(orient="records")
        mock_cache.get.return_value = stage1_data  # キャッシュヒット

        with patch("src.agents.researcher.get_prime_tickers_fallback", return_value=["7203.T"]):
            agent = ResearcherAgent(cache=mock_cache, yf_client=mock_yf, jq_client=None)
            ctx = AgentContext(config=cfg)
            result = agent.run(ctx)

        assert result.success
        mock_yf.get_basic_info_batch.assert_not_called()


class TestResearcherAgentResult:
    def test_result_contains_stage1_count(self, cfg, mock_cache, mock_yf):
        with patch("src.agents.researcher.get_prime_tickers_fallback", return_value=["7203.T"]):
            with patch("src.agents.researcher.calculate_stage1_scores") as mock_s1:
                with patch("src.agents.researcher.filter_stage1_candidates") as mock_filt:
                    mock_s1.return_value = _make_stage1_df()
                    mock_filt.return_value = _make_stage1_df()

                    agent = ResearcherAgent(cache=mock_cache, yf_client=mock_yf, jq_client=None)
                    ctx = AgentContext(config=cfg)
                    result = agent.run(ctx)

        assert result.success
        assert "stage1_count" in result.data
        assert result.data["stage1_count"] == 1
