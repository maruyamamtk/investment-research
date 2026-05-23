#!/usr/bin/env python3
"""PostToolUse hook: 編集ファイルに対応するテストを自動実行する"""
import json
import os
import subprocess
import sys
from pathlib import Path

inp = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
try:
    d = json.loads(inp)
except json.JSONDecodeError:
    sys.exit(0)

file_path = d.get("file_path", "")
if not file_path.endswith(".py"):
    sys.exit(0)

# src/X/Y.py → テスト名の推定マッピング
MAPPINGS = {
    "unified_scorer":    ["test_unified_scorer_stage1", "test_unified_scorer_stage2",
                          "test_unified_scorer_total_score", "test_unified_scorer_missing"],
    "agents/researcher": ["test_researcher_agent"],
    "agents/screener":   ["test_screener_agent"],
    "agents/analyst":    ["test_analyst_agent"],
    "agents/orchestrat": ["test_orchestrator_agent"],
    "cache":             ["test_cache"],
    "gcs_report":        ["test_gcs_report"],
    "portfolio_manager": ["test_portfolio_manager"],
    "rebalance_advisor": ["test_rebalance_advisor"],
    "claude_analyzer":   ["test_qualitative_analysis"],
    "buy_candidates":    [],
    "weekly_pipeline":   ["test_weekly_report_qualitative_integration"],
    "dcf":               ["test_dcf_calculator"],
    "earnings":          ["test_earnings_reviewer"],
}

project_root = Path(__file__).parents[2]
tests_dir = project_root / "tests"

matched = []
for keyword, test_names in MAPPINGS.items():
    if keyword in file_path:
        matched.extend(test_names)

if not matched:
    sys.exit(0)

test_files = [str(tests_dir / f"{t}.py") for t in matched if (tests_dir / f"{t}.py").exists()]
if not test_files:
    sys.exit(0)

print(f"🧪 関連テスト実行: {', '.join(matched)}")
result = subprocess.run(
    ["python3", "-m", "pytest"] + test_files + ["-q", "--tb=short"],
    cwd=str(project_root),
    capture_output=True,
    text=True,
)
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
if result.returncode != 0:
    print(result.stderr[-500:] if result.stderr else "")
    sys.exit(1)
