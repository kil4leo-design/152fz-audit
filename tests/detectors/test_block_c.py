"""
tests/detectors/test_block_c.py — Тесты детектора C1 (html_cookie_banner_missing).

Три теста: нарушение, соответствие, рекомендация (аналитика + баннер).
network_log=[] — тестируем только HTML-логику.
"""
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scanner.detectors.html_cookie_banner_missing import HtmlCookieBannerMissingDetector

FIXTURES = Path(__file__).parent / "fixtures"
LAW_BASE = Path(__file__).parent.parent.parent / "law_base" / "blocks"


def _load_c1_config() -> dict:
    with (LAW_BASE / "C.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return next(v for v in data["violations"] if v["id"] == "C1")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_c1_violation_analytics_no_banner():
    """Страница со скриптом аналитики и без cookie-баннера — нарушение C1."""
    html = (FIXTURES / "c1_violation.html").read_text(encoding="utf-8")
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "C1"
    assert result[0]["is_recommendation"] is False
    assert result[0]["evidence"]["detail"] != ""
    assert result[0]["evidence"]["network_requests"] == []


def test_c1_compliant_no_analytics():
    """Страница без скриптов аналитики — нарушений нет."""
    html = (FIXTURES / "c1_compliant.html").read_text(encoding="utf-8")
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), [])

    assert result == []


def test_c1_recommendation_analytics_with_banner():
    """Аналитика в HTML + cookie-баннер без данных network_log — рекомендация, не нарушение."""
    html = (FIXTURES / "c1_recommendation.html").read_text(encoding="utf-8")
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "C1"
    assert result[0]["is_recommendation"] is True
    assert result[0]["evidence"]["network_requests"] == []


# ── Регрессионный тест Bug 1 — domain matching ────────────────────────────────

def test_c1_no_false_positive_subdomain_lookalike():
    """
    Домен 'fakesegment.io' не должен совпадать с 'segment.io' из intercept_domains.
    Substring match давал ложное срабатывание: 'segment.io' in 'fakesegment.io' == True.
    """
    html = (FIXTURES / "c1_compliant.html").read_text(encoding="utf-8")
    network_log = [
        {"url": "https://fakesegment.io/track", "domain": "fakesegment.io", "timestamp": 1.0},
        {"url": "https://not-google-analytics.com/js", "domain": "not-google-analytics.com", "timestamp": 1.1},
    ]
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), network_log)
    assert result == [], f"Ложное срабатывание C1 на посторонний домен: {result}"


def test_c1_recommendation_script_load_exact_domain():
    """
    Только загрузка скрипта Яндекс.Метрики (tag.js) — рекомендация, не нарушение.
    Сайт может использовать defer mode: скрипт загружается, но ym('init',...) отложен.
    """
    html = (FIXTURES / "c1_compliant.html").read_text(encoding="utf-8")
    network_log = [
        {"url": "https://mc.yandex.ru/metrika/tag.js", "domain": "mc.yandex.ru", "timestamp": 1.0},
    ]
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), network_log)
    assert len(result) == 1
    assert result[0]["id"] == "C1"
    assert result[0]["is_recommendation"] is True
    assert "mc.yandex.ru/metrika/tag.js" in result[0]["evidence"]["network_requests"][0]


def test_c1_recommendation_script_load_subdomain():
    """Загрузка скрипта с поддомена s.mc.yandex.ru — рекомендация (defer mode возможен)."""
    html = (FIXTURES / "c1_compliant.html").read_text(encoding="utf-8")
    network_log = [
        {"url": "https://s.mc.yandex.ru/metrika/tag.js", "domain": "s.mc.yandex.ru", "timestamp": 1.0},
    ]
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), network_log)
    assert len(result) == 1
    assert result[0]["id"] == "C1"
    assert result[0]["is_recommendation"] is True


def test_c1_violation_data_collection_network():
    """Запрос /watch/ (реальный сбор данных Яндекс.Метрики) в network_log — нарушение C1."""
    html = (FIXTURES / "c1_compliant.html").read_text(encoding="utf-8")
    network_log = [
        {"url": "https://mc.yandex.ru/watch/12345678", "domain": "mc.yandex.ru", "timestamp": 1.0},
    ]
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), network_log)
    assert len(result) == 1
    assert result[0]["id"] == "C1"
    assert result[0]["is_recommendation"] is False
    assert "mc.yandex.ru/watch/12345678" in result[0]["evidence"]["network_requests"][0]


def test_c1_violation_data_collection_ga4_network():
    """Запрос /g/collect (Google Analytics 4) в network_log — нарушение C1."""
    html = (FIXTURES / "c1_compliant.html").read_text(encoding="utf-8")
    network_log = [
        {"url": "https://mc.yandex.ru/metrika/tag.js", "domain": "mc.yandex.ru", "timestamp": 1.0},
        {"url": "https://www.google-analytics.com/g/collect?v=2&tid=G-XXX", "domain": "google-analytics.com", "timestamp": 1.1},
    ]
    result = HtmlCookieBannerMissingDetector(_load_c1_config()).detect(_soup(html), network_log)
    assert len(result) == 1
    assert result[0]["id"] == "C1"
    assert result[0]["is_recommendation"] is False
    assert any("g/collect" in url for url in result[0]["evidence"]["network_requests"])
