"""
tests/detectors/test_block_a.py — Тесты детектора A1 (html_link_search).

Два теста на каждый детектор: нарушение + соответствие.
HTTP-проверки отключены (verify_accessible=False) — тестируем только HTML-логику.
"""
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scanner.detectors.html_link_search import HtmlLinkSearchDetector

FIXTURES = Path(__file__).parent / "fixtures"
LAW_BASE = Path(__file__).parent.parent.parent / "law_base" / "blocks"


def _load_a1_config() -> dict:
    with (LAW_BASE / "A.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    config = data["violations"][0]
    config["detector"]["params"]["verify_accessible"] = False
    return config


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_a1_violation_no_link():
    """Страница без ссылки на политику ПДн — нарушение A1."""
    html = (FIXTURES / "a1_violation.html").read_text(encoding="utf-8")
    result = HtmlLinkSearchDetector(_load_a1_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "A1"
    assert result[0]["evidence"]["found"] is False


def test_a1_compliant_with_link():
    """Страница со ссылкой на политику в footer — нарушений нет."""
    html = (FIXTURES / "a1_compliant.html").read_text(encoding="utf-8")
    result = HtmlLinkSearchDetector(_load_a1_config()).detect(_soup(html), [])

    assert result == []
