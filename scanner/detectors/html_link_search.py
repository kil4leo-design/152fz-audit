"""
scanner/detectors/html_link_search.py — Детектор A1.

Нарушение: ст. 18.1 ч.2 152-ФЗ → ч.3 ст.13.11 КоАП.
Штраф для юрлица: 30 000 – 60 000 руб.
"""
from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import httpx

from scanner.detectors.base import BaseDetector

if TYPE_CHECKING:
    from bs4 import BeautifulSoup

_UA = "Mozilla/5.0 (compatible; 152fz-audit/1.0; +https://github.com/kil4leo-design/152fz-audit)"


class HtmlLinkSearchDetector(BaseDetector):
    """
    Детектор A1: проверяет наличие ссылки на политику обработки ПДн.

    Алгоритм:
    1. Поиск <a> с ключевым словом в primary_scope (footer, header, nav).
    2. Если не найдено — поиск в fallback_scope (body).
    3. Если не найдено — проверка known_urls (GET, статус 200).
    4. Если verify_accessible=True — проверка содержимого найденной страницы.

    Шаги 3 и 4 требуют base_url (из network_log[0]). Если network_log пуст —
    шаги 3 и 4 пропускаются.
    """

    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        keywords = [kw.lower() for kw in self.params.get("keywords", [])]
        base_url = _extract_base_url(network_log)
        checked_urls: list[str] = []

        # Шаг 1 — primary_scope
        found_url = self._find_in_scope(
            soup, self.params.get("primary_scope", []), keywords, base_url
        )

        # Шаг 2 — fallback_scope
        if not found_url:
            fallback = self.params.get("fallback_scope")
            if fallback:
                found_url = self._find_in_scope(
                    soup, [fallback], keywords, base_url
                )

        # Шаг 3 — known_urls (только если в HTML не найдено и base_url известен)
        if not found_url and base_url:
            for path in self.params.get("known_urls", []):
                url = urljoin(base_url, path)
                checked_urls.append(url)
                if _is_accessible(url, self.params):
                    found_url = url
                    break

        # Шаг 4 — verify_accessible: проверка содержимого найденной страницы
        if found_url and self.params.get("verify_accessible") and base_url:
            if not _verify_policy_page(found_url, self.params):
                found_url = None

        if found_url:
            return []

        return [self._build_result({
            "detail": "Ссылка на политику обработки ПДн не найдена на странице",
            "checked_urls": checked_urls,
        })]

    def _find_in_scope(
        self,
        soup: BeautifulSoup,
        selectors: list[str],
        keywords: list[str],
        base_url: str | None,
    ) -> str | None:
        """Ищет <a> с ключевым словом в тексте или href для каждого CSS-селектора."""
        for selector in selectors:
            for container in soup.select(selector):
                for a_tag in container.find_all("a", href=True):
                    href_raw = a_tag.get("href", "")
                    if not href_raw or href_raw.startswith(
                        ("#", "javascript:", "mailto:", "tel:")
                    ):
                        continue
                    href_lower = href_raw.lower()
                    text_lower = a_tag.get_text(strip=True).lower()
                    if any(kw in href_lower or kw in text_lower for kw in keywords):
                        return urljoin(base_url, href_raw) if base_url else href_raw
        return None


def _extract_base_url(network_log: list[dict]) -> str | None:
    """
    scheme://host из первого элемента network_log.
    Конвенция: network_log[0] — запрос к сканируемой странице.
    """
    if not network_log:
        return None
    parsed = urlparse(network_log[0].get("url", ""))
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def _is_accessible(url: str, params: dict) -> bool:
    """
    Проверяет что URL возвращает статус в диапазоне [min_status, max_status].

    404 → недоступна (нарушение).
    429/5xx/исключение → неизвестно, считаем доступной (избегаем ложного срабатывания).
    Сайты с rate limiting или WAF возвращают 429/403 на bot UA — не означает отсутствие политики.
    """
    min_s = params.get("min_status", 200)
    max_s = params.get("max_status", 200)
    try:
        with httpx.Client(
            headers={"User-Agent": _UA}, follow_redirects=True, timeout=10
        ) as client:
            status = client.get(url).status_code
        if status == 404:
            return False
        return True  # 200 OK или заблокировано (429/403/5xx) — benefit of doubt
    except Exception:
        return True


def _verify_policy_page(url: str, params: dict) -> bool:
    """
    GET + проверка статуса + минимум content_min_match ключевых слов в тексте.
    GET вместо HEAD: HEAD не позволяет проверить содержимое страницы.

    404 → политики нет (нарушение).
    429/5xx/исключение → неизвестно, считаем верифицированной (benefit of doubt).
    """
    min_s = params.get("min_status", 200)
    max_s = params.get("max_status", 200)
    content_kws = [kw.lower() for kw in params.get("content_keywords", [])]
    min_match = params.get("content_min_match", 1)
    try:
        with httpx.Client(
            headers={"User-Agent": _UA}, follow_redirects=True, timeout=10
        ) as client:
            resp = client.get(url)
        if resp.status_code == 404:
            return False
        if not (min_s <= resp.status_code <= max_s):
            return True  # заблокировано/ошибка сервера — не означает отсутствие политики
        text = resp.text.lower()
        return sum(1 for kw in content_kws if kw in text) >= min_match
    except Exception:
        return True
