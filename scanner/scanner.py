"""
scanner/scanner.py — Оркестратор сканирования.

Связывает PlaywrightWrapper → BeautifulSoup → DetectorEngine.
Браузер живёт всё время жизни Scanner — не создаётся заново на каждый запрос.

Использование (скрипт):
    async with Scanner() as s:
        violations, robots_warning = await s.scan("https://example.com")

Использование (FastAPI lifespan):
    @asynccontextmanager
    async def lifespan(app):
        async with Scanner() as scanner:
            app.state.scanner = scanner
            yield
"""
from __future__ import annotations

import asyncio
from typing import Any

from bs4 import BeautifulSoup

from scanner.engine import DetectorEngine
from scanner.playwright_wrapper import PlaywrightWrapper

__all__ = ["Scanner"]


class Scanner:
    """
    Async context manager для сканирования сайтов.

    Браузер запускается один раз при входе в контекст и закрывается при выходе.
    DetectorEngine (с загруженным Law Base) создаётся один раз при инициализации.
    """

    def __init__(self) -> None:
        self._engine = DetectorEngine()
        self._pw = PlaywrightWrapper()

    async def __aenter__(self) -> Scanner:
        await self._pw.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._pw.__aexit__(*args)

    async def scan(self, url: str) -> tuple[list[dict], list[dict], bool, bool, str]:
        """
        Загрузить страницу по URL и вернуть
        (violations, passed, robots_warning, waf_blocked, blocked_excerpt).

        robots_warning=True если robots.txt ограничивает доступ (Вариант B).
        waf_blocked=True если WAF вернул challenge-страницу — детекторы не запускаются.
        blocked_excerpt — первые 1500 символов текста challenge-страницы (пусто если не заблокировано).

        :raises RuntimeError: если вызвано вне async with
        :raises PlaywrightError: ошибка загрузки страницы (сеть, таймаут и т.д.)
        :return: (нарушения, пройденные проверки, robots_warning, waf_blocked, blocked_excerpt)
        """
        html, network_log, robots_warning, waf_blocked = await self._pw.scan(url)

        if waf_blocked:
            soup = BeautifulSoup(html, "html.parser")
            blocked_excerpt = soup.get_text(separator="\n", strip=True)[:1500]
            return [], [], robots_warning, True, blocked_excerpt

        soup = BeautifulSoup(html, "html.parser")
        # run_all синхронный; A1 делает HTTP-запросы внутри — запускаем в thread
        violations, passed = await asyncio.to_thread(self._engine.run_all, soup, network_log)
        return violations, passed, robots_warning, waf_blocked, ""
