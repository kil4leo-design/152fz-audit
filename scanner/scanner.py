"""
scanner/scanner.py — Оркестратор сканирования.

Связывает PlaywrightWrapper → BeautifulSoup → DetectorEngine.
Браузер живёт всё время жизни Scanner — не создаётся заново на каждый запрос.

Использование (скрипт):
    async with Scanner() as s:
        violations = await s.scan("https://example.com")

Использование (FastAPI lifespan):
    @asynccontextmanager
    async def lifespan(app):
        async with Scanner() as scanner:
            app.state.scanner = scanner
            yield
"""
from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup

from scanner.engine import DetectorEngine
from scanner.playwright_wrapper import PlaywrightWrapper, RobotsDisallowedError

__all__ = ["Scanner", "RobotsDisallowedError"]


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

    async def scan(self, url: str) -> list[dict]:
        """
        Загрузить страницу по URL и вернуть список нарушений 152-ФЗ.

        :raises RobotsDisallowedError: если robots.txt запрещает сканирование
        :raises RuntimeError: если вызвано вне async with
        :raises PlaywrightError: ошибка загрузки страницы (сеть, таймаут и т.д.)
        :return: список нарушений в формате из architecture.md
        """
        html, network_log = await self._pw.scan(url)
        soup = BeautifulSoup(html, "html.parser")
        return self._engine.run_all(soup, network_log)
