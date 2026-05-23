"""
週次パイプライン: 毎週日曜日 8:00 実行
1. 全プライム銘柄取得（J-Quants）
2. 段階1: yfinance基本情報で5次元速報スコア → 上位200〜400社に絞り込み
3. 段階2: J-Quants + yfinance詳細で8次元精緻スコア → 13次元統合スコア（0〜100点）
4. AIによる投資メモ・ベアケース生成（Claude）
5. watch_list.md 出力（後方互換: weekly_moat_stocks.md シンボリックリンク）
6. ③売却判断 軸B: 購入候補リストのファンダメンタルズ再確認
7. LINE通知（ウォッチリスト変更・軸B除外）
"""
import argparse
import math
import os
import sys
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.jquants_client import JQuantsClient, get_prime_tickers_fallback
from src.data.yfinance_client import YFinanceClient
from src.screener.unified_scorer import (
    calculate_stage1_scores,
    filter_stage1_candidates,
    calculate_stage2_scores,
    calculate_total_score,
)
from src.screener.step2_analysis import format_step2_table
from src.screener.buy_candidates import BuyCandidatesManager
from src.ai_analyst.claude_analyzer import ClaudeAnalyzer
from src.notification.line_notifier import from_config as line_from_config
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("weekly_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Cloud Run: Secret Managerから注入された環境変数で上書き
    override_credentials(cfg)
    return cfg


def run_weekly(dry_run: bool = False, force_refresh: bool = False):
    logger.info("=" * 60)
    logger.info(f"週次パイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    yf_client = YFinanceClient(cache=cache, batch_sleep=cfg["data"]["batch_sleep_sec"])
    jq_email = cfg["api"]["jquants"]["email"]
    jq_pass = cfg["api"]["jquants"]["password"]
    analyzer = ClaudeAnalyzer(
        api_key=cfg["api"]["gemini"]["api_key"],
        model=cfg["api"]["gemini"]["model_weekly"],
    )
    notifier = line_from_config(cfg)
    buy_mgr = BuyCandidatesManager(
        cache_path=cfg["output"].get("buy_candidates_cache", "cache/buy_candidates.json"),
        md_path=cfg["output"].get("buy_candidates_md", "output/buy_candidates.md"),
    )

    if force_refresh:
        for key in ["stage1_results", "stage2_results", "watchlist"]:
            cache.invalidate(key)

    # --- Step0: 銘柄リスト取得 ---
    logger.info("【Step0】銘柄マスター取得")
    if jq_email and jq_pass:
        jq_client = JQuantsClient(email=jq_email, password=jq_pass, cache=cache)
        tickers = jq_client.get_prime_tickers()
        jq_codes = jq_client.get_prime_codes()
    else:
        jq_client = None
        tickers = get_prime_tickers_fallback()
        jq_codes = [t.replace(".T", "") + "0" for t in tickers]

    if dry_run:
        logger.info("DRY-RUN: 最初の30銘柄のみ処理します")
        tickers = tickers[:30]
        jq_codes = jq_codes[:30]

    logger.info(f"対象銘柄数: {len(tickers)}件")

    # --- 段階1: yfinance基本情報で速報スコア計算 ---
    logger.info("【段階1】速報スコア計算（yfinance 5次元）")
    stage1_cached = cache.get("stage1_results", ttl_hours=cfg["data"]["cache_ttl_hours"]["fundamentals"])
    if stage1_cached:
        stage1_filtered = pd.DataFrame(stage1_cached)
        logger.info(f"段階1: キャッシュから取得 ({len(stage1_filtered)}件)")
    else:
        basic_info_list = yf_client.get_basic_info_batch(tickers, batch_size=cfg["data"]["batch_size"])
        stage1_df = calculate_stage1_scores(basic_info_list)
        stage1_filtered = filter_stage1_candidates(stage1_df)
        cache.set("stage1_results", stage1_filtered.to_dict(orient="records"))

    stage1_tickers = stage1_filtered["ticker"].tolist()

    # --- 段階2-前処理: J-Quants財務諸表取得 ---
    logger.info("【段階2-前処理】J-Quants財務諸表取得（EPS・売上高・ROE）")
    eps_series_map = {}

    if jq_client:
        step1_codes = []
        ticker_to_code = {}
        for ticker in stage1_tickers:
            code4 = ticker.replace(".T", "")
            code5 = code4 + "0"
            step1_codes.append(code5)
            ticker_to_code[ticker] = code5

        eps_series_map_by_code = jq_client.get_statements_batch(
            step1_codes,
            sleep_sec=cfg["api"]["jquants"].get("rate_limit_delay", 0.15),
        )
        for ticker, code5 in ticker_to_code.items():
            eps_series_map[ticker] = eps_series_map_by_code.get(code5, {"annual": [], "quarterly": []})
    else:
        logger.warning("J-Quants未設定: J-Quantsデータなしで段階2スコアを計算します（欠損値=5点補完）")

    # --- 段階2: 精緻スコア計算・13次元統合スコア（0〜100点） ---
    logger.info("【段階2】精緻スコア計算（J-Quants + yfinance 8次元）→ 統合スコア（0〜100点）")
    stage2_cached = cache.get("stage2_results", ttl_hours=cfg["data"]["cache_ttl_hours"]["fundamentals"])

    if stage2_cached:
        final_df = pd.DataFrame(stage2_cached)
        if "total_score_100" not in final_df.columns and "total_score" in final_df.columns:
            # 旧フォーマットのキャッシュには total_score_100 が存在しない場合がある
            final_df = calculate_total_score(final_df, top_n=cfg["screener"]["step2"].get("top_n_candidates", 20))
        logger.info(f"段階2: キャッシュから取得 ({len(final_df)}件)")
    else:
        logger.info(f"詳細財務取得中: {len(stage1_tickers)}銘柄...")
        detailed_fins_map = {}
        for i, ticker in enumerate(stage1_tickers):
            if i % 20 == 0:
                logger.info(f"  詳細財務取得中: {i + 1}/{len(stage1_tickers)}")
            detailed_fins_map[ticker] = yf_client.get_detailed_financials(ticker)
            if (i + 1) % 30 == 0:
                time.sleep(cfg["data"]["batch_sleep_sec"])

        stage2_df = calculate_stage2_scores(stage1_filtered, eps_series_map, detailed_fins_map)
        final_df = calculate_total_score(stage2_df, top_n=cfg["screener"]["step2"].get("top_n_candidates", 20))
        cache.set("stage2_results", final_df.to_dict(orient="records"))

    # --- Step3: AI分析 ---
    logger.info("【Step3】AI投資メモ生成・定性分析（Q1〜Q5）")
    top5 = final_df.head(5)
    stock_analyses = []

    for _, row in top5.iterrows():
        stock_dict = row.to_dict()
        name = stock_dict.get('name', row['ticker'])
        logger.info(f"  AI分析中: {name}")
        memo = analyzer.generate_investment_memo(stock_dict)
        bear = analyzer.generate_bear_case(stock_dict)
        qualitative = analyzer.analyze_qualitative(
            ticker=row["ticker"],
            company_name=name,
            stock_data=stock_dict,
        )
        stock_analyses.append({
            "data": stock_dict,
            "memo": memo,
            "bear_case": bear,
            "qualitative": qualitative,
        })
        time.sleep(1)

    # --- Step4: レポート出力 ---
    logger.info("【Step4】レポート生成")
    report = _build_weekly_report(final_df, stock_analyses, dry_run)
    output_path = cfg["output"]["weekly_report"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"週次レポートを出力しました: {output_path}")

    # 後方互換: weekly_moat_stocks.md → watch_list.md のシンボリックリンク
    legacy_path = cfg["output"].get("weekly_report_legacy", "output/weekly_moat_stocks.md")
    _ensure_legacy_symlink(output_path, legacy_path)

    # --- Step5: ウォッチリスト更新・LINE通知 ---
    new_watchlist = final_df["ticker"].head(20).tolist()
    prev_watchlist = cache.get("watchlist", ttl_hours=9999) or []
    cache.set("watchlist", new_watchlist)
    logger.info(f"ウォッチリスト更新: {new_watchlist}")

    ticker_names = {row["ticker"]: row.get("name", row["ticker"]) for _, row in final_df.iterrows()}

    notifier.notify_watchlist_update(
        new_watchlist=new_watchlist,
        prev_watchlist=prev_watchlist,
        ticker_names=ticker_names,
    )

    # --- Step6: 軸B ファンダメンタルズ再確認 ---
    if not dry_run:
        logger.info("【Step6】③売却判断 軸B: 購入候補リストのファンダメンタルズ再確認")
        _check_axis_b(buy_mgr, final_df, new_watchlist, notifier)

    logger.info("週次パイプライン完了")
    return final_df


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


def _check_axis_b(
    buy_mgr: "BuyCandidatesManager",
    final_df,
    new_watchlist: list[str],
    notifier,
) -> None:
    """
    軸B: 購入候補リスト内銘柄が①監視対象条件を満たしているか確認する。
    - 上位20社から脱落した場合: caution_count += 1
    - caution_count >= 2 の場合: 除外 + LINE通知
    - 引き続き条件を満たす場合: caution_count リセット
    """
    candidates = buy_mgr.get_tickers()
    if not candidates:
        logger.info("  購入候補リストは空 — 軸B確認をスキップ")
        return

    watch_set = set(new_watchlist)

    for ticker in candidates:
        degraded = ticker not in watch_set

        if degraded:
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
    logger.info("  軸B確認完了")


def _format_qualitative_section(qualitative: Optional[dict]) -> list:
    """定性分析（Q1〜Q5）をMarkdownテーブル形式にフォーマットして行リストで返す。"""
    if not qualitative:
        return []

    q_labels = {
        "q1": "Q1 事業モデル・競争優位性",
        "q2": "Q2 経営陣・ガバナンス",
        "q3": "Q3 市場環境・成長ポテンシャル",
        "q4": "Q4 顧客基盤・サプライチェーン",
        "q5": "Q5 組織力・企業文化",
    }

    lines = [
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

    score = qualitative.get("overall_score")
    score_str = f"{score:.1f} / 10" if score is not None else "N/A"
    overall = qualitative.get("overall_comment", "")
    lines += [
        "",
        f"**総合定性スコア: {score_str}**",
        "",
        overall,
        "",
    ]
    return lines


def _is_nan(val) -> bool:
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return False


def _build_info_sources_section(df: pd.DataFrame) -> list:
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


def _build_weekly_report(final_df, stock_analyses: list, dry_run: bool) -> str:
    now = datetime.now().strftime("%Y年%m月%d日")
    dry_label = "【DRY-RUN】" if dry_run else ""

    lines = [
        f"# {dry_label}週次スクリーニングレポート",
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
        ] + _format_qualitative_section(analysis.get("qualitative")) + [
            "---",
            "",
        ]

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="週次スクリーニングパイプライン")
    parser.add_argument("--dry-run", action="store_true", help="最初の30銘柄のみ処理（テスト用）")
    parser.add_argument("--force-refresh", action="store_true", help="キャッシュを無視して再取得")
    args = parser.parse_args()
    run_weekly(dry_run=args.dry_run, force_refresh=args.force_refresh)
