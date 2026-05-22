"""
tests/detectors/test_block_b.py — Тесты детекторов B1, B2, B3.

Два теста на каждый детектор: нарушение + соответствие.
"""
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scanner.detectors.html_checkbox_prechecked import HtmlCheckboxPrecheckedDetector
from scanner.detectors.html_form_no_consent import HtmlFormNoConsentDetector

FIXTURES = Path(__file__).parent / "fixtures"
LAW_BASE = Path(__file__).parent.parent.parent / "law_base" / "blocks"


def _load_b1_config() -> dict:
    with (LAW_BASE / "B.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["violations"][0]


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_b1_violation_checkbox_prechecked():
    """Форма с ПДн и предустановленным чекбоксом согласия — нарушение B1."""
    html = (FIXTURES / "b1_violation.html").read_text(encoding="utf-8")
    result = HtmlCheckboxPrecheckedDetector(_load_b1_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "B1"
    assert result[0]["evidence"]["form_index"] == 0
    assert result[0]["evidence"]["found"] is True


def test_b1_compliant_checkbox_unchecked():
    """Форма с ПДн и непредустановленным чекбоксом согласия — нарушений нет."""
    html = (FIXTURES / "b1_compliant.html").read_text(encoding="utf-8")
    result = HtmlCheckboxPrecheckedDetector(_load_b1_config()).detect(_soup(html), [])

    assert result == []


# ── B2 ────────────────────────────────────────────────────────────────────────

def _load_b2_config() -> dict:
    with (LAW_BASE / "B.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["violations"][1]


def test_b2_violation_no_consent_checkbox():
    """Форма с ПДн без чекбокса согласия — нарушение B2."""
    html = (FIXTURES / "b2_violation.html").read_text(encoding="utf-8")
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "B2"
    assert result[0]["evidence"]["form_index"] == 0
    assert result[0]["evidence"]["found"] is False


def test_b2_compliant_has_consent_checkbox():
    """Форма с ПДн и чекбоксом согласия — нарушений нет."""
    html = (FIXTURES / "b2_compliant.html").read_text(encoding="utf-8")
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])

    assert result == []
