"""
Gemini AI アナリスト
週次: 投資テーゼ・メモ生成・定性分析（Q1〜Q5フレームワーク）
日次: シグナル解説生成
"""
import json
import os
from typing import Optional

import google.genai as genai
from google.genai import types

from src.utils.logger import get_logger

logger = get_logger("gemini_analyzer")

# Q1〜Q5 の評価ラベル定義
QUALITATIVE_LABELS = ("Strong", "Moderate", "Weak", "Unknown")

# 定性分析の空レスポンス（APIキー未設定・エラー時のフォールバック）
_QUALITATIVE_SKIP_COMMENT = "（AI分析: APIキー未設定のためスキップ）"

def _qualitative_skipped() -> dict:
    q = {"label": "Unknown", "comment": _QUALITATIVE_SKIP_COMMENT}
    return {
        "q1": q.copy(),
        "q2": q.copy(),
        "q3": q.copy(),
        "q4": q.copy(),
        "q5": q.copy(),
        "overall_score": None,
        "overall_comment": _QUALITATIVE_SKIP_COMMENT,
    }


class ClaudeAnalyzer:
    def __init__(self, api_key: Optional[str] = None, model: str = "gemini-2.0-flash"):
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            logger.warning("GEMINI_API_KEY未設定: AI分析機能は無効化されます")
            self.client = None
        else:
            self.client = genai.Client(api_key=key)
        self.model = model

    def _call(self, system: str, user: str, max_tokens: int = 800) -> str:
        if not self.client:
            return "（AI分析: APIキー未設定のためスキップ）"
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=0.3,
                ),
            )
            return response.text.strip()
        except Exception as e:
            logger.error(f"Gemini API呼び出し失敗: {e}")
            return f"（AI分析エラー: {e}）"

    def _call_json(self, system: str, user: str, max_tokens: int = 1500) -> Optional[dict]:
        """JSON出力モードでGeminiを呼び出し、パース済みdictを返す。失敗時はNone。"""
        if not self.client:
            return None
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=max_tokens,
                    temperature=0.2,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini JSON API呼び出し失敗: {e}")
            return None

    # ---- 週次: 投資メモ生成 ----

    def generate_investment_memo(self, stock_data: dict) -> str:
        """
        1銘柄の財務データから投資テーゼ（強み・リスク・バリュエーション）メモを生成する。
        """
        system = (
            "あなたは日本株投資の専門アナリストです。"
            "提供された財務データをもとに、中長期投資家向けの投資メモを日本語で簡潔に記述してください。"
            "強み・成長ドライバー、主なリスク要因、バリュエーション評価の3点を含めてください。"
            "200〜300字程度で記述すること。"
        )
        user = f"""
銘柄: {stock_data.get('name', '')} ({stock_data.get('ticker', '')})
セクター: {stock_data.get('sector', 'N/A')} / {stock_data.get('industry', 'N/A')}
ROE: {_pct(stock_data.get('roe'))}
売上高CAGR（3年）: {_pct(stock_data.get('revenue_cagr'))}
営業利益率: {_pct(stock_data.get('operating_margins'))}
ネット有利子負債/EBITDA: {_val(stock_data.get('net_debt_ebitda'), 'x')}
FCFプラス年数（直近3期中）: {stock_data.get('fcf_positive_years', 'N/A')}
CF品質（OCF/純利益）: {_val(stock_data.get('cf_quality'))}
PER: {_val(stock_data.get('pe_ratio'), 'x')}
PBR: {_val(stock_data.get('pbr'), 'x')}
総合スコア: {_val(stock_data.get('total_score'), '点')}
"""
        return self._call(system, user, max_tokens=600)

    def generate_bear_case(self, stock_data: dict) -> str:
        """ベアケース（弱気要因）のスコアリングと分析を生成する"""
        system = (
            "あなたはリスク管理の専門家です。"
            "提供された銘柄情報から、投資上の最悪シナリオ（弱気要因）を分析し、"
            "リスクスコア（0〜10）と主なリスク要因を日本語で簡潔に記述してください。"
            "地政学リスク・金利上昇耐性・業界競争・財務脆弱性の観点を含めること。"
        )
        user = f"""
銘柄: {stock_data.get('name', '')} ({stock_data.get('ticker', '')})
セクター: {stock_data.get('sector', 'N/A')}
ネット有利子負債/EBITDA: {_val(stock_data.get('net_debt_ebitda'), 'x')}
営業利益率: {_pct(stock_data.get('operating_margins'))}
自己資本比率: {_pct(stock_data.get('equity_ratio'))}

以下の形式で出力:
リスクスコア: X/10
主なリスク要因:
- （要因1）
- （要因2）
- （要因3）
"""
        return self._call(system, user, max_tokens=400)

    # ---- 週次: 定性分析（Q1〜Q5フレームワーク） ----

    def analyze_qualitative(
        self,
        ticker: str,
        company_name: str,
        stock_data: Optional[dict] = None,
    ) -> dict:
        """Q1〜Q5フレームワークによる定性分析を実行し、構造化データを返す。

        Returns:
            {
                "q1": {"label": "Strong|Moderate|Weak|Unknown", "comment": str},
                "q2": {"label": ..., "comment": str},
                "q3": {"label": ..., "comment": str},
                "q4": {"label": ..., "comment": str},
                "q5": {"label": ..., "comment": str},
                "overall_score": float | None,  # 0〜10
                "overall_comment": str,
            }
        """
        if not self.client:
            return _qualitative_skipped()

        sd = stock_data or {}
        context = (
            f"セクター: {sd.get('sector', 'N/A')} / {sd.get('industry', 'N/A')}\n"
            f"ROE: {_pct(sd.get('roe'))}  "
            f"営業利益率: {_pct(sd.get('operating_margins'))}  "
            f"売上高CAGR(3年): {_pct(sd.get('revenue_cagr'))}"
            if sd else ""
        )

        system = (
            "あなたは日本株投資の定性分析の専門家です。"
            "指定された銘柄について、5つの評価フレームワーク（Q1〜Q5）に沿って定性評価を行い、"
            "必ず以下のJSONスキーマに従って日本語で回答してください。\n\n"
            "評価ラベルは Strong / Moderate / Weak / Unknown のいずれか1つ。\n"
            "公開情報が不足している場合は Unknown を使用し、comment に理由を記載すること。\n\n"
            "JSONスキーマ:\n"
            "{\n"
            '  "q1": {"label": "...", "comment": "..."},\n'
            '  "q2": {"label": "...", "comment": "..."},\n'
            '  "q3": {"label": "...", "comment": "..."},\n'
            '  "q4": {"label": "...", "comment": "..."},\n'
            '  "q5": {"label": "...", "comment": "..."},\n'
            '  "overall_score": 数値(0〜10),\n'
            '  "overall_comment": "..."\n'
            "}"
        )

        user = f"""以下の銘柄について定性評価を行ってください。

銘柄: {company_name}（{ticker}）
{context}

【評価フレームワーク】
Q1: 事業モデルと競争優位性（Economic Moat）
  - マネタイズ構造（ストック型 vs. フロー型）・参入障壁（特許・規制・スイッチングコスト）
  - ネットワーク効果・価格決定権の有無

Q2: 経営陣の質とガバナンス
  - 創業者 or プロ経営者・過去のトラックレコード・中計ビジョンの一貫性
  - 経営陣の自社株保有比率・IR開示の誠実さ

Q3: 市場環境と成長ポテンシャル（TAM/SAM）
  - 業界ライフサイクル（黎明期〜成熟期）・国策・規制の追い風
  - グローバル拡張可能性・DX/少子高齢化/脱炭素などメガトレンドとの整合

Q4: 顧客基盤とサプライチェーン
  - 売上集中度（特定顧客依存リスク）・BtoBの解約率/リピート率
  - 調達先の地域・企業集中リスク

Q5: 組織力と企業文化
  - 優秀人材の獲得力・離職率・R&D投資比率
  - 次の成長の種（新製品/新サービス）を仕込む文化の有無

各Q項目は1〜2文の根拠コメントを付けてください。
overall_score は Q1〜Q5 の評価を総合した 0〜10 の数値（小数点1桁）。
overall_comment は総合評価の要約（50〜100字）。
"""
        result = self._call_json(system, user, max_tokens=1500)
        if not result:
            return _qualitative_skipped()

        return _normalize_qualitative(result)

    # ---- 日次: シグナル解説生成 ----

    def explain_signal(self, ticker: str, name: str, signal_result: dict) -> str:
        """テクニカルシグナルの判定理由を自然言語で解説する"""
        system = (
            "あなたは株式テクニカルアナリストです。"
            "提供されたテクニカル指標データをもとに、売買シグナルの理由を"
            "個人投資家にわかりやすい日本語で80〜120字で解説してください。"
        )
        ind = signal_result.get("indicators", {})
        reasons = "、".join(signal_result.get("reasons", []))
        user = f"""
銘柄: {name} ({ticker})
シグナル: {signal_result.get('signal')}（強度: {signal_result.get('strength')}/10）
判定日: {signal_result.get('date')}
現在値: {ind.get('close')}円
SMA5/20: {ind.get('sma5')}/{ind.get('sma20')}
RSI14: {ind.get('rsi14')}
MACDヒスト: {ind.get('macd_hist')}
出来高比率: {ind.get('volume_ratio')}x
判定理由: {reasons}
"""
        return self._call(system, user, max_tokens=300)


# ── ヘルパー ──────────────────────────────────────────────

def _normalize_qualitative(raw: dict) -> dict:
    """GeminiのJSON出力を正規化し、必須キーを補完する。"""
    result = {}
    for q in ("q1", "q2", "q3", "q4", "q5"):
        entry = raw.get(q, {})
        label = entry.get("label", "Unknown")
        if label not in QUALITATIVE_LABELS:
            label = "Unknown"
        result[q] = {"label": label, "comment": str(entry.get("comment", ""))}

    raw_score = raw.get("overall_score")
    try:
        score = float(raw_score)
        score = max(0.0, min(10.0, score))
    except (TypeError, ValueError):
        score = None

    result["overall_score"] = score
    result["overall_comment"] = str(raw.get("overall_comment", ""))
    return result


def _pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1%}"


def _val(val, suffix: str = "") -> str:
    if val is None:
        return "N/A"
    return f"{val:.2f}{suffix}"
