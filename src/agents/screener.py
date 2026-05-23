"""
Screener Agent — 13次元スコアリング・絞り込み

責務:
- 段階2: J-Quants + yfinance詳細財務から8次元スコア計算
- 13次元統合スコア（0〜100点）算出・上位N社選定
- キャッシュ管理
"""
from __future__ import annotations

import time

import pandas as pd

from src.agents.base import AgentContext, AgentResult, BaseAgent
from src.data.yfinance_client import YFinanceClient
from src.screener.unified_scorer import calculate_stage2_scores, calculate_total_score
from src.utils.cache import Cache
from src.utils.logger import get_logger

logger = get_logger("screener_agent")


class ScreenerAgent(BaseAgent):
    """13次元スコアリング・絞り込みエージェント

    ctx.shared への書き込み:
        final_df (DataFrame): 統合スコア順にソートされた最終候補リスト
    """

    name = "ScreenerAgent"

    def __init__(self, cache: Cache, yf_client: YFinanceClient):
        self._cache = cache
        self._yf = yf_client

    def run(self, ctx: AgentContext) -> AgentResult:
        logger.info("[ScreenerAgent] 開始")
        cfg = ctx.config

        stage1_filtered: pd.DataFrame = ctx.shared.get("stage1_filtered")
        eps_series_map: dict = ctx.shared.get("eps_series_map", {})

        if stage1_filtered is None or stage1_filtered.empty:
            return AgentResult.fail("stage1_filtered がありません — ResearcherAgent を先に実行してください")

        stage1_tickers = stage1_filtered["ticker"].tolist()
        ttl_h = cfg["data"]["cache_ttl_hours"]["fundamentals"]

        if ctx.force_refresh:
            self._cache.invalidate("stage2_results")

        stage2_cached = self._cache.get("stage2_results", ttl_hours=ttl_h)

        if stage2_cached:
            final_df = pd.DataFrame(stage2_cached)
            logger.info(f"段階2: キャッシュから取得 ({len(final_df)}件)")
        else:
            logger.info(f"詳細財務取得中: {len(stage1_tickers)}銘柄...")
            detailed_fins_map = {}
            for i, ticker in enumerate(stage1_tickers):
                if i % 20 == 0:
                    logger.info(f"  詳細財務取得中: {i + 1}/{len(stage1_tickers)}")
                detailed_fins_map[ticker] = self._yf.get_detailed_financials(ticker)
                if (i + 1) % 30 == 0:
                    time.sleep(cfg["data"]["batch_sleep_sec"])

            stage2_df = calculate_stage2_scores(stage1_filtered, eps_series_map, detailed_fins_map)
            top_n = cfg["screener"]["step2"].get("top_n_candidates", 20)
            final_df = calculate_total_score(stage2_df, top_n=top_n)
            self._cache.set("stage2_results", final_df.to_dict(orient="records"))
            logger.info(f"段階2: {len(final_df)}件に絞り込み（上位{top_n}社）")

        ctx.shared["final_df"] = final_df

        logger.info("[ScreenerAgent] 完了")
        return AgentResult.ok(final_count=len(final_df))
