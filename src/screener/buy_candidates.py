"""
購入候補リスト管理（output/buy_candidates.md + cache/buy_candidates.json）

・BUYシグナル発生時に銘柄を追加（重複除外・最新情報で更新）
・SELLシグナル発生時に銘柄を除外
・損切り: 初回推奨時の価格から一定率下落で除外（should_stop_loss）
・軸B ファンダメンタルズ劣化時に caution_flag を付与し、2回連続で除外
・output/buy_candidates.md を更新する

状態は Cache 経由で保存する（GCS_CACHE_BUCKET 設定時は GCS、未設定時はローカル）。
Cloud Run のエフェメラルディスクではローカルファイルが実行毎に消えるため、
直接のファイルI/Oでは追加日・caution_count がリセットされてしまう。
"""
import json
import os
from datetime import datetime
from typing import Optional

from src.utils.cache import Cache
from src.utils.logger import get_logger

logger = get_logger("buy_candidates")

_DEFAULT_CACHE = "cache/buy_candidates.json"
_DEFAULT_MD = "output/buy_candidates.md"

# 購入候補は明示的に除外されるまで保持する（TTLで消えてはいけない）
_STATE_TTL_HOURS = 24 * 3650


class BuyCandidatesManager:
    def __init__(
        self,
        cache_path: str = _DEFAULT_CACHE,
        md_path: str = _DEFAULT_MD,
        cache: Optional[Cache] = None,
    ):
        self.cache_path = cache_path
        self.md_path = md_path
        self._cache = cache or Cache(cache_dir=os.path.dirname(cache_path) or "cache")
        self._cache_key = os.path.splitext(os.path.basename(cache_path))[0]
        self._candidates: dict[str, dict] = self._load()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def upsert(self, ticker: str, signal_info: dict) -> None:
        """BUYシグナル発生時に追加または最新情報で更新する。"""
        existing = self._candidates.get(ticker, {})
        self._candidates[ticker] = {
            "ticker": ticker,
            "name": signal_info.get("name", existing.get("name", ticker)),
            "added_date": existing.get("added_date", datetime.now().strftime("%Y-%m-%d")),
            # 損切り判定の基準となる初回推奨時の株価（再BUYでは上書きしない）
            "entry_close": existing.get("entry_close", signal_info.get("close")),
            "last_signal_date": signal_info.get("date", datetime.now().strftime("%Y-%m-%d")),
            "signal_strength": signal_info.get("strength", 0),
            "close": signal_info.get("close"),
            "reasons": signal_info.get("reasons", ""),
            "caution_flag": False,  # BUYシグナル再発生でフラグリセット
            "caution_count": 0,
        }
        action = "更新" if ticker in self._candidates else "追加"
        logger.info(f"  購入候補リスト{action}: {ticker}")
        self._persist()

    def remove(self, ticker: str, reason: str = "") -> bool:
        """SELLシグナルまたは条件劣化で除外する。"""
        if ticker not in self._candidates:
            return False
        del self._candidates[ticker]
        logger.info(f"  購入候補リストから除外: {ticker}（理由: {reason}）")
        self._persist()
        return True

    def mark_caution(self, ticker: str) -> int:
        """
        軸Bファンダメンタルズ劣化時に caution_count をインクリメントする。
        2回以上になった場合は True を返す（呼び出し側が除外処理を行う）。
        """
        if ticker not in self._candidates:
            return 0
        entry = self._candidates[ticker]
        entry["caution_flag"] = True
        entry["caution_count"] = entry.get("caution_count", 0) + 1
        self._persist()
        logger.info(
            f"  購入候補 cautionフラグ: {ticker} "
            f"（count={entry['caution_count']}）"
        )
        return entry["caution_count"]

    def clear_caution(self, ticker: str) -> None:
        """週次で条件を再び満たした場合はフラグをリセットする。"""
        if ticker in self._candidates:
            self._candidates[ticker]["caution_flag"] = False
            self._candidates[ticker]["caution_count"] = 0
            self._persist()

    def should_stop_loss(self, ticker: str, current_close: Optional[float], stop_loss_pct: float) -> bool:
        """初回推奨時の価格から stop_loss_pct 以上下落していれば True を返す。"""
        entry = self._candidates.get(ticker)
        if not entry or not current_close or stop_loss_pct <= 0:
            return False
        entry_close = entry.get("entry_close") or entry.get("close")
        if not entry_close:
            return False
        return current_close <= entry_close * (1 - stop_loss_pct)

    def get_all(self) -> list[dict]:
        return list(self._candidates.values())

    def get_tickers(self) -> list[str]:
        return list(self._candidates.keys())

    def contains(self, ticker: str) -> bool:
        return ticker in self._candidates

    def write_markdown(self) -> None:
        """output/buy_candidates.md を最新状態で書き出す。"""
        os.makedirs(os.path.dirname(self.md_path), exist_ok=True)
        with open(self.md_path, "w", encoding="utf-8") as f:
            f.write(self._build_markdown())
        logger.info(f"購入候補リストを出力: {self.md_path}")

    # ------------------------------------------------------------------ #
    # Private helpers
    # ------------------------------------------------------------------ #

    def _load(self) -> dict[str, dict]:
        try:
            data = self._cache.get(self._cache_key, ttl_hours=_STATE_TTL_HOURS)
        except Exception:
            # 旧形式（Cacheラッパーなしの生JSON）のローカルファイルはここに落ちる
            data = None
        if data is None:
            data = self._load_legacy_file()
        if isinstance(data, list):
            return {item["ticker"]: item for item in data}
        if isinstance(data, dict):
            return data
        return {}

    def _load_legacy_file(self):
        """Cache導入前に直接書き出していた生JSONファイルからの移行読み込み。"""
        if not os.path.exists(self.cache_path):
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as f:
                entry = json.load(f)
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"購入候補キャッシュの読み込み失敗: {self.cache_path}")
            return None
        if isinstance(entry, dict) and "data" in entry and "saved_at" in entry:
            return entry["data"]
        return entry

    def _persist(self) -> None:
        self._cache.set(self._cache_key, list(self._candidates.values()))

    def _build_markdown(self) -> str:
        now = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        candidates = sorted(
            self._candidates.values(),
            key=lambda x: x.get("last_signal_date", ""),
            reverse=True,
        )

        lines = [
            "# 購入候補リスト",
            f"更新日時: {now}",
            "",
            "> BUYシグナルが発生した銘柄のリストです。",
            "> SELLシグナル発生またはファンダメンタルズ劣化（2回連続）で自動的に除外されます。",
            "",
            "---",
            "",
        ]

        if not candidates:
            lines += [
                "現在、購入候補銘柄はありません。",
                "",
                "> BUYシグナルが発生すると自動的にこのリストに追加されます。",
            ]
        else:
            lines += [
                f"**登録銘柄数**: {len(candidates)}社",
                "",
                "| 銘柄コード | 銘柄名 | 追加日 | 最終シグナル日 | シグナル強度 | 現在値 | 状態 |",
                "|-----------|--------|--------|---------------|------------|--------|------|",
            ]
            for c in candidates:
                caution = "⚠️ 要注意" if c.get("caution_flag") else "✅ 保持中"
                lines.append(
                    f"| {c['ticker']} | {c.get('name', c['ticker'])} "
                    f"| {c.get('added_date', 'N/A')} "
                    f"| {c.get('last_signal_date', 'N/A')} "
                    f"| {c.get('signal_strength', 'N/A')}/10 "
                    f"| {c.get('close', 'N/A')}円 "
                    f"| {caution} |"
                )

            lines += ["", "---", "", "## 銘柄詳細", ""]
            for c in candidates:
                caution_label = f" ⚠️ 要注意（{c.get('caution_count', 0)}回連続劣化）" if c.get("caution_flag") else ""
                lines += [
                    f"### {c.get('name', c['ticker'])}（{c['ticker']}）{caution_label}",
                    "",
                    f"- **追加日**: {c.get('added_date', 'N/A')}",
                    f"- **最終BUYシグナル日**: {c.get('last_signal_date', 'N/A')}",
                    f"- **シグナル強度**: {c.get('signal_strength', 'N/A')}/10",
                    f"- **現在値**: {c.get('close', 'N/A')}円",
                    f"- **判定理由**: {c.get('reasons', 'N/A')}",
                    "",
                    "---",
                    "",
                ]

        lines += [
            "## 免責事項",
            "",
            "> このリストは自動生成された情報提供を目的としたものであり、投資助言ではありません。",
            "> 投資判断はご自身の責任で行ってください。",
        ]

        return "\n".join(lines)
