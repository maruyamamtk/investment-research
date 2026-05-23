"""
Researcher Agent — データ収集・キャッシュ管理

責務:
- J-Quants から銘柄リスト・財務諸表（EPS/売上高）取得
- yfinance から基本情報取得 → 段階1スコア計算・絞り込み
- キャッシュ管理（TTLベース）
"""
from __future__ import annotations

import time

import pandas as pd

from src.agents.base import AgentContext, AgentResult, BaseAgent
from src.data.jquants_client import JQuantsClient, get_prime_tickers_fallback
from src.data.yfinance_client import YFinanceClient
from src.screener.unified_scorer import calculate_stage1_scores, filter_stage1_candidates
from src.utils.cache import Cache
from src.utils.logger import get_logger

logger = get_logger("researcher_agent")


class ResearcherAgent(BaseAgent):
    """データ収集・キャッシュ管理エージェント

    ctx.shared への書き込み:
        tickers (list[str])         : 全プライム銘柄 ticker リスト
        jq_codes (list[str])        : 5桁 J-Quants コード
        stage1_filtered (DataFrame) : 段階1スコア通過銘柄
        eps_series_map (dict)       : ticker → {annual: [], quarterly: []}
    """

    name = "ResearcherAgent"

    def __init__(self, cache: Cache, yf_client: YFinanceClient, jq_client: JQuantsClient | None = None):
        self._cache = cache
        self._yf = yf_client
        self._jq = jq_client

    def run(self, ctx: AgentContext) -> AgentResult:
        logger.info("[ResearcherAgent] 開始")
        cfg = ctx.config
        dry_run = ctx.dry_run
        force_refresh = ctx.force_refresh

        # dry_run と正規実行でキャッシュキーを分離し、30銘柄キャッシュが本番結果を汚染しないようにする
        cache_prefix = "dryrun_" if dry_run else ""
        stage1_key = f"{cache_prefix}stage1_results"
        watchlist_key = f"{cache_prefix}watchlist"

        if force_refresh:
            for key in (stage1_key, watchlist_key):
                self._cache.invalidate(key)

        # --- 銘柄リスト取得 ---
        if self._jq:
            tickers = self._jq.get_prime_tickers()
            jq_codes = self._jq.get_prime_codes()
        else:
            tickers = get_prime_tickers_fallback()
            jq_codes = [t.replace(".T", "") + "0" for t in tickers]

        if dry_run:
            tickers = tickers[:30]
            jq_codes = jq_codes[:30]
            logger.info("DRY-RUN: 最初の30銘柄のみ処理します")

        logger.info(f"対象銘柄数: {len(tickers)}件")

        # --- 段階1: yfinance速報スコア ---
        ttl_h = cfg["data"]["cache_ttl_hours"]["fundamentals"]
        stage1_cached = self._cache.get(stage1_key, ttl_hours=ttl_h)

        if stage1_cached:
            stage1_filtered = pd.DataFrame(stage1_cached)
            logger.info(f"段階1: キャッシュから取得 ({len(stage1_filtered)}件)")
        else:
            basic_info_list = self._yf.get_basic_info_batch(
                tickers, batch_size=cfg["data"]["batch_size"]
            )
            stage1_df = calculate_stage1_scores(basic_info_list)
            stage1_filtered = filter_stage1_candidates(stage1_df)
            self._cache.set(stage1_key, stage1_filtered.to_dict(orient="records"))
            logger.info(f"段階1: {len(stage1_filtered)}件に絞り込み")

        stage1_tickers = stage1_filtered["ticker"].tolist()

        # --- J-Quants財務諸表取得（段階2前処理）---
        eps_series_map: dict = {}
        if self._jq:
            ticker_to_code = {
                ticker: ticker.replace(".T", "") + "0"
                for ticker in stage1_tickers
            }
            eps_by_code = self._jq.get_statements_batch(
                list(ticker_to_code.values()),
                sleep_sec=cfg["api"]["jquants"].get("rate_limit_delay", 0.15),
            )
            for ticker, code5 in ticker_to_code.items():
                eps_series_map[ticker] = eps_by_code.get(code5, {"annual": [], "quarterly": []})
        else:
            logger.warning("J-Quants未設定: EPS系データなしで処理します（欠損値=5点補完）")

        ctx.shared["tickers"] = tickers
        ctx.shared["jq_codes"] = jq_codes
        ctx.shared["stage1_filtered"] = stage1_filtered
        ctx.shared["eps_series_map"] = eps_series_map

        logger.info("[ResearcherAgent] 完了")
        return AgentResult.ok(
            tickers_count=len(tickers),
            stage1_count=len(stage1_filtered),
        )
