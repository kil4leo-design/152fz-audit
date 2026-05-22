"""
scanner/playwright_wrapper.py — Playwright wrapper для загрузки страниц.

Ответственности:
1. Проверка robots.txt перед любым сканированием
2. Перехват всех исходящих сетевых запросов (network_log)
3. Загрузка страницы (networkidle + 2 секунды для динамического контента)
4. Rate limiting — минимум 2 секунды между запросами к одному домену

Поведение зафиксировано в architecture.md → раздел "PlaywrightWrapper".

Использование:
    async with PlaywrightWrapper() as pw:
        html, network_log = await pw.scan("https://example.com")
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import Browser, async_playwright

_UA = "Mozilla/5.0 (compatible; 152fz-audit/1.0; +https://github.com/kil4leo-design/152fz-audit)"
_RATE_LIMIT_SECONDS = 2.0
_ROBOTS_TIMEOUT_SECONDS = 5.0


class RobotsDisallowedError(Exception):
    """Поднимается когда robots.txt запрещает сканирование URL."""


class PlaywrightWrapper:
    """
    Async context manager для загрузки страниц через Playwright.

    Каждый вызов scan() создаёт изолированный браузерный контекст
    (нет cookies между сканированиями).

    Использование:
        async with PlaywrightWrapper() as pw:
            html, network_log = await pw.scan("https://example.com")
    """

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        # domain → время последнего запроса (для rate limiting)
        self._last_request: dict[str, float] = {}

    async def __aenter__(self) -> PlaywrightWrapper:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        return self

    async def __aexit__(self, *_args: Any) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scan(self, url: str) -> tuple[str, list[dict]]:
        """
        Загрузить страницу и вернуть (html, network_log).

        Конвенция network_log:
        - network_log[0] — запрос к сканируемой странице (используется детектором A1
          для построения base_url при проверке known_urls)
        - Каждый элемент: {"url": str, "domain": str, "timestamp": float}

        :raises RobotsDisallowedError: robots.txt запрещает сканирование URL
        :raises RuntimeError: вызвано вне async with
        :raises PlaywrightError: ошибка загрузки страницы (таймаут, сеть и т.д.)
        """
        if self._browser is None:
            raise RuntimeError(
                "PlaywrightWrapper не инициализирован — использовать как async with."
            )

        if not await _robots_allowed(url):
            raise RobotsDisallowedError(url)

        domain = _extract_domain(url)
        await self._enforce_rate_limit(domain)

        network_log: list[dict] = []
        context = await self._browser.new_context(
            user_agent=_UA,
            ignore_https_errors=True,
        )
        try:
            page = await context.new_page()
            page.on(
                "request",
                lambda req: network_log.append({
                    "url": req.url,
                    "domain": _extract_domain(req.url),
                    "timestamp": time.time(),
                }),
            )
            await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            html = await page.content()
        finally:
            await context.close()
            self._last_request[domain] = time.time()

        return html, network_log

    async def _enforce_rate_limit(self, domain: str) -> None:
        """Задержка если с момента последнего запроса к домену прошло менее 2 секунд."""
        elapsed = time.time() - self._last_request.get(domain, 0.0)
        if elapsed < _RATE_LIMIT_SECONDS:
            await asyncio.sleep(_RATE_LIMIT_SECONDS - elapsed)


async def _robots_allowed(url: str) -> bool:
    """
    Проверяет robots.txt через stdlib RobotFileParser.

    Таймаут 5 секунд. Если robots.txt недоступен или ошибка — разрешаем
    (стандартная практика: недоступный robots.txt не означает запрет).
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser(robots_url)
    try:
        await asyncio.wait_for(asyncio.to_thread(rp.read), timeout=_ROBOTS_TIMEOUT_SECONDS)
    except Exception:
        return True
    return rp.can_fetch(_UA, url)


def _extract_domain(url: str) -> str:
    """Hostname из URL без порта. Пустая строка если URL невалиден."""
    return urlparse(url).hostname or ""
