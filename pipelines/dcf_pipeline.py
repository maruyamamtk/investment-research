"""
DCFパイプライン: ウォッチリスト上位銘柄の簡易DCFモデル自動計算
- stage2_cache / ウォッチリストからスコア上位銘柄を取得
- 各銘柄の WACC・TV・フェアバリュー試算・感度分析マトリクスを生成
- output/dcf_YYYYMMDD.md に出力
"""
import argparse
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.yfinance_client import YFinanceClient
from src.screener.dcf_calculator import (
    DEFAULT_RISK_FREE_RATE,
    DEFAULT_TERMINAL_GROWTH,
    DEFAULT_MARKET_PREMIUM,
    generate_dcf_report,
)
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("dcf_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    override_credentials(cfg)
    return cfg


def run_dcf(
    top_n: int = 5,
    dry_run: bool = False,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    market_premium: float = DEFAULT_MARKET_PREMIUM,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
):
    logger.info("=" * 60)
    logger.info(f"DCFパイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    sleep_sec = 0.5 if dry_run else cfg["data"]["batch_sleep_sec"]
    yf_client = YFinanceClient(cache=cache, batch_sleep=sleep_sec)

    # ウォッチリストから対象銘柄を取得
    watchlist = cache.get("watchlist", ttl_hours=168)
    if not watchlist:
        candidates_raw = cache.get("stage2_results", ttl_hours=168) or cache.get("stage1_results", ttl_hours=168) or []
        watchlist = [c["ticker"] for c in candidates_raw if "ticker" in c]

    target_tickers = watchlist[:top_n]
    logger.info(f"DCF対象: {target_tickers}")

    if not target_tickers:
        logger.error("対象銘柄が1件もありません。終了します。")
        return

    sections = []
    for ticker in target_tickers:
        try:
            md = generate_dcf_report(
                target_ticker=ticker,
                yf_client=yf_client,
                risk_free_rate=risk_free_rate,
                market_premium=market_premium,
                terminal_growth=terminal_growth,
            )
            sections.append(md)
            logger.info(f"  {ticker}: DCF生成完了")
        except Exception as e:
            logger.error(f"  {ticker}: DCF生成失敗: {e}")
            sections.append(f"## {ticker} - エラー\n\n{e}\n\n---\n")

    # Markdown 出力
    date_str = datetime.now().strftime("%Y%m%d")
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"dcf_{date_str}.md")

    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    dry_label = "【DRY-RUN】" if dry_run else ""
    content = "\n".join([
        f"# {dry_label}DCF分析レポート",
        f"生成日時: {now}",
        f"対象銘柄数: {len(sections)}社",
        f"リスクフリーレート: {risk_free_rate * 100:.1f}%  |  永続成長率: {terminal_growth * 100:.1f}%",
        "",
        "---",
        "",
    ] + sections)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"DCFレポートを出力: {out_path}")
    logger.info("DCFパイプライン完了")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DCFモデル自動計算パイプライン")
    parser.add_argument("--top-n", type=int, default=5, help="上位N銘柄（デフォルト: 5）")
    parser.add_argument("--dry-run", action="store_true", help="テスト用（APIスリープ短縮）")
    parser.add_argument("--risk-free-rate", type=float, default=DEFAULT_RISK_FREE_RATE,
                        help="リスクフリーレート（デフォルト: 0.015）")
    parser.add_argument("--market-premium", type=float, default=DEFAULT_MARKET_PREMIUM,
                        help="市場リスクプレミアム（デフォルト: 0.05）")
    parser.add_argument("--terminal-growth", type=float, default=DEFAULT_TERMINAL_GROWTH,
                        help="永続成長率（デフォルト: 0.01）")
    args = parser.parse_args()
    run_dcf(
        top_n=args.top_n,
        dry_run=args.dry_run,
        risk_free_rate=args.risk_free_rate,
        market_premium=args.market_premium,
        terminal_growth=args.terminal_growth,
    )
