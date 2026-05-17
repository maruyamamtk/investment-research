"""
テスト: ClaudeAnalyzer.analyze_qualitative(), _normalize_qualitative(),
        および weekly_pipeline._format_qualitative_section()
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ai_analyst.claude_analyzer import (
    ClaudeAnalyzer,
    QUALITATIVE_LABELS,
    _normalize_qualitative,
    _qualitative_skipped,
)


# ============================================================
# _normalize_qualitative テスト
# ============================================================

class TestNormalizeQualitative:
    def _base_raw(self, label="Strong", score=7.5):
        return {
            "q1": {"label": label, "comment": "強い参入障壁がある"},
            "q2": {"label": "Moderate", "comment": "プロ経営者だが開示が少ない"},
            "q3": {"label": "Strong", "comment": "DX需要が追い風"},
            "q4": {"label": "Moderate", "comment": "顧客集中度が課題"},
            "q5": {"label": "Weak", "comment": "R&D比率が低い"},
            "overall_score": score,
            "overall_comment": "財務は堅調だが定性面で課題あり",
        }

    def test_valid_input_returns_all_keys(self):
        result = _normalize_qualitative(self._base_raw())
        assert set(result.keys()) == {"q1", "q2", "q3", "q4", "q5", "overall_score", "overall_comment"}

    def test_each_q_has_label_and_comment(self):
        result = _normalize_qualitative(self._base_raw())
        for q in ("q1", "q2", "q3", "q4", "q5"):
            assert "label" in result[q]
            assert "comment" in result[q]

    def test_valid_label_preserved(self):
        result = _normalize_qualitative(self._base_raw(label="Strong"))
        assert result["q1"]["label"] == "Strong"

    def test_invalid_label_becomes_unknown(self):
        raw = self._base_raw()
        raw["q1"]["label"] = "invalid_label"
        result = _normalize_qualitative(raw)
        assert result["q1"]["label"] == "Unknown"

    def test_overall_score_clamped_to_0_10(self):
        raw = self._base_raw(score=15.0)
        result = _normalize_qualitative(raw)
        assert result["overall_score"] == 10.0

        raw2 = self._base_raw(score=-3.0)
        result2 = _normalize_qualitative(raw2)
        assert result2["overall_score"] == 0.0

    def test_non_numeric_score_becomes_none(self):
        raw = self._base_raw()
        raw["overall_score"] = "seven"
        result = _normalize_qualitative(raw)
        assert result["overall_score"] is None

    def test_missing_q_key_uses_unknown(self):
        raw = {
            "overall_score": 5.0,
            "overall_comment": "テスト",
        }
        result = _normalize_qualitative(raw)
        for q in ("q1", "q2", "q3", "q4", "q5"):
            assert result[q]["label"] == "Unknown"

    def test_all_labels_are_valid(self):
        for label in QUALITATIVE_LABELS:
            raw = {
                "q1": {"label": label, "comment": "テスト"},
                "q2": {"label": label, "comment": ""},
                "q3": {"label": label, "comment": ""},
                "q4": {"label": label, "comment": ""},
                "q5": {"label": label, "comment": ""},
                "overall_score": 5.0,
                "overall_comment": "",
            }
            result = _normalize_qualitative(raw)
            assert result["q1"]["label"] == label


# ============================================================
# _qualitative_skipped テスト
# ============================================================

def test_qualitative_skipped_has_all_keys():
    result = _qualitative_skipped()
    assert set(result.keys()) == {"q1", "q2", "q3", "q4", "q5", "overall_score", "overall_comment"}


def test_qualitative_skipped_overall_score_is_none():
    result = _qualitative_skipped()
    assert result["overall_score"] is None


def test_qualitative_skipped_all_labels_unknown():
    result = _qualitative_skipped()
    for q in ("q1", "q2", "q3", "q4", "q5"):
        assert result[q]["label"] == "Unknown"


# ============================================================
# ClaudeAnalyzer.analyze_qualitative テスト
# ============================================================

class TestAnalyzeQualitative:
    def _make_analyzer_no_key(self):
        """APIキーなしの ClaudeAnalyzer を返す"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GEMINI_API_KEY", None)
            return ClaudeAnalyzer(api_key=None)

    def _make_analyzer_with_mock_client(self, json_response: dict):
        """モッククライアントを持つ ClaudeAnalyzer を返す"""
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(json_response)
        mock_client.models.generate_content.return_value = mock_response
        analyzer.client = mock_client
        analyzer.model = "gemini-2.0-flash"
        return analyzer

    def test_no_api_key_returns_skipped(self):
        analyzer = self._make_analyzer_no_key()
        result = analyzer.analyze_qualitative("7203.T", "トヨタ自動車")
        assert result["overall_score"] is None
        for q in ("q1", "q2", "q3", "q4", "q5"):
            assert result[q]["label"] == "Unknown"

    def test_valid_response_returns_normalized_dict(self):
        mock_json = {
            "q1": {"label": "Strong", "comment": "参入障壁が高い"},
            "q2": {"label": "Moderate", "comment": "プロ経営者"},
            "q3": {"label": "Strong", "comment": "DX需要"},
            "q4": {"label": "Moderate", "comment": "顧客集中度問題あり"},
            "q5": {"label": "Weak", "comment": "R&D比率低い"},
            "overall_score": 7.0,
            "overall_comment": "総合的に良好",
        }
        analyzer = self._make_analyzer_with_mock_client(mock_json)
        result = analyzer.analyze_qualitative("7203.T", "トヨタ自動車")
        assert result["q1"]["label"] == "Strong"
        assert result["overall_score"] == 7.0
        assert result["overall_comment"] == "総合的に良好"

    def test_gemini_api_error_returns_skipped(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("API Error")
        analyzer.client = mock_client
        analyzer.model = "gemini-2.0-flash"
        result = analyzer.analyze_qualitative("7203.T", "トヨタ自動車")
        assert result["overall_score"] is None

    def test_invalid_json_response_returns_skipped(self):
        analyzer = ClaudeAnalyzer.__new__(ClaudeAnalyzer)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "not valid json {{{"
        mock_client.models.generate_content.return_value = mock_response
        analyzer.client = mock_client
        analyzer.model = "gemini-2.0-flash"
        result = analyzer.analyze_qualitative("7203.T", "トヨタ自動車")
        assert result["overall_score"] is None

    def test_stock_data_included_in_prompt(self):
        """stock_data が渡された場合、generate_content が呼ばれることを確認"""
        mock_json = {
            "q1": {"label": "Strong", "comment": "test"},
            "q2": {"label": "Moderate", "comment": ""},
            "q3": {"label": "Moderate", "comment": ""},
            "q4": {"label": "Moderate", "comment": ""},
            "q5": {"label": "Moderate", "comment": ""},
            "overall_score": 6.0,
            "overall_comment": "test",
        }
        analyzer = self._make_analyzer_with_mock_client(mock_json)
        stock_data = {"sector": "自動車", "roe": 0.15, "operating_margins": 0.08}
        result = analyzer.analyze_qualitative("7203.T", "トヨタ自動車", stock_data=stock_data)
        assert analyzer.client.models.generate_content.called
        assert result["q1"]["label"] == "Strong"

    def test_return_type_is_dict_with_correct_structure(self):
        mock_json = {
            "q1": {"label": "Moderate", "comment": "c1"},
            "q2": {"label": "Moderate", "comment": "c2"},
            "q3": {"label": "Moderate", "comment": "c3"},
            "q4": {"label": "Moderate", "comment": "c4"},
            "q5": {"label": "Moderate", "comment": "c5"},
            "overall_score": 5.5,
            "overall_comment": "平均的",
        }
        analyzer = self._make_analyzer_with_mock_client(mock_json)
        result = analyzer.analyze_qualitative("9432.T", "NTT")
        assert isinstance(result, dict)
        assert isinstance(result["overall_score"], float)
        for q in ("q1", "q2", "q3", "q4", "q5"):
            assert isinstance(result[q]["label"], str)
            assert isinstance(result[q]["comment"], str)


# ============================================================
# _format_qualitative_section テスト（weekly_pipeline）
# ============================================================

class TestFormatQualitativeSection:
    def setup_method(self):
        import pipelines.weekly_pipeline as wp
        self.fmt = wp._format_qualitative_section

    def _sample_qualitative(self):
        return {
            "q1": {"label": "Strong", "comment": "参入障壁が高い"},
            "q2": {"label": "Moderate", "comment": "プロ経営者"},
            "q3": {"label": "Strong", "comment": "DX需要"},
            "q4": {"label": "Moderate", "comment": "顧客集中度 | 問題あり"},
            "q5": {"label": "Weak", "comment": "R&D比率低い"},
            "overall_score": 7.0,
            "overall_comment": "総合的に良好",
        }

    def test_none_returns_empty_list(self):
        assert self.fmt(None) == []

    def test_returns_list_of_strings(self):
        result = self.fmt(self._sample_qualitative())
        assert isinstance(result, list)
        assert all(isinstance(line, str) for line in result)

    def test_contains_all_q_labels(self):
        result = self.fmt(self._sample_qualitative())
        joined = "\n".join(result)
        for label in ("Q1 事業モデル", "Q2 経営陣", "Q3 市場環境", "Q4 顧客基盤", "Q5 組織力"):
            assert label in joined

    def test_pipe_in_comment_is_escaped(self):
        result = self.fmt(self._sample_qualitative())
        joined = "\n".join(result)
        # q4 の comment に含まれる | が ｜ に変換されているか
        assert "顧客集中度 ｜ 問題あり" in joined

    def test_overall_score_is_shown(self):
        result = self.fmt(self._sample_qualitative())
        joined = "\n".join(result)
        assert "7.0 / 10" in joined

    def test_overall_score_none_shows_na(self):
        q = self._sample_qualitative()
        q["overall_score"] = None
        result = self.fmt(q)
        joined = "\n".join(result)
        assert "N/A" in joined
