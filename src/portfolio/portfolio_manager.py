"""
ポートフォリオ管理モジュール

config/portfolio.yaml から保有銘柄を読み込み、
yfinance で現在価格を取得して評価額・損益を計算する。
"""
import os
from dataclasses import dataclass, field
from typing import Optional

import yaml

from src.utils.logger import get_logger

logger = get_logger("portfolio_manager")


@dataclass
class Holding:
    ticker: str
    shares: int
    acquisition_price: float
    name: str = ""
    note: str = ""
    current_price: Optional[float] = None

    @property
    def acquisition_value(self) -> float:
        return self.shares * self.acquisition_price

    @property
    def current_value(self) -> Optional[float]:
        if self.current_price is None:
            return None
        return self.shares * self.current_price

    @property
    def unrealized_pnl(self) -> Optional[float]:
        if self.current_price is None:
            return None
        return (self.current_price - self.acquisition_price) * self.shares

    @property
    def unrealized_pnl_pct(self) -> Optional[float]:
        if self.current_price is None or self.acquisition_price == 0:
            return None
        return (self.current_price - self.acquisition_price) / self.acquisition_price


class PortfolioManager:
    """
    保有銘柄の読み込み・評価・サマリー生成を担当する。

    portfolio_path: config/portfolio.yaml へのパス
    yf_client: YFinanceClient（現在価格取得に使用）
    """

    def __init__(self, portfolio_path: str = "config/portfolio.yaml", yf_client=None):
        self.portfolio_path = portfolio_path
        self.yf_client = yf_client
        self._settings: dict = {}
        self._holdings: list[Holding] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.portfolio_path):
            logger.warning(f"ポートフォリオファイルが見つかりません: {self.portfolio_path}")
            return

        with open(self.portfolio_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        self._settings = data.get("settings", {})
        raw_holdings = data.get("holdings") or []

        self._holdings = []
        for item in raw_holdings:
            if not item.get("ticker") or not item.get("shares"):
                continue
            self._holdings.append(
                Holding(
                    ticker=str(item["ticker"]),
                    shares=int(item["shares"]),
                    acquisition_price=float(item.get("acquisition_price", 0)),
                    name=item.get("name", ""),
                    note=item.get("note", ""),
                )
            )

        logger.info(f"ポートフォリオ読み込み完了: {len(self._holdings)}銘柄")

    def refresh_prices(self) -> None:
        """yf_client 経由で現在価格を取得して各 Holding に設定する。"""
        if not self._holdings:
            return
        if self.yf_client is None:
            logger.warning("YFinanceClientが未設定のため現在価格を取得できません")
            return

        for h in self._holdings:
            try:
                df = self.yf_client.get_price_history(h.ticker, days=5)
                if df is None or df.empty:
                    logger.warning(f"  {h.ticker} の価格履歴が取得できませんでした")
                    continue
                close_col = next(
                    (c for c in df.columns if c.lower() == "close"), None
                )
                if close_col is None:
                    logger.warning(f"  {h.ticker} のCloseカラムが見つかりません")
                    continue
                h.current_price = float(df[close_col].dropna().iloc[-1])
                logger.info(f"  {h.ticker} 現在価格: {h.current_price:,.0f}円")
            except Exception as e:
                logger.warning(f"  {h.ticker} の現在価格取得失敗: {e}")

    @property
    def holdings(self) -> list[Holding]:
        return self._holdings

    @property
    def settings(self) -> dict:
        return self._settings

    @property
    def total_acquisition_value(self) -> float:
        return sum(h.acquisition_value for h in self._holdings)

    @property
    def total_current_value(self) -> Optional[float]:
        values = [h.current_value for h in self._holdings if h.current_value is not None]
        if not values:
            return None
        return sum(values)

    @property
    def total_unrealized_pnl(self) -> Optional[float]:
        total = self.total_current_value
        if total is None:
            return None
        return total - self.total_acquisition_value

    def get_weights(self) -> dict[str, float]:
        """現在評価額ベースの各銘柄ウェイトを返す。"""
        total = self.total_current_value
        if not total:
            return {}
        return {
            h.ticker: (h.current_value or 0) / total
            for h in self._holdings
        }

    def is_empty(self) -> bool:
        return len(self._holdings) == 0

    def to_dict_list(self) -> list[dict]:
        """LINE通知・レポート生成用の辞書リストに変換する。"""
        weights = self.get_weights()
        result = []
        for h in self._holdings:
            result.append({
                "ticker": h.ticker,
                "name": h.name or h.ticker,
                "shares": h.shares,
                "acquisition_price": h.acquisition_price,
                "acquisition_value": h.acquisition_value,
                "current_price": h.current_price,
                "current_value": h.current_value,
                "unrealized_pnl": h.unrealized_pnl,
                "unrealized_pnl_pct": h.unrealized_pnl_pct,
                "weight": weights.get(h.ticker),
                "note": h.note,
            })
        return result
