#!/usr/bin/env python3
"""PostToolUse hook: .py ファイルの構文チェック"""
import json
import os
import subprocess
import sys

inp = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
try:
    d = json.loads(inp)
except json.JSONDecodeError:
    sys.exit(0)

file_path = d.get("file_path", "")
if not file_path.endswith(".py"):
    sys.exit(0)

result = subprocess.run(
    ["python3", "-m", "py_compile", file_path],
    capture_output=True,
    text=True,
)
if result.returncode == 0:
    print(f"✓ 構文OK: {file_path}")
else:
    print(f"✗ 構文エラー: {file_path}")
    print(result.stderr)
    sys.exit(1)
