"""
tests/detectors/test_block_a.py — Тесты детектора A1 (html_link_search).

Два теста на каждый детектор: нарушение + соответствие.
HTTP-проверки отключены (verify_accessible=False) — тестируем только HTML-логику.
"""
from pathlib import Path
from unittest.mock import patch

import yaml
from bs4 import BeautifulSoup

from scanner.detectors.html_link_search import HtmlLinkSearchDetector, _is_accessible, _verify_policy_page

FIXTURES = Path(__file__).parent / "fixtures"
LAW_BASE = Path(__file__).parent.parent.parent / "law_base" / "blocks"


def _load_a1_config() -> dict:
    with (LAW_BASE / "A.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    config = next(v for v in data["violations"] if v["id"] == "A1")
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
    assert result[0]["evidence"]["detail"] != ""


def test_a1_compliant_with_link():
    """Страница со ссылкой на политику в footer — нарушений нет."""
    html = (FIXTURES / "a1_compliant.html").read_text(encoding="utf-8")
    result = HtmlLinkSearchDetector(_load_a1_config()).detect(_soup(html), [])

    assert result == []


# ── Тесты HTTP-проверки (benefit of doubt при блокировке) ───────────────────

def test_a1_is_accessible_404_returns_false():
    """404 — страница не существует, считаем недоступной."""
    params = {"min_status": 200, "max_status": 200}
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value.status_code = 404
        assert _is_accessible("https://example.com/privacy", params) is False


def test_a1_is_accessible_429_returns_false():
    """
    429 на шаге 3 (known_urls) — URL не подтверждён как существующий.
    _is_accessible строгий: только 200 = нашли. 429 = не нашли.
    """
    params = {"min_status": 200, "max_status": 200}
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value.status_code = 429
        assert _is_accessible("https://example.com/privacy", params) is False


def test_a1_is_accessible_exception_returns_false():
    """
    Сетевая ошибка на шаге 3 (known_urls) — URL не подтверждён.
    _is_accessible строгий: не смогли проверить = не нашли.
    """
    params = {"min_status": 200, "max_status": 200}
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = Exception("timeout")
        assert _is_accessible("https://example.com/privacy", params) is False


def test_a1_verify_policy_page_404_returns_false():
    """404 при verify — политики нет, нарушение."""
    params = {"min_status": 200, "max_status": 200, "content_keywords": [], "content_min_match": 1}
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value.status_code = 404
        assert _verify_policy_page("https://example.com/privacy", params) is False


def test_a1_verify_policy_page_429_returns_true():
    """429 при verify — benefit of doubt, не флагируем нарушение."""
    params = {"min_status": 200, "max_status": 200, "content_keywords": [], "content_min_match": 1}
    with patch("httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.return_value.status_code = 429
        assert _verify_policy_page("https://example.com/privacy", params) is True
