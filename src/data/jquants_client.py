"""
J-Quants API クライアント（V2）
用途: プライム市場の全銘柄リスト・財務諸表（EPS・売上高・ROE）取得
認証: APIキー方式（x-api-key ヘッダー）。
      ※ V1 のトークン方式（/token/auth_user → refresh_token → id_token）は
        J-Quants 側で廃止され 410 Gone を返すため、V2 へ移行済み。
"""
import time
from typing import Optional

import requests

from src.utils.cache import Cache
from src.utils.logger import get_logger

BASE_URL = "https://api.jquants.com/v2"
logger = get_logger("jquants")

# 年次・四半期を判別するための DocType プレフィックス
_ANNUAL_TYPES = {"FY"}
_QUARTERLY_TYPES = {"1Q", "2Q", "3Q"}

# V2 で短縮されたフィールド名 → 本クライアントが内部で使う正規名 への対応表。
# 下流ロジック（get_eps_series 等）を V1 時代のまま維持するための正規化に使う。
_STATEMENT_FIELD_MAP = {
    "EPS": "EarningsPerShare",
    "Sales": "NetSales",
    "NP": "Profit",
    "Eq": "Equity",
    "EqAR": "EquityToAssetRatio",
    "DocType": "TypeOfDocument",
    "CurPerEn": "CurrentPeriodEndDate",
}


class JQuantsClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        cache: Optional[Cache] = None,
        # 後方互換のため残置（V2 では未使用）
        email: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self.api_key = api_key
        self.email = email
        self.password = password
        self.cache = cache or Cache()

    # ---- 認証（APIキー方式） ----

    def _headers(self) -> dict:
        if not self.api_key:
            raise RuntimeError(
                "J-Quants APIキーが未設定です。V2 はAPIキー認証必須です"
                "（settings.yaml の api.jquants.api_key または環境変数 JQUANTS_API_KEY を設定してください）"
            )
        return {"x-api-key": self.api_key}

    # ---- 銘柄マスター ----

    def get_prime_stocks(self) -> list[dict]:
        """プライム市場の全銘柄マスターを取得する"""
        cached = self.cache.get("prime_stock_list", ttl_hours=168)
        if cached:
            logger.info(f"J-Quants: 銘柄マスターをキャッシュから取得 ({len(cached)}件)")
            return cached

        logger.info("J-Quants: プライム市場銘柄マスター取得中...")
        resp = requests.get(
            f"{BASE_URL}/equities/master",
            headers=self._headers(),
            timeout=60,
        )
        resp.raise_for_status()

        all_stocks = resp.json().get("data", [])
        # V2: 市場区分は "Mkt"、プライム = "0111"
        prime = [s for s in all_stocks if s.get("Mkt") == "0111"]

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
                f"{BASE_URL}/fins/summary",
                headers=self._headers(),
                params={"code": jq_code},
                timeout=30,
            )
            resp.raise_for_status()
            raw = resp.json().get("data", [])
            # V2 の短縮フィールド名を V1 互換の正規名へ変換し、下流ロジックを不変に保つ
            statements = [_normalize_statement(s) for s in raw]
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


def _normalize_statement(s: dict) -> dict:
    """V2 /fins/summary の短縮フィールド名を V1 互換の正規名へマッピングする。
    元キーも残しつつ、正規名が未設定の場合のみ補完する（冪等）。"""
    out = dict(s)
    for v2_key, canonical in _STATEMENT_FIELD_MAP.items():
        if canonical not in out and v2_key in s:
            out[canonical] = s[v2_key]
    return out


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
