"""BuyCandidatesManager の永続化・損切り判定と市場レジーム判定のテスト"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.screener.buy_candidates import BuyCandidatesManager
from src.technical.signals import detect_market_regime, REGIME_BULL, REGIME_BEAR, REGIME_NEUTRAL


def _make_manager(tmp_path):
    return BuyCandidatesManager(
        cache_path=str(tmp_path / "cache" / "buy_candidates.json"),
        md_path=str(tmp_path / "output" / "buy_candidates.md"),
    )


def _signal_info(close=1000.0, date="2026-07-01", strength=4):
    return {"name": "テスト銘柄", "date": date, "strength": strength, "close": close, "reasons": "test"}


class TestPersistence:
    def test_upsert_persists_across_instances(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.upsert("7203.T", _signal_info())

        reloaded = _make_manager(tmp_path)
        assert reloaded.contains("7203.T")
        entry = reloaded.get_all()[0]
        assert entry["added_date"]
        assert entry["entry_close"] == 1000.0

    def test_added_date_preserved_on_re_buy(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.upsert("7203.T", _signal_info(close=1000.0, date="2026-07-01"))
        first_added = mgr.get_all()[0]["added_date"]

        reloaded = _make_manager(tmp_path)
        reloaded.upsert("7203.T", _signal_info(close=1200.0, date="2026-07-08"))
        entry = reloaded.get_all()[0]
        assert entry["added_date"] == first_added
        assert entry["entry_close"] == 1000.0  # 初回価格を保持
        assert entry["close"] == 1200.0  # 現在値は更新

    def test_legacy_raw_json_migration(self, tmp_path):
        # Cache導入前の生JSON形式（ラッパーなし）を読み込めること
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        legacy = [{"ticker": "9984.T", "name": "旧形式", "added_date": "2026-06-01", "close": 500.0}]
        (cache_dir / "buy_candidates.json").write_text(
            json.dumps(legacy, ensure_ascii=False), encoding="utf-8"
        )

        mgr = _make_manager(tmp_path)
        assert mgr.contains("9984.T")
        assert mgr.get_all()[0]["added_date"] == "2026-06-01"

    def test_remove(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.upsert("7203.T", _signal_info())
        assert mgr.remove("7203.T", reason="test")
        assert not _make_manager(tmp_path).contains("7203.T")


class TestStopLoss:
    def test_triggers_below_threshold(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.upsert("7203.T", _signal_info(close=1000.0))
        assert mgr.should_stop_loss("7203.T", 899.0, 0.10) is True

    def test_not_triggered_above_threshold(self, tmp_path):
        mgr = _make_manager(tmp_path)
        mgr.upsert("7203.T", _signal_info(close=1000.0))
        assert mgr.should_stop_loss("7203.T", 950.0, 0.10) is False

    def test_uses_entry_close_not_latest(self, tmp_path):
        # 再BUYで close が更新されても損切り基準は初回価格のまま
        mgr = _make_manager(tmp_path)
        mgr.upsert("7203.T", _signal_info(close=1000.0))
        mgr.upsert("7203.T", _signal_info(close=1500.0, date="2026-07-08"))
        assert mgr.should_stop_loss("7203.T", 1300.0, 0.10) is False  # 初回比-13%ではない(+30%)
        assert mgr.should_stop_loss("7203.T", 890.0, 0.10) is True   # 初回比-11%

    def test_safe_on_missing_data(self, tmp_path):
        mgr = _make_manager(tmp_path)
        assert mgr.should_stop_loss("0000.T", 100.0, 0.10) is False  # 未登録
        mgr.upsert("7203.T", _signal_info(close=None))
        assert mgr.should_stop_loss("7203.T", 100.0, 0.10) is False  # 基準価格なし
        assert mgr.should_stop_loss("7203.T", None, 0.10) is False   # 現在値なし


class TestMarketRegime:
    @staticmethod
    def _index_df(closes):
        idx = pd.date_range("2025-01-01", periods=len(closes), freq="B")
        return pd.DataFrame({"Close": closes}, index=idx)

    def test_insufficient_data_is_neutral(self):
        result = detect_market_regime(self._index_df(np.linspace(100, 110, 199)))
        assert result["regime"] == REGIME_NEUTRAL
        assert result["buy_threshold"] == 4

    def test_uptrend_is_bull(self):
        result = detect_market_regime(self._index_df(np.linspace(100, 200, 250)))
        assert result["regime"] == REGIME_BULL
        assert result["buy_threshold"] == 3

    def test_downtrend_is_bear(self):
        result = detect_market_regime(self._index_df(np.linspace(200, 100, 250)))
        assert result["regime"] == REGIME_BEAR
        assert result["buy_threshold"] == 5
