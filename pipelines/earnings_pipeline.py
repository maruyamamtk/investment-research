"""
決算レビューパイプライン: ウォッチリスト銘柄の決算Beat/Miss・ガイダンス変化を解析
- ウォッチリストから対象銘柄を取得
- 各銘柄のEPS・売上のBeat/Miss判定とガイダンス変化を解析
- output/earnings_review_YYYYMMDD.md に出力
- LINE通知で結果を送信
"""
import argparse
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.yfinance_client import YFinanceClient
from src.notification import line_notifier
from src.screener.earnings_reviewer import generate_earnings_report, get_earnings_data, determine_beat_miss
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.gcs_report import upload_report_to_gcs
from src.utils.logger import get_logger

logger = get_logger("earnings_pipeline")

PREV_ESTIMATES_CACHE_KEY = "earnings_prev_estimates"


def load_config(path: str = "config/settings.yaml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    override_credentials(cfg)
    return cfg


def run_earnings_review(
    top_n: int = 5,
    dry_run: bool = False,
    tickers: list[str] = None,
):
    logger.info("=" * 60)
    logger.info(f"決算レビューパイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    sleep_sec = 0.5 if dry_run else cfg["data"]["batch_sleep_sec"]
    yf_client = YFinanceClient(cache=cache, batch_sleep=sleep_sec)
    notifier = line_notifier.from_config(cfg)

    # 対象銘柄を決定
    if tickers:
        target_tickers = tickers
    else:
        watchlist = cache.get("watchlist", ttl_hours=168)
        if not watchlist:
            candidates_raw = (
                cache.get("stage2_results", ttl_hours=168)
                or cache.get("stage1_results", ttl_hours=168)
                or []
            )
            watchlist = [c["ticker"] for c in candidates_raw if "ticker" in c]
        target_tickers = watchlist[:top_n]

    logger.info(f"決算レビュー対象: {target_tickers}")

    if not target_tickers:
        logger.error("対象銘柄が1件もありません。終了します。")
        return

    # 前回EPS予想をキャッシュから復元（ガイダンス変化検出用）
    prev_estimates: dict = cache.get(PREV_ESTIMATES_CACHE_KEY, ttl_hours=24 * 90) or {}
    new_estimates: dict = {}

    sections = []
    summaries = []

    for ticker in target_tickers:
        try:
            # データを1回だけ取得し、レポート生成・サマリー収集の両方で再利用する
            data = get_earnings_data(ticker, yf_client)

            md = generate_earnings_report(
                target_ticker=ticker,
                yf_client=yf_client,
                prev_estimates=prev_estimates,
                earnings_data=data,
            )
            sections.append(md)
            logger.info(f"  {ticker}: 決算レビュー生成完了")

            # サマリー情報を収集（LINE通知用）
            eps_hist = data.get("eps_history", [])
            if eps_hist:
                latest = eps_hist[0]
                verdict = determine_beat_miss(latest.get("actual"), latest.get("estimate"))
                summaries.append({
                    "ticker": ticker,
                    "name": data.get("name", ticker),
                    "verdict": verdict,
                    "surprise_pct": latest.get("surprise_pct"),
                    "quarter": latest.get("quarter", ""),
                })

            # 今回のEPS予想を記録
            fwd_eps = data.get("current_eps_estimate")
            if fwd_eps is not None:
                new_estimates[ticker] = fwd_eps

        except Exception as e:
            logger.error(f"  {ticker}: 決算レビュー生成失敗: {e}")
            sections.append(f"## {ticker} - エラー\n\n{e}\n\n---\n")

    # 新しいEPS予想をキャッシュに保存
    merged_estimates = {**prev_estimates, **new_estimates}
    cache.set(PREV_ESTIMATES_CACHE_KEY, merged_estimates)

    # Markdown 出力
    date_str = datetime.now().strftime("%Y%m%d")
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"earnings_review_{date_str}.md")

    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    dry_label = "【DRY-RUN】" if dry_run else ""
    content = "\n".join([
        f"# {dry_label}決算レビューレポート",
        f"生成日時: {now}",
        f"対象銘柄数: {len(sections)}社",
        "",
        "---",
        "",
    ] + sections)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    logger.info(f"決算レビューレポートを出力: {out_path}")
    if not dry_run:
        upload_report_to_gcs(out_path, logger)

    # LINE 通知
    if not dry_run and summaries:
        notifier.notify_earnings_review(summaries)

    logger.info("決算レビューパイプライン完了")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="決算レビュー自動化パイプライン")
    parser.add_argument("--top-n", type=int, default=5, help="上位N銘柄（デフォルト: 5）")
    parser.add_argument("--dry-run", action="store_true", help="テスト用（LINE通知・APIスリープ短縮）")
    parser.add_argument("--tickers", nargs="+", help="対象銘柄を直接指定（例: 7203.T 9984.T）")
    args = parser.parse_args()
    run_earnings_review(
        top_n=args.top_n,
        dry_run=args.dry_run,
        tickers=args.tickers,
    )
