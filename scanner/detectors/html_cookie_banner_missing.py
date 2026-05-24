"""
scanner/detectors/html_cookie_banner_missing.py — Детектор C1.

Нарушение: ст. 9 152-ФЗ → ч.1 ст.13.11 КоАП.
Штраф для юрлица: 150 000 – 300 000 руб.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.detectors.base import BaseDetector

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


class HtmlCookieBannerMissingDetector(BaseDetector):
    """
    Детектор C1: аналитика и cookie-файлы используются без согласия пользователя.

    Алгоритм:
    1. Проверить network_log на запросы к аналитическим доменам (intercept_domains).
       Если нашли — аналитика загружается ДО согласия → нарушение.
    2. Проверить HTML на сигнатуры аналитики (analytics_signatures).
       Если аналитика не найдена ни там ни там → нарушений нет.
    3. Если аналитика только в HTML (нет данных network_log):
       - Нет cookie-баннера → нарушение.
       - Есть баннер → рекомендация (нельзя подтвердить порядок загрузки без перехвата сети).
    """

    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        network_cfg = self.params.get("network_analysis", {})
        intercept_domains = network_cfg.get("intercept_domains", [])
        data_collection_patterns = network_cfg.get("data_collection_patterns", [])
        analytics_signatures = self.params.get("analytics_signatures", [])
        banner_selectors = self.params.get("banner_selectors", [])
        banner_keywords = self.params.get("banner_keywords", [])

        network_hits = _match_network_domains(network_log, intercept_domains)
        html_hits = _match_html_signatures(soup, analytics_signatures)

        if not network_hits and not html_hits:
            return []

        if network_hits:
            data_hits = _filter_data_collection(network_hits, data_collection_patterns)
            if data_hits:
                # Реальный сбор данных зафиксирован ДО согласия — нарушение
                return [self._build_result({
                    "detail": "Аналитика активно собирает данные до получения согласия пользователя",
                    "network_requests": data_hits,
                })]
            # Только загрузка скриптов — возможна отложенная инициализация (defer mode)
            result = self._build_result({
                "detail": (
                    "Скрипты аналитики загружаются до согласия. "
                    "Убедитесь, что инициализация счётчиков (ym('init', ...) и др.) "
                    "выполняется только после получения согласия пользователя"
                ),
                "network_requests": network_hits,
            })
            result["is_recommendation"] = True
            return [result]

        # HTML-only путь (нет данных network_log, например в тестах)
        banner_present = _has_cookie_banner(soup, banner_selectors, banner_keywords)

        if not banner_present:
            return [self._build_result({
                "detail": "Обнаружены скрипты аналитики. Cookie-баннер на странице отсутствует",
                "network_requests": [],
            })]

        # Аналитика в HTML + баннер присутствует, но порядок загрузки неизвестен
        result = self._build_result({
            "detail": (
                "Обнаружены скрипты аналитики и cookie-баннер. "
                "Без перехвата сети невозможно подтвердить, "
                "что аналитика не загружается до согласия"
            ),
            "network_requests": [],
        })
        result["is_recommendation"] = True
        return [result]


def _filter_data_collection(urls: list[str], patterns: list[str]) -> list[str]:
    """
    Фильтрует URL по паттернам реального сбора данных.

    Если patterns пустой — возвращает все urls (обратная совместимость: любой
    domain hit считается нарушением).
    Иначе возвращает только URLs, содержащие хотя бы один паттерн.
    """
    if not patterns:
        return urls
    return [url for url in urls if any(p in url for p in patterns)]


def _match_network_domains(
    network_log: list[dict], intercept_domains: list[str]
) -> list[str]:
    """Возвращает список URL из network_log, домен которых совпадает с intercept_domains."""
    hits = []
    for entry in network_log:
        domain = entry.get("domain", "")
        if any(domain == d or domain.endswith("." + d) for d in intercept_domains):
            url = entry.get("url", "")
            if url:
                hits.append(url)
    return hits


def _match_html_signatures(soup: BeautifulSoup, signatures: list[str]) -> list[str]:
    """Возвращает список сигнатур, найденных в исходном HTML (строковое совпадение)."""
    html_text = str(soup)
    return [sig for sig in signatures if sig in html_text]


def _has_cookie_banner(
    soup: BeautifulSoup,
    selectors: list[str],
    keywords: list[str],
) -> bool:
    """
    Проверяет наличие cookie-баннера двумя способами:
    1. CSS-селекторы (ID, классы, data-атрибуты) через soup.select()
    2. Ключевые слова в тексте страницы
    """
    for selector in selectors:
        try:
            if soup.select(selector):
                return True
        except Exception:
            pass

    page_text = soup.get_text(separator=" ").lower()
    return any(kw.lower() in page_text for kw in keywords)
