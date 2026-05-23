"""
ポートフォリオ管理・リバランス提案パイプライン

config/portfolio.yaml の保有銘柄を読み込み、
週次スクリーニング結果（watchlist）と照合してリバランス提案を生成する。

出力:
  output/portfolio_report.md  - ポートフォリオ状況 + リバランス提案レポート
  LINE通知（保有なし or リバランス提案あり）
"""
import argparse
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.portfolio.portfolio_manager import PortfolioManager
from src.portfolio.rebalance_advisor import RebalanceAdvisor
from src.data.yfinance_client import YFinanceClient
from src.notification.line_notifier import from_config as line_from_config
from src.utils.cache import Cache
from src.utils.credentials import override_credentials
from src.utils.logger import get_logger

logger = get_logger("portfolio_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    override_credentials(cfg)
    return cfg


def run_portfolio(
    portfolio_path: str = "config/portfolio.yaml",
    watchlist_csv: str = None,
    dry_run: bool = False,
) -> dict:
    """
    ポートフォリオ評価・リバランス提案を実行する。

    portfolio_path: 保有銘柄YAMLファイルのパス
    watchlist_csv:  週次スクリーニング結果CSVのパス（省略時はキャッシュから読み込み）
    dry_run:        Trueの場合は通知を送信しない
    """
    logger.info("=" * 60)
    logger.info("ポートフォリオ管理パイプライン開始")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    yf_client = YFinanceClient(cache=cache, batch_sleep=cfg["data"]["batch_sleep_sec"])
    notifier = line_from_config(cfg)

    # --- Step1: ポートフォリオ読み込み ---
    logger.info("【Step1】ポートフォリオ読み込み")
    pm = PortfolioManager(portfolio_path=portfolio_path, yf_client=yf_client)

    if pm.is_empty():
        logger.info(f"保有銘柄が登録されていません。{portfolio_path} に銘柄を追加してください。")
        _write_empty_report(cfg)
        return {"status": "empty", "holdings": 0}

    # --- Step2: 現在価格取得 ---
    logger.info("【Step2】現在価格取得（yfinance）")
    pm.refresh_prices()

    # --- Step3: ウォッチリスト読み込み ---
    logger.info("【Step3】ウォッチリスト読み込み")
    watchlist_df = _load_watchlist(watchlist_csv, cache, cfg)

    # --- Step4: リバランス提案生成 ---
    logger.info("【Step4】リバランス提案生成")
    advisor = RebalanceAdvisor(portfolio_manager=pm, watchlist_df=watchlist_df)
    suggestions = advisor.generate(top_n_new=5)

    actionable = [s for s in suggestions if s.action != "HOLD"]
    logger.info(f"提案件数: {len(suggestions)}件（うちアクション要 {len(actionable)}件）")

    # --- Step5: レポート出力 ---
    logger.info("【Step5】レポート出力")
    report = advisor.build_report(suggestions)
    output_path = cfg["output"].get("portfolio_report", "output/portfolio_report.md")
    _makedirs_safe(output_path)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    logger.info(f"ポートフォリオレポートを出力: {output_path}")

    # --- Step6: LINE通知 ---
    if not dry_run and actionable:
        logger.info("【Step6】LINE通知（リバランス提案あり）")
        cost = advisor.estimate_total_rebalance_cost(suggestions)
        notifier.notify_rebalance_suggestion(
            suggestions=actionable,
            portfolio_summary={
                "total_current_value": pm.total_current_value,
                "total_unrealized_pnl": pm.total_unrealized_pnl,
            },
            cost_summary=cost,
        )
    else:
        logger.info("LINE通知: アクション提案なし or dry-run のためスキップ")

    logger.info("ポートフォリオ管理パイプライン完了")
    return {
        "status": "ok",
        "holdings": len(pm.holdings),
        "suggestions": len(suggestions),
        "actionable": len(actionable),
        "report_path": output_path,
    }


def _makedirs_safe(path: str) -> None:
    """ファイルパスのディレクトリを安全に作成する（フラットなファイル名でも安全）。"""
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)


def _load_watchlist(watchlist_csv, cache, cfg):
    """ウォッチリストを読み込む（CSV優先 → キャッシュフォールバック）。"""
    import pandas as pd

    if watchlist_csv and os.path.exists(watchlist_csv):
        logger.info(f"  ウォッチリストCSV読み込み: {watchlist_csv}")
        return pd.read_csv(watchlist_csv)

    # キャッシュから stage2_results を取得（設定ファイルの TTL を優先）
    ttl = cfg.get("data", {}).get("cache_ttl_hours", {}).get("fundamentals", 168)
    cached = cache.get("stage2_results", ttl_hours=ttl)
    if cached:
        df = pd.DataFrame(cached)
        logger.info(f"  ウォッチリストをキャッシュから取得: {len(df)}銘柄")
        return df

    logger.warning("  ウォッチリストが見つかりません（週次パイプラインを先に実行してください）")
    return None


def _write_empty_report(cfg):
    """保有銘柄が空の場合のレポートを出力する。"""
    output_path = cfg["output"].get("portfolio_report", "output/portfolio_report.md")
    _makedirs_safe(output_path)
    content = (
        "# ポートフォリオ・リバランスレポート\n\n"
        "保有銘柄が登録されていません。\n\n"
        "`config/portfolio.yaml` に保有銘柄を追加してください。\n"
        "フォーマットは `config/portfolio.yaml.example` を参照してください。\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ポートフォリオ管理・リバランス提案パイプライン")
    parser.add_argument(
        "--portfolio",
        default="config/portfolio.yaml",
        help="保有銘柄YAMLファイルのパス",
    )
    parser.add_argument(
        "--watchlist-csv",
        default=None,
        help="週次スクリーニング結果CSVのパス（省略時はキャッシュから読み込み）",
    )
    parser.add_argument("--dry-run", action="store_true", help="LINE通知を送信しない")
    args = parser.parse_args()

    result = run_portfolio(
        portfolio_path=args.portfolio,
        watchlist_csv=args.watchlist_csv,
        dry_run=args.dry_run,
    )
    print(f"完了: {result}")
