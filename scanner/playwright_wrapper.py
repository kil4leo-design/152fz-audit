"""
scanner/playwright_wrapper.py — Playwright wrapper для загрузки страниц.

Ответственности:
1. Проверка robots.txt — возвращает предупреждение (не блокирует скан)
2. Stealth mode — маскировка под реальный браузер для обхода WAF (DDoS-Guard, Cloudflare)
3. Перехват всех исходящих сетевых запросов (network_log)
4. Загрузка страницы (networkidle + 2 секунды для динамического контента)
5. Rate limiting — минимум 2 секунды между запросами к одному домену
6. WAF detection — если stealth не помог, детектируем и сигнализируем в отчёт

Стратегия robots.txt (Вариант B, сессия 9):
Сканирование выполняется всегда — целевой пользователь проверяет свой сайт.

Stealth mode (сессия 9):
WAF (DDoS-Guard, Cloudflare) детектируют headless Playwright по navigator.webdriver=true
и специфичным fingerprints. Патчим через init_script и launch args. Для robots.txt
используем честный bot UA — для страницы реальный Chrome UA (иначе WAF блокирует).

Поведение зафиксировано в architecture.md → раздел "PlaywrightWrapper".

Использование:
    async with PlaywrightWrapper() as pw:
        html, network_log, robots_warning, waf_blocked = await pw.scan("https://example.com")
"""
from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from playwright.async_api import Browser, async_playwright

# Честный bot UA — для robots.txt (прозрачная идентификация)
_ROBOTS_UA = "Mozilla/5.0 (compatible; 152fz-audit/1.0; +https://github.com/kil4leo-design/152fz-audit)"

# Реальный Chrome UA — для загрузки страницы (WAF пропускает реальные браузеры)
_PAGE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_RATE_LIMIT_SECONDS = 2.0
_ROBOTS_TIMEOUT_SECONDS = 5.0

# Убирает следы Playwright/автоматизации — обходит DDoS-Guard и большинство WAF.
# navigator.webdriver=true — главный маркер headless-браузера для WAF.
_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [
    {name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format'},
    {name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: ''},
    {name: 'Native Client', filename: 'internal-nacl-plugin', description: ''}
]});
window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
"""

# Сигнатуры challenge-страниц WAF — детектируем если stealth не помог
_WAF_SIGNATURES = [
    "ddos-guard",
    "cloudflare",
    "just a moment",
    "checking your browser",
    "access denied",
    "enable javascript and cookies",
]


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
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            # Убирает главный fingerprint-маркер автоматизации
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    async def __aexit__(self, *_args: Any) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def scan(self, url: str) -> tuple[str, list[dict], bool, bool]:
        """
        Загрузить страницу и вернуть (html, network_log, robots_warning, waf_blocked).

        robots_warning=True если robots.txt ограничивает доступ — скан выполняется всегда.
        waf_blocked=True если WAF вернул challenge-страницу вместо реального сайта
        (результаты ненадёжны — stealth не помог).

        Конвенция network_log:
        - network_log[0] — запрос к сканируемой странице (используется детектором A1
          для построения base_url при проверке known_urls)
        - Каждый элемент: {"url": str, "domain": str, "timestamp": float}

        :raises RuntimeError: вызвано вне async with
        :raises PlaywrightError: ошибка загрузки страницы (таймаут, сеть и т.д.)
        """
        if self._browser is None:
            raise RuntimeError(
                "PlaywrightWrapper не инициализирован — использовать как async with."
            )

        robots_warning = not await _robots_allowed(url)
        domain = _extract_domain(url)
        await self._enforce_rate_limit(domain)

        network_log: list[dict] = []
        context = await self._browser.new_context(
            user_agent=_PAGE_UA,
            ignore_https_errors=True,
        )
        try:
            # Патч fingerprints до первого запроса — обходит DDoS-Guard и Cloudflare
            await context.add_init_script(_STEALTH_SCRIPT)
            page = await context.new_page()
            page.on(
                "request",
                lambda req: network_log.append({
                    "url": req.url,
                    "domain": _extract_domain(req.url),
                    "timestamp": time.time(),
                }),
            )
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            try:
                html = await page.content()
            except Exception as e:
                if "navigating" in str(e).lower():
                    # Страница продолжает навигировать (JS-редирект, SPA).
                    # Ждём domcontentloaded — он срабатывает раньше networkidle.
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    html = await page.content()
                else:
                    raise
        finally:
            await context.close()
            self._last_request[domain] = time.time()

        waf_blocked = _is_waf_blocked(response.status if response else 200, html)
        return html, network_log, robots_warning, waf_blocked

    async def _enforce_rate_limit(self, domain: str) -> None:
        """Задержка если с момента последнего запроса к домену прошло менее 2 секунд."""
        elapsed = time.time() - self._last_request.get(domain, 0.0)
        if elapsed < _RATE_LIMIT_SECONDS:
            await asyncio.sleep(_RATE_LIMIT_SECONDS - elapsed)


async def _robots_allowed(url: str) -> bool:
    """
    Проверяет robots.txt через stdlib RobotFileParser.

    Использует честный bot UA (_ROBOTS_UA) — прозрачная идентификация.
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
    return rp.can_fetch(_ROBOTS_UA, url)


def _is_waf_blocked(status: int, html: str) -> bool:
    """
    Возвращает True если получена challenge-страница WAF вместо реального сайта.
    Детектирует DDoS-Guard, Cloudflare и аналоги по HTTP-статусу и сигнатурам в HTML.
    """
    if status not in (403, 503):
        return False
    html_lower = html.lower()
    return any(sig in html_lower for sig in _WAF_SIGNATURES)


def _extract_domain(url: str) -> str:
    """Hostname из URL без порта. Пустая строка если URL невалиден."""
    return urlparse(url).hostname or ""
