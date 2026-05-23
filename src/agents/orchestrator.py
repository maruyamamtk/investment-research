"""
Orchestrator Agent — エージェント全体の調整・実行制御

責務:
- Researcher → Screener → Analyst の順に実行
- エージェント間のコンテキスト共有管理
- エラー時の早期終了・ログ記録
- 最終レポート出力・LINE通知

設計参考: anthropics/financial-services Managed Agents パターン
"""
from __future__ import annotations

from typing import Any

from src.agents.analyst import AnalystAgent
from src.agents.base import AgentContext, AgentResult, BaseAgent
from src.agents.researcher import ResearcherAgent
from src.agents.screener import ScreenerAgent
from src.utils.logger import get_logger

logger = get_logger("orchestrator_agent")


class OrchestratorAgent(BaseAgent):
    """マルチエージェント実行オーケストレーター

    実行順序: ResearcherAgent → ScreenerAgent → AnalystAgent

    Returns (ctx.shared):
        tickers, stage1_filtered, eps_series_map  (Researcher)
        final_df                                  (Screener)
        stock_analyses                            (Analyst)
    """

    name = "OrchestratorAgent"

    def __init__(
        self,
        researcher: ResearcherAgent,
        screener: ScreenerAgent,
        analyst: AnalystAgent,
    ):
        self._researcher = researcher
        self._screener = screener
        self._analyst = analyst
        self._pipeline: list[BaseAgent] = [researcher, screener, analyst]

    def run(self, ctx: AgentContext) -> AgentResult:
        logger.info("[OrchestratorAgent] マルチエージェントパイプライン開始")

        for agent in self._pipeline:
            logger.info(f"  → {agent.name} 実行中...")
            result = agent.run(ctx)
            if not result.success:
                logger.error(f"  ✗ {agent.name} 失敗: {result.error}")
                return AgentResult.fail(f"{agent.name} が失敗しました: {result.error}")
            logger.info(f"  ✓ {agent.name} 完了: {result.data}")

        logger.info("[OrchestratorAgent] 全エージェント完了")
        return AgentResult.ok(
            final_count=len(ctx.shared.get("final_df", [])),
            analyzed_count=len(ctx.shared.get("stock_analyses", [])),
        )
