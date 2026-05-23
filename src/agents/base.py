"""
マルチエージェント基底クラス

Managed Agents パターン（anthropics/financial-services 参考）に基づく
Orchestrator → Researcher / Screener / Analyst の職務分離アーキテクチャ。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    """エージェント間で受け渡すコンテキスト（不変入力 + 蓄積出力）"""
    config: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    force_refresh: bool = False
    shared: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentResult:
    """エージェントの実行結果"""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    @classmethod
    def ok(cls, **data) -> "AgentResult":
        return cls(success=True, data=data)

    @classmethod
    def fail(cls, error: str) -> "AgentResult":
        return cls(success=False, error=error)


class BaseAgent:
    """全エージェントの基底クラス"""

    name: str = "BaseAgent"

    def run(self, ctx: AgentContext) -> AgentResult:
        raise NotImplementedError(f"{self.name}.run() が未実装です")
