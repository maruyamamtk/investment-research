"""
決算レビューモジュール

機能:
  - yfinance から直近四半期の EPS・売上の実績 vs アナリスト予想を取得
  - Beat / Miss / Meet 判定
  - 通期ガイダンスの上方・下方修正を検出
  - Markdown レポートセクションを生成
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from src.utils.logger import get_logger

logger = get_logger("earnings_reviewer")

# 判定閾値
BEAT_THRESHOLD = 0.01    # +1% 以上で Beat
MISS_THRESHOLD = -0.01   # -1% 以下で Miss
GUIDANCE_CHANGE_THRESHOLD = 0.01  # ±1% 超で変化とみなす


# ----------------------------------------------------------------
# データ取得
# ----------------------------------------------------------------

def get_earnings_data(ticker: str, yf_client) -> dict:
    """決算レビューに必要なデータを yfinance から取得する。

    Returns:
        dict with keys:
            ticker, name, sector, industry, currency,
            eps_history (list[dict]),   # 最新順: {quarter, actual, estimate, surprise_pct}
            revenue_history (list[dict]),  # 最新順: {quarter, actual}
            current_eps_estimate (float|None),
            prev_eps_estimate (float|None),
            earnings_date (str|None),
            current_price (float|None),
    """
    import yfinance as yf

    result: dict = {"ticker": ticker}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        result["name"] = info.get("longName") or info.get("shortName", ticker)
        result["sector"] = info.get("sector", "")
        result["industry"] = info.get("industry", "")
        result["currency"] = info.get("currency", "JPY")
        result["current_price"] = info.get("currentPrice") or info.get("regularMarketPrice")

        # EPS 履歴（actual vs estimate）
        result["eps_history"] = _fetch_eps_history(t)

        # 売上実績履歴
        result["revenue_history"] = _fetch_revenue_history(t)

        # 通期EPS予想（現在 vs 前回）
        result["current_eps_estimate"] = info.get("forwardEps")
        result["trailing_eps"] = info.get("trailingEps")

        # 直近決算日
        result["earnings_date"] = _fetch_latest_earnings_date(t)

    except Exception as e:
        logger.warning(f"決算データ取得失敗 {ticker}: {e}")

    return result


def _fetch_eps_history(ticker_obj) -> list[dict]:
    """EPS 実績 vs 予想の履歴を返す（最新順）。"""
    records = []
    try:
        hist = ticker_obj.earnings_history
        if hist is not None and not hist.empty:
            for idx, row in hist.iterrows():
                actual = _safe_float(row.get("epsActual"))
                estimate = _safe_float(row.get("epsEstimate"))
                surprise = _safe_float(row.get("surprisePercent"))
                quarter = str(idx)[:10] if idx else None
                records.append({
                    "quarter": quarter,
                    "actual": actual,
                    "estimate": estimate,
                    "surprise_pct": surprise,
                })
            return records
    except Exception as e:
        logger.debug(f"earnings_history 取得失敗: {e}")

    # フォールバック: quarterly_earnings
    try:
        qe = ticker_obj.quarterly_earnings
        if qe is not None and not qe.empty:
            for idx, row in qe.iterrows():
                records.append({
                    "quarter": str(idx),
                    "actual": _safe_float(row.get("Earnings")),
                    "estimate": None,
                    "surprise_pct": None,
                })
            return records
    except Exception as e:
        logger.debug(f"quarterly_earnings 取得失敗: {e}")

    return records


def _fetch_revenue_history(ticker_obj) -> list[dict]:
    """四半期売上高の実績履歴を返す（最新順）。"""
    records = []
    try:
        stmt = ticker_obj.quarterly_income_stmt
        if stmt is None or stmt.empty:
            stmt = ticker_obj.quarterly_financials
        if stmt is not None and not stmt.empty:
            rev_row = None
            for label in ("Total Revenue", "Revenue", "TotalRevenue"):
                if label in stmt.index:
                    rev_row = stmt.loc[label]
                    break
            if rev_row is not None:
                for date, val in rev_row.items():
                    records.append({
                        "quarter": str(date)[:10],
                        "actual": _safe_float(val),
                    })
    except Exception as e:
        logger.debug(f"売上実績取得失敗: {e}")
    return records


def _fetch_latest_earnings_date(ticker_obj) -> Optional[str]:
    """直近の決算発表日を返す。"""
    try:
        cal = ticker_obj.calendar
        if cal is None:
            return None
        if isinstance(cal, dict):
            ed = cal.get("Earnings Date")
            if ed and len(ed) > 0:
                return str(pd.Timestamp(ed[0]))[:10]
    except Exception:
        pass
    return None


# ----------------------------------------------------------------
# 判定ロジック
# ----------------------------------------------------------------

def determine_beat_miss(actual: Optional[float], estimate: Optional[float]) -> str:
    """EPS/売上の Beat/Miss/Meet を返す。"""
    if actual is None or estimate is None or estimate == 0:
        return "N/A"
    surprise = (actual - estimate) / abs(estimate)
    if surprise >= BEAT_THRESHOLD:
        return "Beat"
    if surprise <= MISS_THRESHOLD:
        return "Miss"
    return "Meet"


def calculate_surprise_pct(actual: Optional[float], estimate: Optional[float]) -> Optional[float]:
    """サプライズ率（%）を計算する。"""
    if actual is None or estimate is None or estimate == 0:
        return None
    return (actual - estimate) / abs(estimate) * 100


def detect_guidance_change(
    current_estimate: Optional[float],
    prev_estimate: Optional[float],
) -> str:
    """通期EPS予想の変化を検出する。

    Returns:
        "上方修正", "下方修正", "変化なし", "N/A"
    """
    if current_estimate is None or prev_estimate is None or prev_estimate == 0:
        return "N/A"
    change = (current_estimate - prev_estimate) / abs(prev_estimate)
    if change >= GUIDANCE_CHANGE_THRESHOLD:
        return "上方修正"
    if change <= -GUIDANCE_CHANGE_THRESHOLD:
        return "下方修正"
    return "変化なし"


# ----------------------------------------------------------------
# Markdown レポート生成
# ----------------------------------------------------------------

def generate_earnings_report(
    target_ticker: str,
    yf_client,
    prev_estimates: Optional[dict] = None,
) -> str:
    """target_ticker の決算レビューレポート（Markdown）を生成して返す。

    Args:
        target_ticker: 銘柄コード
        yf_client: YFinanceClient インスタンス
        prev_estimates: 前回記録した通期EPS予想 {ticker: float}（ガイダンス変化検出用）
    """
    logger.info(f"決算レビュー開始: {target_ticker}")
    data = get_earnings_data(target_ticker, yf_client)

    name = data.get("name", target_ticker)
    currency = data.get("currency", "JPY")
    now_str = datetime.now().strftime("%Y年%m月%d日 %H:%M")

    lines = [
        f"## {name}（{target_ticker}） 決算レビュー",
        "",
        f"生成日時: {now_str}",
        f"セクター: {data.get('sector', 'N/A')} / 業種: {data.get('industry', 'N/A')}",
        "",
    ]

    # ---- EPS サマリー ----
    eps_hist = data.get("eps_history", [])
    if eps_hist:
        latest = eps_hist[0]
        actual_eps = latest.get("actual")
        estimate_eps = latest.get("estimate")
        surprise_pct = latest.get("surprise_pct") or calculate_surprise_pct(actual_eps, estimate_eps)
        verdict = determine_beat_miss(actual_eps, estimate_eps)
        verdict_icon = {"Beat": "🟢", "Miss": "🔴", "Meet": "🟡"}.get(verdict, "⚪")

        lines += [
            "### EPS（1株利益）",
            "",
            f"| 項目 | 値 |",
            f"|---|---|",
            f"| 直近四半期 | {latest.get('quarter', 'N/A')} |",
            f"| 実績EPS | {_fmt_val(actual_eps, currency)} |",
            f"| 予想EPS | {_fmt_val(estimate_eps, currency)} |",
            f"| サプライズ | {_fmt_pct(surprise_pct)} |",
            f"| 判定 | {verdict_icon} **{verdict}** |",
            "",
        ]

        # 直近4四半期のEPS推移
        if len(eps_hist) >= 2:
            lines += [
                "#### 直近EPS推移",
                "",
                "| 四半期 | 実績EPS | 予想EPS | サプライズ |",
                "|---|---|---|---|",
            ]
            for rec in eps_hist[:4]:
                sp = rec.get("surprise_pct") or calculate_surprise_pct(
                    rec.get("actual"), rec.get("estimate")
                )
                lines.append(
                    f"| {rec.get('quarter', 'N/A')} "
                    f"| {_fmt_val(rec.get('actual'), currency)} "
                    f"| {_fmt_val(rec.get('estimate'), currency)} "
                    f"| {_fmt_pct(sp)} |"
                )
            lines.append("")
    else:
        lines += [
            "### EPS（1株利益）",
            "",
            "> ⚠️ EPS データが取得できませんでした。",
            "",
        ]

    # ---- 売上高 ----
    rev_hist = data.get("revenue_history", [])
    if rev_hist:
        latest_rev = rev_hist[0]
        prev_rev = rev_hist[1] if len(rev_hist) >= 2 else None
        actual_rev = latest_rev.get("actual")
        prev_actual_rev = prev_rev.get("actual") if prev_rev else None

        yoy_pct = None
        if actual_rev and prev_actual_rev and prev_actual_rev > 0:
            if len(rev_hist) >= 5:
                yoy_prev = rev_hist[4].get("actual") if len(rev_hist) > 4 else None
                if yoy_prev and yoy_prev > 0:
                    yoy_pct = (actual_rev - yoy_prev) / yoy_prev * 100

        lines += [
            "### 売上高",
            "",
            "| 項目 | 値 |",
            "|---|---|",
            f"| 直近四半期 | {latest_rev.get('quarter', 'N/A')} |",
            f"| 実績売上高 | {_fmt_jpy(actual_rev)} |",
        ]
        if yoy_pct is not None:
            lines.append(f"| 前年同期比 | {_fmt_pct(yoy_pct)} |")
        lines.append("")

        if len(rev_hist) >= 2:
            lines += [
                "#### 直近売上高推移（四半期）",
                "",
                "| 四半期 | 売上高 |",
                "|---|---|",
            ]
            for rec in rev_hist[:4]:
                lines.append(f"| {rec.get('quarter', 'N/A')} | {_fmt_jpy(rec.get('actual'))} |")
            lines.append("")
    else:
        lines += [
            "### 売上高",
            "",
            "> ⚠️ 売上高データが取得できませんでした。",
            "",
        ]

    # ---- ガイダンス変化 ----
    current_fwd_eps = data.get("current_eps_estimate")
    prev_fwd_eps = (prev_estimates or {}).get(target_ticker)
    guidance_change = detect_guidance_change(current_fwd_eps, prev_fwd_eps)
    guidance_icon = {"上方修正": "🔼", "下方修正": "🔽", "変化なし": "➡️"}.get(guidance_change, "❓")

    lines += [
        "### ガイダンス（通期EPS予想）",
        "",
        "| 項目 | 値 |",
        "|---|---|",
        f"| 現在の通期EPS予想（Forward EPS） | {_fmt_val(current_fwd_eps, currency)} |",
        f"| 前回記録時のEPS予想 | {_fmt_val(prev_fwd_eps, currency)} |",
        f"| 判定 | {guidance_icon} **{guidance_change}** |",
        "",
    ]

    if guidance_change == "N/A":
        lines.append("> ℹ️ 前回EPS予想が記録されていないため、ガイダンス変化を検出できませんでした。")
        lines.append("")

    lines += [
        "---",
        "",
    ]

    return "\n".join(lines)


# ----------------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _fmt_val(val: Optional[float], currency: str = "JPY") -> str:
    if val is None:
        return "N/A"
    if currency == "JPY":
        return f"¥{val:,.2f}"
    return f"{val:,.2f}"


def _fmt_jpy(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    oku = val / 1e8
    if abs(oku) >= 1:
        return f"{oku:,.1f} 億円"
    man = val / 1e4
    return f"{man:,.0f} 万円"


def _fmt_pct(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.1f}%"
