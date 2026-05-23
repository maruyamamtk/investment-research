"""
Compsパイプライン: ウォッチリスト上位銘柄の同業他社比較分析
- stage2_cache からスコア上位銘柄を取得
- 各銘柄について同業他社5社との10指標比較表を生成
- output/comps_YYYYMMDD.md に出力
"""
import argparse
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.yfinance_client import YFinanceClient
from src.screener.comps_analyzer import generate_comps_report
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("comps_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except FileNotFoundError:
        cfg = {}
    override_credentials(cfg)
    return cfg


def run_comps(top_n: int = 5, dry_run: bool = False):
    logger.info("=" * 60)
    logger.info(f"Compsパイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    yf_client = YFinanceClient(cache=cache, batch_sleep=cfg["data"]["batch_sleep_sec"])

    # stage2_cache から候補銘柄を取得（ピア選定に使用）
    candidates_raw = cache.get("stage2_results", ttl_hours=168)
    if not candidates_raw:
        # フォールバック: stage1_cache
        candidates_raw = cache.get("stage1_results", ttl_hours=168)
    if not candidates_raw:
        logger.warning("stage1/stage2キャッシュが見つかりません。週次パイプラインを先に実行してください。")
        candidates_raw = []

    # リスト形式に正規化（DataFrameのto_dict()結果はlist[dict]）
    if isinstance(candidates_raw, list):
        candidates = candidates_raw
    else:
        candidates = []

    logger.info(f"候補銘柄プール: {len(candidates)}件")

    # ウォッチリストからtop_N銘柄を取得
    watchlist = cache.get("watchlist", ttl_hours=168)
    if not watchlist:
        logger.warning("ウォッチリストが見つかりません。候補プールの先頭を使用します。")
        watchlist = [c["ticker"] for c in candidates[:top_n] if "ticker" in c]
    target_tickers = watchlist[:top_n]
    logger.info(f"Comps対象: {target_tickers}")

    if not target_tickers:
        logger.error("対象銘柄が1件もありません。終了します。")
        return

    # 各銘柄のCompsレポートを生成
    sleep_sec = 0.5 if dry_run else cfg["data"]["batch_sleep_sec"]
    sections = []
    for ticker in target_tickers:
        try:
            md = generate_comps_report(
                target_ticker=ticker,
                candidates=candidates,
                yf_client=yf_client,
                n_peers=5,
                sleep_sec=sleep_sec,
            )
            sections.append(md)
            logger.info(f"  {ticker}: Comps生成完了")
        except Exception as e:
            logger.error(f"  {ticker}: Comps生成失敗: {e}")
            sections.append(f"## {ticker} - エラー\n\n{e}\n\n---\n")

    # Markdown 出力
    date_str = datetime.now().strftime("%Y%m%d")
    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"comps_{date_str}.md")

    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    dry_label = "【DRY-RUN】" if dry_run else ""
    content = "\n".join([
        f"# {dry_label}Comps分析レポート",
        f"生成日時: {now}",
        f"対象銘柄数: {len(sections)}社",
        "",
        "---",
        "",
    ] + sections)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Compsレポートを出力: {out_path}")
    logger.info("Compsパイプライン完了")
    return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Comps分析パイプライン")
    parser.add_argument("--top-n", type=int, default=5, help="上位N銘柄を対象（デフォルト: 5）")
    parser.add_argument("--dry-run", action="store_true", help="テスト用（APIスリープ短縮）")
    args = parser.parse_args()
    run_comps(top_n=args.top_n, dry_run=args.dry_run)
