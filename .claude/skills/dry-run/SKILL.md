---
name: dry-run
description: パイプラインをdry-runモードで即時実行する。引数: weekly / daily / notify / agent-weekly
disable-model-invocation: true
---

引数に応じて以下を実行してください。失敗した場合はエラーを日本語で報告してください。

## 引数なし or weekly
```bash
cd /Users/michika_maruyama/Desktop/investment_research
python3 pipelines/weekly_pipeline.py --dry-run
```

## daily
```bash
cd /Users/michika_maruyama/Desktop/investment_research
PIPELINE=daily python3 pipelines/entrypoint.py --dry-run
```

## notify
```bash
cd /Users/michika_maruyama/Desktop/investment_research
PIPELINE=notify python3 pipelines/entrypoint.py
```

## agent-weekly
```bash
cd /Users/michika_maruyama/Desktop/investment_research
python3 pipelines/agent_weekly_pipeline.py --dry-run
```

実行ログを表示し、ERROR/WARNING があれば日本語で要約してください。
