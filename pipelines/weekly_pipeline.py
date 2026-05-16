"""
週次パイプライン: 毎週日曜日 8:00 実行
1. 全プライム銘柄取得（J-Quants）
2. Step1: 基本財務フィルタ（yfinance）
3. Step2: EPS・売上高・ROEフィルタ（J-Quants）+ FCF・財務健全性（yfinance）+ スコアリング
4. AIによる投資メモ・ベアケース生成（Claude）
5. weekly_moat_stocks.md 出力
6. LINE通知（ウォッチリスト変更）
"""
import argparse
import math
import os
import sys
import time
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.jquants_client import JQuantsClient, get_prime_tickers_fallback
from src.data.yfinance_client import YFinanceClient
from src.screener.step1_filter import apply_step1_filter
from src.screener.step2_analysis import apply_step2_analysis, format_step2_table
from src.ai_analyst.claude_analyzer import ClaudeAnalyzer
from src.notification.line_notifier import from_config as line_from_config
from src.utils.cache import Cache
from src.utils.logger import get_logger

logger = get_logger("weekly_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


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

    if force_refresh:
        for key in ["step1_results", "step2_results", "watchlist"]:
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

    # --- Step1: 基本財務フィルタ ---
    logger.info("【Step1】基本財務フィルタ（yfinance）")
    import pandas as pd

    step1_cached = cache.get("step1_results", ttl_hours=cfg["data"]["cache_ttl_hours"]["fundamentals"])
    if step1_cached:
        step1_df = pd.DataFrame(step1_cached)
        logger.info(f"Step1: キャッシュから取得 ({len(step1_df)}件)")
    else:
        s1 = cfg["screener"]["step1"]
        basic_info_list = yf_client.get_basic_info_batch(tickers, batch_size=cfg["data"]["batch_size"])
        step1_df = apply_step1_filter(
            basic_info_list,
            min_market_cap=s1["min_market_cap_jpy"],
            min_revenue_growth=s1["min_revenue_growth"],
            min_operating_margin=s1["min_operating_margin"],
            min_pbr=s1["min_pbr"],
            min_equity_ratio=s1["min_equity_ratio"],
        )
        cache.set("step1_results", step1_df.to_dict(orient="records"))

    step1_tickers = step1_df["ticker"].tolist()

    # --- Step2-前処理: J-Quants財務諸表取得 ---
    logger.info("【Step2-前処理】J-Quants財務諸表取得（EPS・売上高・ROE）")
    eps_series_map = {}

    if jq_client:
        # Step1通過銘柄の4桁コードを5桁コードに変換
        step1_codes = []
        ticker_to_code = {}
        for ticker in step1_tickers:
            code4 = ticker.replace(".T", "")
            code5 = code4 + "0"
            step1_codes.append(code5)
            ticker_to_code[ticker] = code5

        eps_series_map_by_code = jq_client.get_statements_batch(
            step1_codes,
            sleep_sec=cfg["api"]["jquants"].get("rate_limit_delay", 0.15),
        )
        # ticker形式に変換
        for ticker, code5 in ticker_to_code.items():
            eps_series_map[ticker] = eps_series_map_by_code.get(code5, {"annual": [], "quarterly": []})
    else:
        logger.warning("J-Quants未設定: EPS/売上高フィルタをスキップします")

    # --- Step2: 精緻分析 ---
    logger.info("【Step2】精緻分析（EPS・売上・ROE・FCF・スコアリング）")
    step2_cached = cache.get("step2_results", ttl_hours=cfg["data"]["cache_ttl_hours"]["fundamentals"])

    if step2_cached:
        step2_df = pd.DataFrame(step2_cached)
        logger.info(f"Step2: キャッシュから取得 ({len(step2_df)}件)")
    else:
        logger.info(f"Step2詳細財務取得中: {len(step1_tickers)}銘柄...")
        detailed = []
        for i, ticker in enumerate(step1_tickers):
            if i % 20 == 0:
                logger.info(f"  詳細財務取得中: {i + 1}/{len(step1_tickers)}")
            detailed.append(yf_client.get_detailed_financials(ticker))
            if (i + 1) % 30 == 0:
                time.sleep(cfg["data"]["batch_sleep_sec"])

        s2 = cfg["screener"]["step2"]
        step2_df = apply_step2_analysis(
            detailed,
            eps_series_map=eps_series_map if eps_series_map else None,
            min_roe=s2["min_roe"],
            min_eps_annual_growth=s2.get("min_eps_annual_growth", 0.25),
            min_eps_quarterly_growth=s2.get("min_eps_quarterly_growth", 0.25),
            min_revenue_growth_latest=s2.get("min_revenue_growth_latest", 0.25),
            min_fcf_positive_years=s2["min_fcf_positive_years"],
            min_cf_quality=s2["min_cf_quality"],
            max_net_debt_ebitda=s2["max_net_debt_ebitda"],
            max_payout_ratio=s2["max_payout_ratio"],
            top_n=s2["top_n_candidates"],
            weights=cfg["screener"]["weights"],
        )
        cache.set("step2_results", step2_df.to_dict(orient="records"))

    # --- Step3: AI分析 ---
    logger.info("【Step3】AI投資メモ生成")
    top5 = step2_df.head(5)
    stock_analyses = []

    for _, row in top5.iterrows():
        stock_dict = row.to_dict()
        logger.info(f"  AI分析中: {stock_dict.get('name', row['ticker'])}")
        memo = analyzer.generate_investment_memo(stock_dict)
        bear = analyzer.generate_bear_case(stock_dict)
        stock_analyses.append({"data": stock_dict, "memo": memo, "bear_case": bear})
        time.sleep(1)

    # --- Step4: レポート出力 ---
    logger.info("【Step4】レポート生成")
    report = _build_weekly_report(step2_df, stock_analyses, dry_run)
    output_path = cfg["output"]["weekly_report"]
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"週次レポートを出力しました: {output_path}")

    # --- Step5: ウォッチリスト更新・LINE通知 ---
    new_watchlist = step2_df["ticker"].head(20).tolist()
    prev_watchlist = cache.get("watchlist", ttl_hours=9999) or []
    cache.set("watchlist", new_watchlist)
    logger.info(f"ウォッチリスト更新: {new_watchlist}")

    # 銘柄名マップ
    ticker_names = {row["ticker"]: row.get("name", row["ticker"]) for _, row in step2_df.iterrows()}

    notifier.notify_watchlist_update(
        new_watchlist=new_watchlist,
        prev_watchlist=prev_watchlist,
        ticker_names=ticker_names,
    )

    logger.info("週次パイプライン完了")
    return step2_df


def _is_nan(val) -> bool:
    try:
        return math.isnan(float(val))
    except (TypeError, ValueError):
        return False


def _build_weekly_report(step2_df, stock_analyses: list, dry_run: bool) -> str:
    now = datetime.now().strftime("%Y年%m月%d日")
    dry_label = "【DRY-RUN】" if dry_run else ""

    all_cond = step2_df[step2_df.get("classification", "") == "全条件"] if "classification" in step2_df.columns else step2_df
    eps_only = step2_df[step2_df.get("classification", "") == "EPS条件のみ"] if "classification" in step2_df.columns else step2_df.iloc[0:0]

    lines = [
        f"# {dry_label}週次スクリーニングレポート",
        f"生成日時: {now}",
        "",
        "---",
        "",
        "## スクリーニング結果サマリー",
        "",
        f"- **Step2通過銘柄数**: {len(step2_df)}社",
        f"  - 全条件銘柄: {len(all_cond)}社",
        f"  - EPS条件のみ銘柄: {len(eps_only)}社",
        f"- **おすすめ銘柄（Top5）**: {', '.join(step2_df.head(5)['ticker'].tolist())}",
        "",
        "---",
        "",
        "## Top20 スコアランキング",
        "",
        format_step2_table(step2_df),
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
        score = d.get("total_score")
        label = d.get("classification", "")
        roe = d.get("roe")
        cagr = d.get("revenue_cagr")
        margin = d.get("operating_margins")
        nd = d.get("net_debt_ebitda")

        lines += [
            f"### {i}. {name}（{ticker}）　`{label}`",
            "",
            f"**総合スコア**: {score:.1f}/10  |  **セクター**: {d.get('sector', 'N/A')}",
            "",
            "| 指標 | 値 |",
            "|------|-----|",
            f"| ROE | {roe:.1%} |" if roe is not None and not _is_nan(roe) else "| ROE | N/A |",
            f"| 売上高CAGR（3年） | {cagr:.1%} |" if cagr is not None and not _is_nan(cagr) else "| 売上高CAGR | N/A |",
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
            "---",
            "",
        ]

    lines += [
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
