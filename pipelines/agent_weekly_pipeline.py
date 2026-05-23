"""
マルチエージェント週次パイプライン（Issue #16）

単一パイプラインを職務分離されたエージェント構成に再設計:
  OrchestratorAgent
    ├── ResearcherAgent  — データ収集・キャッシュ管理
    ├── ScreenerAgent    — 13次元スコアリング・絞り込み
    └── AnalystAgent     — 定性分析・投資テーゼ・レポート生成

使用方法:
    python3 pipelines/agent_weekly_pipeline.py [--dry-run] [--force-refresh]
"""
import argparse
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agents.analyst import AnalystAgent
from src.agents.base import AgentContext
from src.agents.orchestrator import OrchestratorAgent
from src.agents.researcher import ResearcherAgent
from src.agents.screener import ScreenerAgent
from src.ai_analyst.claude_analyzer import ClaudeAnalyzer
from src.data.jquants_client import JQuantsClient
from src.data.yfinance_client import YFinanceClient
from src.notification.line_notifier import from_config as line_from_config
from src.screener.buy_candidates import BuyCandidatesManager
from src.screener.step2_analysis import format_step2_table
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("agent_weekly_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    override_credentials(cfg)
    return cfg


def run_agent_weekly(dry_run: bool = False, force_refresh: bool = False):
    logger.info("=" * 60)
    logger.info(f"マルチエージェント週次パイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")

    jq_email = cfg["api"]["jquants"]["email"]
    jq_pass = cfg["api"]["jquants"]["password"]
    jq_client = JQuantsClient(email=jq_email, password=jq_pass, cache=cache) if (jq_email and jq_pass) else None

    yf_client = YFinanceClient(cache=cache, batch_sleep=cfg["data"]["batch_sleep_sec"])
    analyzer = ClaudeAnalyzer(
        api_key=cfg["api"]["gemini"]["api_key"],
        model=cfg["api"]["gemini"]["model_weekly"],
    )
    notifier = line_from_config(cfg)
    buy_mgr = BuyCandidatesManager(
        cache_path=cfg["output"].get("buy_candidates_cache", "cache/buy_candidates.json"),
        md_path=cfg["output"].get("buy_candidates_md", "output/buy_candidates.md"),
    )

    # --- エージェント組み立て ---
    researcher = ResearcherAgent(cache=cache, yf_client=yf_client, jq_client=jq_client)
    screener = ScreenerAgent(cache=cache, yf_client=yf_client)
    analyst = AnalystAgent(analyzer=analyzer)
    orchestrator = OrchestratorAgent(researcher=researcher, screener=screener, analyst=analyst)

    ctx = AgentContext(config=cfg, dry_run=dry_run, force_refresh=force_refresh)

    # --- 実行 ---
    result = orchestrator.run(ctx)
    if not result.success:
        logger.error(f"パイプライン失敗: {result.error}")
        return None

    final_df = ctx.shared["final_df"]
    stock_analyses = ctx.shared["stock_analyses"]

    # --- レポート出力 ---
    logger.info("【レポート生成】")
    report = _build_report(final_df, stock_analyses, dry_run)
    output_path = cfg["output"]["weekly_report"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"レポート出力: {output_path}")

    # 後方互換: weekly_moat_stocks.md → watch_list.md シンボリックリンク
    legacy_path = cfg["output"].get("weekly_report_legacy", "output/weekly_moat_stocks.md")
    _ensure_legacy_symlink(output_path, legacy_path)

    # --- LINE通知 ---
    # dry_run と正規実行でキャッシュキーを分離し、dry_runの前回リストが本番通知に混入しないようにする
    watchlist_key = "dryrun_watchlist" if dry_run else "watchlist"
    new_watchlist = final_df["ticker"].head(20).tolist()
    prev_watchlist = cache.get(watchlist_key, ttl_hours=9999) or []
    cache.set(watchlist_key, new_watchlist)

    ticker_names = {row["ticker"]: row.get("name", row["ticker"]) for _, row in final_df.iterrows()}
    notifier.notify_watchlist_update(
        new_watchlist=new_watchlist,
        prev_watchlist=prev_watchlist,
        ticker_names=ticker_names,
    )

    # --- 軸B ファンダメンタルズ再確認 ---
    if not dry_run:
        logger.info("【軸B】購入候補ファンダメンタルズ再確認")
        _check_axis_b(buy_mgr, final_df, new_watchlist, notifier)

    logger.info("マルチエージェント週次パイプライン完了")
    return final_df


def _build_report(final_df, stock_analyses: list, dry_run: bool) -> str:
    import math

    def _is_nan(v):
        try:
            return math.isnan(float(v))
        except (TypeError, ValueError):
            return False

    now = datetime.now().strftime("%Y年%m月%d日")
    dry_label = "【DRY-RUN】" if dry_run else ""

    lines = [
        f"# {dry_label}週次スクリーニングレポート（マルチエージェント版）",
        f"生成日時: {now}",
        "",
        "---",
        "",
        "## スクリーニング結果サマリー",
        "",
        f"- **スクリーニング通過銘柄数**: {len(final_df)}社（13次元統合スコア Top{len(final_df)}）",
        f"- **おすすめ銘柄（Top5）**: {', '.join(final_df.head(5)['ticker'].tolist())}",
        "",
        "---",
        "",
        "## Top20 スコアランキング",
        "",
        format_step2_table(final_df),
        "",
        "---",
        "",
        "## おすすめ銘柄 詳細分析（Top5）",
        "",
    ]

    q_labels = {
        "q1": "Q1 事業モデル・競争優位性",
        "q2": "Q2 経営陣・ガバナンス",
        "q3": "Q3 市場環境・成長ポテンシャル",
        "q4": "Q4 顧客基盤・サプライチェーン",
        "q5": "Q5 組織力・企業文化",
    }

    for i, analysis in enumerate(stock_analyses, 1):
        d = analysis["data"]
        ticker = d.get("ticker", "")
        name = d.get("name", ticker)
        score = d.get("total_score_100")
        roe = d.get("roe")
        rev_growth = d.get("revenue_annual_growth")
        margin = d.get("operating_margins")
        nd = d.get("net_debt_ebitda")
        score_str = f"{score:.1f}/100" if score is not None and not _is_nan(score) else "N/A"

        lines += [
            f"### {i}. {name}（{ticker}）",
            "",
            f"**総合スコア**: {score_str}  |  **セクター**: {d.get('sector', 'N/A')}",
            "",
            "| 指標 | 値 |",
            "|------|-----|",
            f"| ROE | {roe:.1%} |" if roe is not None and not _is_nan(roe) else "| ROE | N/A |",
            f"| 年次売上高成長率 | {rev_growth:.1%} |" if rev_growth is not None and not _is_nan(rev_growth) else "| 年次売上高成長率 | N/A |",
            f"| 営業利益率 | {margin:.1%} |" if margin is not None and not _is_nan(margin) else "| 営業利益率 | N/A |",
            f"| 純負債/EBITDA | {nd:.1f}x |" if nd is not None and not _is_nan(nd) else "| 純負債/EBITDA | N/A |",
            f"| FCFプラス年数 | {d.get('fcf_positive_years', 'N/A')}期 |",
            "",
            "**投資メモ**",
            "",
            analysis["memo"],
            "",
            "**ベアケース（リスク分析）**",
            "",
            analysis["bear_case"],
            "",
        ]

        qualitative = analysis.get("qualitative")
        if qualitative:
            lines += [
                "**定性分析（Q1〜Q5フレームワーク）**",
                "",
                "| 評価軸 | 評価 | 根拠 |",
                "|--------|------|------|",
            ]
            for key, label in q_labels.items():
                entry = qualitative.get(key, {})
                ev_label = entry.get("label", "Unknown")
                comment = entry.get("comment", "").replace("|", "｜")
                lines.append(f"| {label} | {ev_label} | {comment} |")

            score_val = qualitative.get("overall_score")
            score_str2 = f"{score_val:.1f} / 10" if score_val is not None else "N/A"
            lines += [
                "",
                f"**総合定性スコア: {score_str2}**",
                "",
                qualitative.get("overall_comment", ""),
                "",
            ]

        lines += ["---", ""]

    lines += _build_info_sources_section(final_df)

    lines += [
        "---",
        "",
        "## 免責事項",
        "",
        "> このレポートは自動生成された情報提供を目的としたものであり、投資助言ではありません。",
        "> 投資判断はご自身の責任で行ってください。",
    ]

    return "\n".join(lines)


def _ensure_legacy_symlink(target: str, link_path: str) -> None:
    """watch_list.md への後方互換シンボリックリンクを作成する。"""
    try:
        if os.path.islink(link_path):
            os.unlink(link_path)
        elif os.path.exists(link_path):
            os.rename(link_path, link_path + ".bak")
        rel_target = os.path.basename(target)
        os.symlink(rel_target, link_path)
        logger.info(f"後方互換シンボリックリンク作成: {link_path} → {rel_target}")
    except Exception as e:
        logger.warning(f"シンボリックリンク作成失敗（スキップ）: {e}")


def _build_info_sources_section(df) -> list:
    """各銘柄の一次情報ソース（EDINET・TDnet・IR）をMarkdownテーブルとして返す。"""
    lines = [
        "## 参照すべき一次情報ソース",
        "",
        "| 銘柄 | EDINET（有報） | TDnet（適時開示） | IR ページ |",
        "|------|--------------|----------------|---------|",
    ]
    for _, row in df.iterrows():
        ticker = row.get("ticker", "")
        name = row.get("name", ticker)
        label = f"{name}（{ticker}）"
        edinet_url = "https://disclosure.edinet-fsa.go.jp/"
        tdnet_url = "https://www.release.tdnet.info/"
        website = row.get("website", "") or ""
        edinet_cell = f"[有報を見る]({edinet_url})"
        tdnet_cell = f"[開示を見る]({tdnet_url})"
        ir_cell = f"[IR]({website})" if website else "-"
        lines.append(f"| {label} | {edinet_cell} | {tdnet_cell} | {ir_cell} |")
    lines.append("")
    return lines


def _check_axis_b(buy_mgr, final_df, new_watchlist, notifier) -> None:
    candidates = buy_mgr.get_tickers()
    if not candidates:
        return

    watch_set = set(new_watchlist)
    for ticker in candidates:
        if ticker not in watch_set:
            count = buy_mgr.mark_caution(ticker)
            logger.info(f"  軸B劣化: {ticker} (caution_count={count})")
            if count >= 2:
                entry = next((c for c in buy_mgr.get_all() if c["ticker"] == ticker), {})
                buy_mgr.remove(ticker, reason="ファンダメンタルズ劣化（軸B・2回連続）")
                notifier.notify_sell_candidate_removed(
                    {"ticker": ticker, "name": entry.get("name", ticker), "close": entry.get("close")},
                    reason="ファンダメンタルズ劣化（週次スクリーニング2回連続条件外）",
                )
        else:
            buy_mgr.clear_caution(ticker)

    buy_mgr.write_markdown()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="マルチエージェント週次スクリーニングパイプライン")
    parser.add_argument("--dry-run", action="store_true", help="最初の30銘柄のみ処理（テスト用）")
    parser.add_argument("--force-refresh", action="store_true", help="キャッシュを無視して再取得")
    args = parser.parse_args()
    run_agent_weekly(dry_run=args.dry_run, force_refresh=args.force_refresh)
