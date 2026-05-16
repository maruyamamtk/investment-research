"""
J-Quants API クライアント
用途: プライム市場の全銘柄リスト・財務諸表（EPS・売上高・ROE）取得
認証フロー: email/password → refresh_token → id_token
"""
import time
from typing import Optional

import requests

from src.utils.cache import Cache
from src.utils.logger import get_logger

BASE_URL = "https://api.jquants.com/v1"
logger = get_logger("jquants")

# 年次・四半期を判別するための TypeOfDocument プレフィックス
_ANNUAL_TYPES = {"FY"}
_QUARTERLY_TYPES = {"1Q", "2Q", "3Q"}


class JQuantsClient:
    def __init__(self, email: str, password: str, cache: Optional[Cache] = None):
        self.email = email
        self.password = password
        self.cache = cache or Cache()
        self._id_token: Optional[str] = None

    # ---- 認証 ----

    def _get_refresh_token(self) -> str:
        resp = requests.post(
            f"{BASE_URL}/token/auth_user",
            json={"mailaddress": self.email, "password": self.password},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["refreshToken"]

    def _get_id_token(self, refresh_token: str) -> str:
        resp = requests.post(
            f"{BASE_URL}/token/auth_refresh",
            params={"refreshtoken": refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["idToken"]

    def _authenticate(self) -> None:
        cached = self.cache.get("jquants_id_token", ttl_hours=23)
        if cached:
            self._id_token = cached
            return
        logger.info("J-Quants: 認証中...")
        refresh_token = self._get_refresh_token()
        self._id_token = self._get_id_token(refresh_token)
        self.cache.set("jquants_id_token", self._id_token)
        logger.info("J-Quants: 認証完了")

    def _headers(self) -> dict:
        if not self._id_token:
            self._authenticate()
        return {"Authorization": f"Bearer {self._id_token}"}

    # ---- 銘柄マスター ----

    def get_prime_stocks(self) -> list[dict]:
        """プライム市場の全銘柄マスターを取得する"""
        cached = self.cache.get("prime_stock_list", ttl_hours=168)
        if cached:
            logger.info(f"J-Quants: 銘柄マスターをキャッシュから取得 ({len(cached)}件)")
            return cached

        logger.info("J-Quants: プライム市場銘柄マスター取得中...")
        resp = requests.get(
            f"{BASE_URL}/listed/info",
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()

        all_stocks = resp.json().get("info", [])
        prime = [s for s in all_stocks if s.get("MarketCode") == "0111"]

        self.cache.set("prime_stock_list", prime)
        logger.info(f"J-Quants: プライム市場銘柄マスター取得完了 ({len(prime)}件)")
        return prime

    def get_prime_tickers(self) -> list[str]:
        """プライム市場の全銘柄コード（yfinance形式: '{code}.T'）を返す"""
        stocks = self.get_prime_stocks()
        return [f"{s['Code'][:4]}.T" for s in stocks]

    def get_prime_codes(self) -> list[str]:
        """プライム市場の全銘柄コード（J-Quants形式: 5桁）を返す"""
        stocks = self.get_prime_stocks()
        return [s["Code"] for s in stocks]

    # ---- 財務諸表 ----

    def get_statements(self, code: str) -> list[dict]:
        """
        銘柄の財務諸表を全件取得する。
        code は J-Quants 形式（5桁）または 4桁コードどちらでも可。
        """
        # 4桁コードを5桁に変換（末尾0を追加）
        jq_code = code.replace(".T", "")
        if len(jq_code) == 4:
            jq_code = jq_code + "0"

        cache_key = f"stmts_{jq_code}"
        cached = self.cache.get(cache_key, ttl_hours=168)
        if cached:
            return cached

        try:
            resp = requests.get(
                f"{BASE_URL}/fins/statements",
                headers=self._headers(),
                params={"code": jq_code},
                timeout=30,
            )
            resp.raise_for_status()
            statements = resp.json().get("statements", [])
            self.cache.set(cache_key, statements)
            return statements
        except Exception as e:
            logger.debug(f"J-Quants: 財務諸表取得失敗 {jq_code}: {e}")
            return []

    def get_annual_statements(self, code: str) -> list[dict]:
        """年次財務諸表のみ抽出（TypeOfDocument が FY で始まるもの）"""
        stmts = self.get_statements(code)
        annual = [
            s for s in stmts
            if any(s.get("TypeOfDocument", "").startswith(t) for t in _ANNUAL_TYPES)
        ]
        # 期末日で降順ソート（最新が先頭）
        annual.sort(key=lambda x: x.get("CurrentPeriodEndDate", ""), reverse=True)
        return annual

    def get_quarterly_statements(self, code: str) -> list[dict]:
        """四半期財務諸表のみ抽出（1Q/2Q/3Q）"""
        stmts = self.get_statements(code)
        quarterly = [
            s for s in stmts
            if any(s.get("TypeOfDocument", "").startswith(t) for t in _QUARTERLY_TYPES)
        ]
        quarterly.sort(key=lambda x: x.get("CurrentPeriodEndDate", ""), reverse=True)
        return quarterly

    def get_eps_series(self, code: str) -> dict:
        """
        EPS・売上高・ROE の年次・四半期時系列を返す。

        Returns:
            {
                "annual": [{"date": "2024-03-31", "eps": 100.0, "net_sales": 1e12, "roe": 0.15}, ...],
                "quarterly": [{"date": "2024-12-31", "eps": 30.0, "net_sales": 2e11, "period_type": "3Q"}, ...]
            }
        """
        cache_key = f"eps_{code.replace('.', '_').replace('0', '', 1)}"
        cached = self.cache.get(cache_key, ttl_hours=168)
        if cached:
            return cached

        annual_raw = self.get_annual_statements(code)
        quarterly_raw = self.get_quarterly_statements(code)

        annual = []
        for s in annual_raw[:5]:  # 直近5期
            eps = _to_float(s.get("EarningsPerShare"))
            sales = _to_float(s.get("NetSales"))
            profit = _to_float(s.get("Profit"))
            equity = _to_float(s.get("Equity"))
            roe = (profit / equity) if (profit is not None and equity and equity > 0) else None
            annual.append({
                "date": s.get("CurrentPeriodEndDate", ""),
                "eps": eps,
                "net_sales": sales,
                "profit": profit,
                "equity": equity,
                "roe": roe,
                "equity_ratio": _to_float(s.get("EquityToAssetRatio")),
            })

        quarterly = []
        for s in quarterly_raw[:6]:  # 直近6四半期
            doc_type = s.get("TypeOfDocument", "")
            period_type = next((t for t in _QUARTERLY_TYPES if doc_type.startswith(t)), "")
            eps = _to_float(s.get("EarningsPerShare"))
            sales = _to_float(s.get("NetSales"))
            quarterly.append({
                "date": s.get("CurrentPeriodEndDate", ""),
                "eps": eps,
                "net_sales": sales,
                "period_type": period_type,
            })

        result = {"annual": annual, "quarterly": quarterly}
        self.cache.set(cache_key, result)
        return result

    def get_statements_batch(
        self, codes: list[str], batch_size: int = 30, sleep_sec: float = 0.15
    ) -> dict[str, dict]:
        """複数銘柄のEPS時系列を一括取得する"""
        result = {}
        total = len(codes)
        for i, code in enumerate(codes):
            if i % 50 == 0:
                logger.info(f"  財務諸表取得中: {i + 1}/{total}")
            result[code] = self.get_eps_series(code)
            time.sleep(sleep_sec)
        return result


def _to_float(val) -> Optional[float]:
    try:
        f = float(val)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


def get_prime_tickers_fallback() -> list[str]:
    """J-Quants APIキーなし時のフォールバック: 代表的なプライム銘柄リストを返す"""
    fallback = [
        "7203.T", "6758.T", "9432.T", "8306.T", "6861.T",
        "4063.T", "9984.T", "6501.T", "7974.T", "8035.T",
        "4519.T", "6594.T", "6367.T", "9433.T", "8316.T",
        "7267.T", "6702.T", "4661.T", "6954.T", "2914.T",
        "9020.T", "3382.T", "8058.T", "8031.T", "5108.T",
        "7270.T", "6902.T", "4543.T", "8766.T", "6326.T",
    ]
    logger.warning(f"J-Quants APIキー未設定: フォールバック銘柄リスト({len(fallback)}件)を使用")
    return fallback
