"""
Comps分析モジュール: 同業他社5社との10指標比較表を生成する
"""
import time
from datetime import datetime
from typing import Optional

from src.utils.logger import get_logger

logger = get_logger("comps_analyzer")

# 比較する10指標の定義（フィールド名, 表示名, 単位, 高い方が良いか）
COMPS_METRICS = [
    ("market_cap",         "時価総額",         "億円",  True),
    ("pe_ratio",           "PER",              "倍",    False),  # 低い方が割安
    ("pbr",                "PBR",              "倍",    False),
    ("ev_ebitda",          "EV/EBITDA",        "倍",    False),
    ("ev_revenue",         "EV/Revenue",       "倍",    False),
    ("roe",                "ROE",              "%",     True),
    ("operating_margins",  "営業利益率",        "%",     True),
    ("revenue_growth",     "売上成長率",        "%",     True),
    ("eps_growth",         "EPS成長率",         "%",     True),
    ("dividend_yield",     "配当利回り",        "%",     True),
]


def find_peers(
    target_info: dict,
    candidates: list[dict],
    n: int = 5,
) -> list[dict]:
    """スクリーニング済み候補からtargetと同セクター・同業種のピアを最大n社選定する。

    優先順位:
    1. 同じ industry の銘柄（市場時価総額降順）
    2. 不足する場合は同じ sector の銘柄で補完
    """
    target_ticker = target_info.get("ticker", "")
    target_industry = target_info.get("industry", "")
    target_sector = target_info.get("sector", "")

    same_industry = [
        c for c in candidates
        if c.get("ticker") != target_ticker
        and c.get("industry") == target_industry
        and c.get("industry")
    ]
    same_sector = [
        c for c in candidates
        if c.get("ticker") != target_ticker
        and c.get("sector") == target_sector
        and c.get("industry") != target_industry
        and c.get("sector")
    ]

    # 時価総額降順でソート（Noneは末尾）
    def sort_key(c):
        mc = c.get("market_cap")
        return -(mc if mc else 0)

    same_industry.sort(key=sort_key)
    same_sector.sort(key=sort_key)

    peers = (same_industry + same_sector)[:n]

    if not peers:
        logger.warning(
            f"{target_ticker}: ピアが見つかりません "
            f"(sector={target_sector}, industry={target_industry})"
        )
    else:
        logger.info(
            f"{target_ticker}: ピア {len(peers)}社 "
            f"(同業種{len(same_industry[:n])}社 + 同セクター{len(same_sector[:n-len(same_industry[:n])])}社)"
        )

    return peers


def fetch_comps_metrics(ticker: str, yf_client) -> dict:
    """1銘柄分のComps指標を取得する"""
    try:
        info = yf_client.get_basic_info(ticker)
        fins = yf_client.get_detailed_financials(ticker)

        market_cap_jpy = info.get("market_cap")
        market_cap_oku = (market_cap_jpy / 1e8) if market_cap_jpy else None

        # EPS成長率: earningsGrowth または epsCurrentYear と epsTrailingTwelveMonths の差分
        import yfinance as yf
        raw_info = {}
        try:
            t = yf.Ticker(ticker)
            raw_info = t.info or {}
        except Exception:
            pass

        eps_growth = raw_info.get("earningsGrowth") or raw_info.get("earningsQuarterlyGrowth")

        return {
            "ticker": ticker,
            "name": info.get("name", ticker),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": market_cap_oku,
            "pe_ratio": info.get("pe_ratio"),
            "pbr": info.get("pbr"),
            "ev_ebitda": fins.get("ev_ebitda"),
            "ev_revenue": fins.get("ev_revenue"),
            "roe": fins.get("roe"),
            "operating_margins": info.get("operating_margins"),
            "revenue_growth": info.get("revenue_growth"),
            "eps_growth": eps_growth,
            "dividend_yield": raw_info.get("dividendYield"),
        }
    except Exception as e:
        logger.warning(f"Comps指標取得失敗 {ticker}: {e}")
        return {"ticker": ticker, "name": ticker}


def generate_comps_report(
    target_ticker: str,
    candidates: list[dict],
    yf_client,
    n_peers: int = 5,
    sleep_sec: float = 1.0,
) -> str:
    """target_tickerのCompsレポート（Markdown）を生成して返す"""
    logger.info(f"Comps分析開始: {target_ticker}")

    # ターゲットの基本情報でピア選定
    target_basic = next(
        (c for c in candidates if c.get("ticker") == target_ticker), None
    )
    if target_basic is None:
        target_basic = yf_client.get_basic_info(target_ticker)

    peers = find_peers(target_basic, candidates, n=n_peers)
    peer_tickers = [p["ticker"] for p in peers]

    all_tickers = [target_ticker] + peer_tickers
    all_data: list[dict] = []
    for t in all_tickers:
        data = fetch_comps_metrics(t, yf_client)
        all_data.append(data)
        time.sleep(sleep_sec)

    target_data = all_data[0]
    peers_data = all_data[1:]

    return _build_comps_markdown(target_data, peers_data)


def _build_comps_markdown(target: dict, peers: list[dict]) -> str:
    """Comps比較表をMarkdown形式で生成する"""
    now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
    name = target.get("name", target["ticker"])
    ticker = target["ticker"]
    sector = target.get("sector", "不明")
    industry = target.get("industry", "不明")

    header = [
        f"## {name}（{ticker}） Comps分析",
        "",
        f"生成日時: {now}",
        f"セクター: {sector} / 業種: {industry}",
        "",
    ]

    if not peers:
        header += [
            "> ⚠️ 同セクター・同業種のピアが候補銘柄内に見つかりませんでした。",
            "> ウォッチリストを拡充するか、手動でピアを指定してください。",
            "",
        ]
        return "\n".join(header)

    # テーブルヘッダー
    all_stocks = [target] + peers
    col_names = ["指標"] + [f"{s.get('name', s['ticker'])[:8]}\n({s['ticker']})" for s in all_stocks]

    rows = []
    for field, label, unit, higher_is_better in COMPS_METRICS:
        row_vals = []
        raw_vals = [s.get(field) for s in all_stocks]

        # ターゲット値を強調する最小/最大判定
        valid_vals = [v for v in raw_vals if v is not None]
        best_val = (max(valid_vals) if higher_is_better else min(valid_vals)) if valid_vals else None

        for i, (stock, val) in enumerate(zip(all_stocks, raw_vals)):
            formatted = _format_metric(field, val, unit)
            is_best = (val is not None and val == best_val and len(valid_vals) > 1)
            is_target = (i == 0)

            if is_target and is_best:
                cell = f"**{formatted} ★**"
            elif is_target:
                cell = f"**{formatted}**"
            elif is_best:
                cell = f"{formatted} ★"
            else:
                cell = formatted
            row_vals.append(cell)

        rows.append([f"{label}（{unit}）"] + row_vals)

    # Markdown テーブル生成
    separator = "|" + "|".join(["---"] * (len(all_stocks) + 1)) + "|"

    lines = header + [
        "### 10指標比較表",
        "",
        "| 指標 | " + " | ".join(
            f"{s.get('name', s['ticker'])[:8]}({s['ticker']})" for s in all_stocks
        ) + " |",
        separator,
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")

    lines += [
        "",
        "> **★**: 比較対象中でもっとも優れた値",
        "> **太字**: 分析対象銘柄",
        "",
        "---",
        "",
    ]

    return "\n".join(lines)


def _format_metric(field: str, val, unit: str) -> str:
    if val is None:
        return "N/A"
    try:
        if field == "market_cap":
            return f"{val:,.0f}"
        elif unit == "%":
            return f"{val * 100:.1f}"
        else:
            return f"{val:.1f}"
    except (TypeError, ValueError):
        return "N/A"
