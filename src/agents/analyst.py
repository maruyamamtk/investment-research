"""
Analyst Agent — 定性分析・投資テーゼ・レポート生成

責務:
- TopN銘柄の投資メモ・ベアケース・Q1〜Q5定性分析生成（Gemini API）
- 分析結果を構造化データとして出力
"""
from __future__ import annotations

import time

import pandas as pd

from src.agents.base import AgentContext, AgentResult, BaseAgent
from src.ai_analyst.claude_analyzer import ClaudeAnalyzer
from src.utils.logger import get_logger

logger = get_logger("analyst_agent")


class AnalystAgent(BaseAgent):
    """定性分析・投資テーゼ生成エージェント

    ctx.shared への書き込み:
        stock_analyses (list[dict]): TopN銘柄の分析結果
            各要素: {data, memo, bear_case, qualitative}
    """

    name = "AnalystAgent"

    def __init__(self, analyzer: ClaudeAnalyzer):
        self._analyzer = analyzer

    def run(self, ctx: AgentContext) -> AgentResult:
        logger.info("[AnalystAgent] 開始")

        final_df: pd.DataFrame = ctx.shared.get("final_df")
        if final_df is None or final_df.empty:
            return AgentResult.fail("final_df がありません — ScreenerAgent を先に実行してください")

        ai_top_n = ctx.config.get("screener", {}).get("step2", {}).get("ai_analysis_top_n", 20)
        top_stocks = final_df.head(ai_top_n)
        stock_analyses = []

        logger.info(f"  AI分析対象: Top{ai_top_n}銘柄")

        for _, row in top_stocks.iterrows():
            stock_dict = row.to_dict()
            name = stock_dict.get("name", row["ticker"])
            ticker = row["ticker"]

            logger.info(f"  AI分析中: {name} ({ticker})")

            memo = self._analyzer.generate_investment_memo(stock_dict)
            bear = self._analyzer.generate_bear_case(stock_dict)
            qualitative = self._analyzer.analyze_qualitative(
                ticker=ticker,
                company_name=name,
                stock_data=stock_dict,
            )

            stock_analyses.append({
                "data": stock_dict,
                "memo": memo,
                "bear_case": bear,
                "qualitative": qualitative,
            })
            time.sleep(3)  # RPM制限対策: Top20では最大60呼び出しになるため余裕を持たせる

        ctx.shared["stock_analyses"] = stock_analyses

        logger.info(f"[AnalystAgent] 完了: {len(stock_analyses)}件の分析生成")
        return AgentResult.ok(analyzed_count=len(stock_analyses))
