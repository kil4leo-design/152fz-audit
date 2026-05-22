"""
scanner/scanner.py — Оркестратор сканирования.

Связывает PlaywrightWrapper → BeautifulSoup → DetectorEngine.
Принимает URL, возвращает список нарушений.

Использование:
    violations = await scan(url)
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from scanner.engine import DetectorEngine
from scanner.playwright_wrapper import PlaywrightWrapper, RobotsDisallowedError

__all__ = ["scan", "RobotsDisallowedError"]

_engine = DetectorEngine()


async def scan(url: str) -> list[dict]:
    """
    Загрузить страницу по URL и вернуть список нарушений 152-ФЗ.

    :raises RobotsDisallowedError: если robots.txt запрещает сканирование
    :raises Exception: любая ошибка Playwright (сеть, таймаут и т.д.)
    :return: список нарушений — каждый элемент в формате из architecture.md
    """
    async with PlaywrightWrapper() as pw:
        html, network_log = await pw.scan(url)

    soup = BeautifulSoup(html, "html.parser")
    return _engine.run_all(soup, network_log)
