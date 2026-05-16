"""
Gemini AI アナリスト
週次: 投資テーゼ・メモ生成
日次: シグナル解説生成
"""
import os
from typing import Optional

import google.genai as genai
from google.genai import types

from src.utils.logger import get_logger

logger = get_logger("gemini_analyzer")


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


def _pct(val) -> str:
    if val is None:
        return "N/A"
    return f"{val:.1%}"


def _val(val, suffix: str = "") -> str:
    if val is None:
        return "N/A"
    return f"{val:.2f}{suffix}"
