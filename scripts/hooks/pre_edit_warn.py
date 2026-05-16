#!/usr/bin/env python3
"""PreToolUse hook: config/settings.yaml 編集時に警告を表示する"""
import json
import os
import sys

inp = os.environ.get("CLAUDE_TOOL_INPUT", "{}")
try:
    d = json.loads(inp)
except json.JSONDecodeError:
    sys.exit(0)

file_path = d.get("file_path", "")
if file_path.endswith("config/settings.yaml"):
    print("⚠  このファイルにはAPIキー（J-Quants・Gemini・LINE）が含まれています。")
    print("   変更内容を確認し、誤ってキーを削除・上書きしないよう注意してください。")
