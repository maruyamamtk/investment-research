"""
日次パイプライン: 平日 19:30（東証閉場後）実行
1. ウォッチリスト（週次で選定）の取得
2. 市場レジーム判定（日経225 200日SMA）
3. 各銘柄の日足データ取得・テクニカル指標計算
4. 売買シグナル判定（フェイクアウト回避ロジック含む）
5. ②購入候補リスト管理（BUY追加 / SELL除外）
6. AIによるシグナル解説生成
7. daily_trade_signals.md / signals.csv 出力
8. LINE通知（BUY追加・SELL除外）
"""
import argparse
import csv
import os
import sys
import time
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.yfinance_client import YFinanceClient
from src.technical.signals import add_all_indicators, determine_signal, detect_market_regime, signal_emoji
from src.ai_analyst.claude_analyzer import ClaudeAnalyzer
from src.notification.line_notifier import from_config as line_from_config
from src.screener.buy_candidates import BuyCandidatesManager
from src.utils.cache import Cache
from src.utils.logger import get_logger

logger = get_logger("daily_pipeline")


def load_config(path: str = "config/settings.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_daily(ticker_override: str = None, dry_run: bool = False):
    logger.info("=" * 60)
    logger.info(f"日次パイプライン開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    cfg = load_config()
    cache = Cache(cache_dir="cache")
    yf_client = YFinanceClient(cache=cache, batch_sleep=cfg["data"]["batch_sleep_sec"])
    notifier = line_from_config(cfg)
    analyzer = ClaudeAnalyzer(
        api_key=cfg["api"]["gemini"]["api_key"],
        model=cfg["api"]["gemini"]["model_daily"],
    )
    buy_mgr = BuyCandidatesManager(
        cache_path=cfg["output"].get("buy_candidates_cache", "cache/buy_candidates.json"),
        md_path=cfg["output"].get("buy_candidates_md", "output/buy_candidates.md"),
    )

    # --- ウォッチリスト取得 ---
    if ticker_override:
        watchlist = [ticker_override]
        logger.info(f"指定銘柄モード: {ticker_override}")
    else:
        watchlist = cache.get("watchlist", ttl_hours=168)
        if not watchlist:
            logger.warning("ウォッチリストが見つかりません。週次パイプラインを先に実行してください。")
            logger.warning("デモ用にデフォルト銘柄を使用します。")
            watchlist = ["7203.T", "6758.T", "9432.T", "8306.T", "6861.T"]

    logger.info(f"対象銘柄: {watchlist}")

    # --- 市場レジーム判定（日経225）---
    market_regime = None
    if not dry_run:
        logger.info("市場レジーム判定（日経225）")
        n225_df = yf_client.get_price_history("^N225", days=300)
        if n225_df is not None and not n225_df.empty:
            market_regime = detect_market_regime(n225_df)
            logger.info(
                f"  レジーム: {market_regime['regime']} "
                f"（BUY閾値: {market_regime['buy_threshold']}点）"
            )

    tech_cfg = cfg["technical"]
    sig_cfg = tech_cfg["signal_thresholds"]
    results = []

    for ticker in watchlist:
        logger.info(f"処理中: {ticker}")

        # --- 株価履歴取得 ---
        df = yf_client.get_price_history(ticker, days=cfg["data"]["history_days"])
        if df is None or df.empty:
            logger.warning(f"  株価データ取得失敗: {ticker}")
            results.append({
                "ticker": ticker,
                "signal": "ERROR",
                "strength": 0,
                "close": None,
                "rsi14": None,
                "macd_hist": None,
                "reason": "株価データ取得失敗",
                "ai_comment": "",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "list_type": "buy_candidate" if buy_mgr.contains(ticker) else "watch",
            })
            continue

        # --- テクニカル指標計算 ---
        df = add_all_indicators(df)

        # --- 決算日取得（フェイクアウト回避）---
        earnings_date = yf_client.get_earnings_date(ticker) if not dry_run else None

        # --- シグナル判定 ---
        signal_result = determine_signal(
            df,
            rsi_oversold=sig_cfg["rsi_oversold"],
            rsi_overbought=sig_cfg["rsi_overbought"],
            volume_threshold=tech_cfg["volume_ratio_threshold"],
            earnings_date=earnings_date,
            earnings_hold_days=sig_cfg["earnings_hold_days"],
            market_regime=market_regime,
        )

        # --- AI解説生成 ---
        basic = yf_client.get_basic_info(ticker)
        name = basic.get("name", ticker)
        ai_comment = analyzer.explain_signal(ticker, name, signal_result) if not dry_run else "（DRY-RUN）"

        ind = signal_result["indicators"]
        sig = signal_result["signal"]
        list_type = "buy_candidate" if buy_mgr.contains(ticker) else "watch"

        results.append({
            "ticker": ticker,
            "name": name,
            "signal": sig,
            "strength": signal_result["strength"],
            "close": ind.get("close"),
            "sma5": ind.get("sma5"),
            "sma20": ind.get("sma20"),
            "rsi14": ind.get("rsi14"),
            "macd_hist": ind.get("macd_hist"),
            "volume_ratio": ind.get("volume_ratio"),
            "reasons": " / ".join(signal_result["reasons"]),
            "ai_comment": ai_comment,
            "date": signal_result["date"],
            "earnings_date": str(earnings_date.date()) if earnings_date else "N/A",
            "list_type": list_type,
        })

        logger.info(f"  {ticker}: {signal_emoji(sig)} {sig} (強度:{signal_result['strength']}/10)")
        time.sleep(1)

    # --- ②購入候補リスト更新（BUY追加 / SELL除外）---
    if not dry_run:
        removed_tickers = []
        added_tickers = []
        for r in results:
            ticker = r["ticker"]
            if r["signal"] == "ERROR":
                continue
            if r["signal"] == "BUY":
                buy_mgr.upsert(ticker, r)
                if r["list_type"] == "watch":
                    added_tickers.append(r)
            elif r["signal"] == "SELL" and buy_mgr.contains(ticker):
                buy_mgr.remove(ticker, reason="テクニカルSELLシグナル（軸A）")
                removed_tickers.append(r)

        buy_mgr.write_markdown()

        # --- LINE通知（BUY追加・SELL除外）---
        for r in added_tickers:
            notifier.notify_buy_candidate_added(r)
        for r in removed_tickers:
            notifier.notify_sell_candidate_removed(r)

    # --- Markdown 出力 ---
    md_path = cfg["output"]["daily_signals_md"]
    csv_path = cfg["output"]["daily_signals_csv"]
    os.makedirs(os.path.dirname(md_path), exist_ok=True)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_build_daily_report(results, dry_run, market_regime))
    logger.info(f"日次シグナル(Markdown)を出力: {md_path}")

    # --- CSV 出力 ---
    _write_csv(results, csv_path)
    logger.info(f"日次シグナル(CSV)を出力: {csv_path}")

    # --- LINE通知（全シグナルサマリー）---
    if not dry_run:
        notifier.notify_daily_signals(results)

    logger.info("日次パイプライン完了")
    return results


def _build_daily_report(results: list, dry_run: bool, market_regime: dict = None) -> str:
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    dry_label = "【DRY-RUN】" if dry_run else ""

    # シグナル別に分類
    buy = [r for r in results if r["signal"] == "BUY"]
    sell = [r for r in results if r["signal"] == "SELL"]
    hold = [r for r in results if r["signal"] == "HOLD"]
    watch = [r for r in results if r["signal"] == "WATCH"]
    error = [r for r in results if r["signal"] == "ERROR"]

    # 市場レジーム表示
    regime_line = ""
    if market_regime:
        regime_emoji = {"BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "🟡"}.get(market_regime["regime"], "⚪")
        regime_label = {"BULL": "強気相場", "BEAR": "弱気相場", "NEUTRAL": "中立相場"}.get(
            market_regime["regime"], market_regime["regime"]
        )
        regime_line = (
            f"**市場レジーム**: {regime_emoji} {regime_label} "
            f"（BUY閾値: {market_regime['buy_threshold']}点）"
        )

    lines = [
        f"# {dry_label}日次売買シグナルレポート",
        f"生成日時: {now}",
        "",
    ]
    if regime_line:
        lines += [regime_line, ""]
    lines += [
        "---",
        "",
        "## シグナルサマリー",
        "",
        f"| シグナル | 件数 |",
        f"|---------|------|",
        f"| 🟢 BUY  | {len(buy)}件 |",
        f"| 🔴 SELL | {len(sell)}件 |",
        f"| 🟡 HOLD | {len(hold)}件 |",
        f"| ⚪ WATCH| {len(watch)}件 |",
        "",
        "---",
        "",
    ]

    for group_label, group, emoji in [
        ("BUY シグナル（買いチャンス）", buy, "🟢"),
        ("SELL シグナル（利確・損切り）", sell, "🔴"),
        ("HOLD（決算前後・様子見）", hold, "🟡"),
        ("WATCH（中立・様子見）", watch, "⚪"),
    ]:
        if not group:
            continue
        lines += [f"## {emoji} {group_label}", ""]
        for r in group:
            lines += [
                f"### {r.get('name', r['ticker'])}（{r['ticker']}）",
                "",
                f"**シグナル強度**: {r['strength']}/10  |  "
                f"**現在値**: {r['close']}円  |  "
                f"**次回決算**: {r.get('earnings_date', 'N/A')}",
                "",
                "| 指標 | 値 |",
                "|------|-----|",
                f"| SMA5 / SMA20 | {r.get('sma5')} / {r.get('sma20')} |",
                f"| RSI(14) | {r.get('rsi14')} |",
                f"| MACDヒスト | {r.get('macd_hist')} |",
                f"| 出来高比率 | {r.get('volume_ratio')}x |",
                "",
                f"**判定理由**: {r.get('reasons', 'N/A')}",
                "",
                f"**AIコメント**: {r.get('ai_comment', '')}",
                "",
                "---",
                "",
            ]

    lines += [
        "## 免責事項",
        "",
        "> このシグナルは自動生成された情報提供を目的としたものであり、投資助言ではありません。",
        "> 投資判断はご自身の責任で行ってください。",
    ]

    return "\n".join(lines)


def _write_csv(results: list, path: str) -> None:
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    fieldnames = ["date", "ticker", "name", "signal", "strength", "close",
                  "sma5", "sma20", "rsi14", "macd_hist", "volume_ratio",
                  "reasons", "ai_comment", "earnings_date", "list_type"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="日次売買シグナルパイプライン")
    parser.add_argument("--ticker", type=str, default=None, help="特定銘柄のみ処理（例: 7203.T）")
    parser.add_argument("--dry-run", action="store_true", help="AI解説・決算取得をスキップ（テスト用）")
    args = parser.parse_args()
    run_daily(ticker_override=args.ticker, dry_run=args.dry_run)
