"""
Yahoo Finance クライアント
用途: 株価OHLCV・財務比率・詳細財務データ・決算予定日の取得
"""
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import yfinance as yf

from src.utils.cache import Cache
from src.utils.logger import get_logger

logger = get_logger("yfinance")


class YFinanceClient:
    def __init__(self, cache: Optional[Cache] = None, batch_sleep: float = 2.0):
        self.cache = cache or Cache()
        self.batch_sleep = batch_sleep

    # ---- 株価履歴 ----

    def get_price_history(self, ticker: str, days: int = 400) -> Optional[pd.DataFrame]:
        """日足OHLCV履歴を取得（テクニカル分析用）"""
        cache_key = f"price_{ticker.replace('.', '_')}"
        cached = self.cache.get(cache_key, ttl_hours=24)
        if cached:
            df = pd.DataFrame(cached)
            df.index = pd.to_datetime(df.index)
            return df

        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
            if df.empty:
                return None
            # MultiIndex列名を平坦化
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.index = df.index.strftime("%Y-%m-%d")
            self.cache.set(cache_key, df.to_dict())
            df.index = pd.to_datetime(df.index)
            return df
        except Exception as e:
            logger.warning(f"株価履歴取得失敗 {ticker}: {e}")
            return None

    # ---- 基本財務情報（Step1用）----

    def get_basic_info(self, ticker: str) -> dict:
        """Step1スクリーニング用の基本財務情報を取得"""
        cache_key = f"info_{ticker.replace('.', '_')}"
        cached = self.cache.get(cache_key, ttl_hours=168)
        if cached:
            return cached

        try:
            t = yf.Ticker(ticker)
            info = t.info or {}
            result = {
                "ticker": ticker,
                "name": info.get("longName") or info.get("shortName", ""),
                "market_cap": info.get("marketCap"),
                "revenue_growth": info.get("revenueGrowth"),
                "operating_margins": info.get("operatingMargins"),
                "pbr": info.get("priceToBook"),
                "pe_ratio": info.get("trailingPE"),
                "payout_ratio": info.get("payoutRatio"),
                "total_debt": info.get("totalDebt", 0),
                "total_equity": info.get("totalStockholderEquity") or info.get("bookValue"),
                "total_assets": info.get("totalAssets"),
                "sector": info.get("sector", ""),
                "industry": info.get("industry", ""),
                "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
                "currency": info.get("currency", "JPY"),
                "website": info.get("website", ""),
            }
            self.cache.set(cache_key, result)
            return result
        except Exception as e:
            logger.debug(f"基本情報取得失敗 {ticker}: {e}")
            return {"ticker": ticker}

    def get_basic_info_batch(self, tickers: list[str], batch_size: int = 30) -> list[dict]:
        """複数銘柄の基本財務情報をバッチ取得"""
        results = []
        total = len(tickers)
        for i in range(0, total, batch_size):
            batch = tickers[i:i + batch_size]
            logger.info(f"基本情報取得中: {i + 1}〜{min(i + batch_size, total)}/{total}件")
            for ticker in batch:
                results.append(self.get_basic_info(ticker))
            if i + batch_size < total:
                time.sleep(self.batch_sleep)
        return results

    # ---- 詳細財務情報（Step2用）----

    def get_detailed_financials(self, ticker: str) -> dict:
        """Step2分析用の詳細財務データを取得"""
        cache_key = f"fins_{ticker.replace('.', '_')}"
        cached = self.cache.get(cache_key, ttl_hours=168)
        if cached:
            return cached

        result = {"ticker": ticker}
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            # --- ROE ---
            result["roe"] = info.get("returnOnEquity")

            # --- 売上高CAGR計算 ---
            try:
                rev = t.financials
                if rev is not None and not rev.empty:
                    rev_row = rev.loc["Total Revenue"] if "Total Revenue" in rev.index else None
                    if rev_row is not None and len(rev_row) >= 3:
                        latest = rev_row.iloc[0]
                        oldest = rev_row.iloc[min(2, len(rev_row) - 1)]
                        years = min(2, len(rev_row) - 1)
                        if oldest and oldest > 0 and latest and latest > 0:
                            result["revenue_cagr"] = (latest / oldest) ** (1 / years) - 1
                        else:
                            result["revenue_cagr"] = None
                    else:
                        result["revenue_cagr"] = None
                else:
                    result["revenue_cagr"] = None
            except Exception:
                result["revenue_cagr"] = None

            # --- FCF・CF品質 ---
            try:
                cf = t.cashflow
                if cf is not None and not cf.empty:
                    ocf_row = cf.loc["Operating Cash Flow"] if "Operating Cash Flow" in cf.index else None
                    capex_row = cf.loc["Capital Expenditure"] if "Capital Expenditure" in cf.index else None

                    if ocf_row is not None:
                        ocf_vals = ocf_row.dropna().values
                        capex_vals = capex_row.dropna().values if capex_row is not None else [0] * len(ocf_vals)

                        fcf_vals = [
                            o + c for o, c in zip(ocf_vals, capex_vals)
                        ]
                        result["fcf_positive_years"] = sum(1 for f in fcf_vals[:3] if f > 0)
                        result["latest_ocf"] = float(ocf_vals[0]) if len(ocf_vals) > 0 else None
                    else:
                        result["fcf_positive_years"] = 0
                        result["latest_ocf"] = None
                else:
                    result["fcf_positive_years"] = 0
                    result["latest_ocf"] = None
            except Exception:
                result["fcf_positive_years"] = 0
                result["latest_ocf"] = None

            # --- CF品質 ---
            try:
                net_income = info.get("netIncomeToCommon")
                ocf = result.get("latest_ocf")
                if ocf and net_income and net_income > 0:
                    result["cf_quality"] = ocf / net_income
                else:
                    result["cf_quality"] = None
            except Exception:
                result["cf_quality"] = None

            # --- ネット有利子負債/EBITDA ---
            result["ebitda"] = info.get("ebitda")
            result["total_debt"] = info.get("totalDebt", 0)
            result["total_cash"] = info.get("totalCash", 0)
            if result["ebitda"] and result["ebitda"] > 0:
                net_debt = (result["total_debt"] or 0) - (result["total_cash"] or 0)
                result["net_debt_ebitda"] = net_debt / result["ebitda"]
            else:
                result["net_debt_ebitda"] = None

            # --- 配当性向 ---
            result["payout_ratio"] = info.get("payoutRatio")

            # --- その他補足情報 ---
            result["operating_margins"] = info.get("operatingMargins")
            result["pe_ratio"] = info.get("trailingPE")
            result["pbr"] = info.get("priceToBook")
            result["ev_revenue"] = info.get("enterpriseToRevenue")
            result["ev_ebitda"] = info.get("enterpriseToEbitda")
            result["name"] = info.get("longName") or info.get("shortName", ticker)
            result["sector"] = info.get("sector", "")
            result["industry"] = info.get("industry", "")
            # --- Comps分析用補足指標 ---
            result["dividend_yield"] = info.get("dividendYield")
            result["eps_growth"] = info.get("earningsGrowth") or info.get("earningsQuarterlyGrowth")

            self.cache.set(cache_key, result)
        except Exception as e:
            logger.warning(f"詳細財務取得失敗 {ticker}: {e}")

        return result

    # ---- DCFモデル用データ取得 ----

    def get_dcf_data(self, ticker: str) -> dict:
        """DCFモデル計算に必要なデータを取得する。

        Returns:
            dict with keys:
                ticker, name, current_price, shares_outstanding,
                beta, market_cap, total_debt, total_cash, net_debt,
                fcf_list (最新順), latest_fcf, revenue_growth, ebitda
        """
        cache_key = f"dcf_{ticker.replace('.', '_')}"
        cached = self.cache.get(cache_key, ttl_hours=168)
        if cached:
            return cached

        result: dict = {"ticker": ticker}
        try:
            t = yf.Ticker(ticker)
            info = t.info or {}

            result["name"] = info.get("longName") or info.get("shortName", ticker)
            result["current_price"] = info.get("currentPrice") or info.get("regularMarketPrice")
            result["shares_outstanding"] = info.get("sharesOutstanding")
            result["beta"] = info.get("beta")
            result["market_cap"] = info.get("marketCap")
            result["total_debt"] = info.get("totalDebt") or 0
            result["total_cash"] = info.get("totalCash") or 0
            result["net_debt"] = result["total_debt"] - result["total_cash"]
            result["ebitda"] = info.get("ebitda")
            result["revenue_growth"] = info.get("revenueGrowth")

            # --- 歴史的FCFリスト（最新順）---
            fcf_list = []
            try:
                cf = t.cashflow
                if cf is not None and not cf.empty:
                    ocf_row = cf.loc["Operating Cash Flow"] if "Operating Cash Flow" in cf.index else None
                    capex_row = cf.loc["Capital Expenditure"] if "Capital Expenditure" in cf.index else None
                    if ocf_row is not None:
                        ocf_vals = ocf_row.dropna().values
                        capex_vals = (
                            capex_row.dropna().values
                            if capex_row is not None
                            else [0.0] * len(ocf_vals)
                        )
                        fcf_list = [float(o + c) for o, c in zip(ocf_vals, capex_vals)]
            except Exception:
                pass

            result["fcf_list"] = fcf_list
            result["latest_fcf"] = fcf_list[0] if fcf_list else None

            # --- Beta取得失敗時のフォールバック ---
            if result["beta"] is None or result["beta"] <= 0:
                result["beta"] = 1.0

            self.cache.set(cache_key, result)
        except Exception as e:
            logger.warning(f"DCFデータ取得失敗 {ticker}: {e}")

        return result

    # ---- 決算カレンダー（フェイクアウト回避）----

    def get_earnings_date(self, ticker: str) -> Optional[datetime]:
        """次回決算発表予定日を取得"""
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if cal is None:
                return None
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed and len(ed) > 0:
                    d = ed[0]
                    return pd.Timestamp(d).to_pydatetime() if not isinstance(d, datetime) else d
            return None
        except Exception:
            return None
