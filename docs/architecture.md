# architecture.md — Архитектура системы

> Этот файл читается при разработке любого модуля.
> Описывает взаимодействие модулей, потоки данных, ключевые решения.

---

## Модули и взаимодействие

```
Пользователь
    │
    ▼
[UI — React]
    │  URL
    ▼
[API — FastAPI]
    │  URL
    ▼
[Scanner]
    ├── robots.txt check — перед любым сканированием
    ├── [Playwright Wrapper] — загружает страницу + перехватывает сеть
    │        │
    │        ├── HTML (после networkidle + 2s timeout)
    │        └── network_log (все исходящие запросы)
    │             │
    │        [BeautifulSoup] — парсит HTML в дерево (soup)
    │             │
    └── [Detector Engine] — прогоняет детекторы
             │
             ├── [Detector A1] ──── soup + network_log → использует soup
             ├── [Detector B1] ──── soup + network_log → использует soup
             ├── [Detector B2] ──── soup + network_log → использует soup
             ├── [Detector B3] ──── soup + network_log → использует soup
             ├── [Detector C1] ──── soup + network_log → использует ОБА
             └── [Detector C2] ──── soup + network_log → использует ОБА
                      │
                      ▼ список нарушений + evidence
             [Report Engine]
                      │
                      ▼ отчёт (JSON / HTML) + disclaimer
             [API — FastAPI]
                      │
                      ▼
             [UI — React]

[post-MVP] [DB — SQLite] — история проверок (модуль History)

[Law Monitor] — независимый процесс (GitHub Actions, раз в месяц)
    ├── fetcher.py — опрашивает publication.pravo.gov.ru API/RSS
    ├── parser.py — извлекает текст закона
    ├── analyzer.py — передаёт текст AI, получает предложения правок YAML
    └── notifier.py — уведомляет оператора для подтверждения
```

---

## Принципы

**Scanner не знает про UI и API.**
Scanner принимает URL, возвращает список нарушений. Всё остальное — не его ответственность.

**Detector Engine — фабричный паттерн.**
Dispatch по полю `detector.method` из YAML, не по `id`. Реестр методов:

| method | class | файл |
|--------|-------|------|
| `html_link_search` | `HtmlLinkSearchDetector` | `scanner/detectors/html_link_search.py` |
| `html_checkbox_prechecked` | `HtmlCheckboxPrecheckedDetector` | `scanner/detectors/html_checkbox_prechecked.py` |
| `html_form_no_consent` | `HtmlFormNoConsentDetector` | `scanner/detectors/html_form_no_consent.py` |
| `html_form_no_policy_link` | `HtmlFormNoPolicyLinkDetector` | `scanner/detectors/html_form_no_policy_link.py` |
| `html_cookie_banner_missing` | `HtmlCookieBannerMissingDetector` | `scanner/detectors/html_cookie_banner_missing.py` |
| `html_foreign_analytics` | `HtmlForeignAnalyticsDetector` | не реализован — C2 отключён (`enabled: false`) |

**Playwright — единственный режим работы.**
PlaywrightWrapper ВСЕГДА:
1. Проверяет robots.txt перед загрузкой страницы
2. Ждёт `networkidle` + 2 секунды timeout для динамического контента
3. Перехватывает ВСЕ исходящие сетевые запросы (network_log)
4. Возвращает (html, network_log) — оба значения всегда

A/B детекторы игнорируют network_log. C детекторы используют оба.
Это проще чем два режима и не создаёт значимых накладных расходов.

**C1 — важно: network interception без взаимодействия пользователя.**
PlaywrightWrapper загружает страницу и немедленно собирает network_log.
Никаких кликов, никакого взаимодействия с баннером.
Это эмулирует первый визит пользователя: если аналитика загружается сразу —
это нарушение (данные собираются до согласия).
Детектор C1 проверяет: есть ли запросы к аналитическим доменам в network_log
ДО любого взаимодействия пользователя.

**Сигнатура метода детектора:**
```python
def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
```
Возвращает [] или список нарушений. Никогда не бросает исключение наружу.

**Law Base — единственный источник правил.**
Детекторы читают параметры из YAML (keywords, selectors, pd_fields и т.д.).
Изменение правила = изменение YAML, не кода детектора.

**Один детектор — одна ответственность.**
Каждый детектор проверяет ровно одно нарушение. Результат: [] или список нарушений.

**Общие параметры (pd_fields) — управление дублированием.**
pd_fields идентичен в B1, B2, B3. Дублирование в YAML — сознательное решение для простоты.
Риск: при обновлении одного файла другие могут остаться устаревшими.
Правило: при изменении pd_fields — обновлять все три файла (B1, B2, B3) в одном коммите.
Долгосрочно: вынести в `law_base/shared_params.yaml` и загружать в DetectorEngine.

**Зависимости между детекторами.**
B1 (предустановленный чекбокс) запускается только если форма с ПДн найдена.
B2 (нет чекбокса) и B1 (предустановлен) взаимоисключающие для одной формы:
- Если форма без чекбокса → B2 срабатывает, B1 для этой формы не проверяется
- Если чекбокс есть и предустановлен → B1 срабатывает

**Реализация — `DetectorEngine._apply_b_mutex()`:**
Все B-детекторы прогоняются независимо. После прогона `run_all()` вызывает
`_apply_b_mutex()`: если B2 и B1 оба сработали на одном `form_index` —
B2 приоритетнее, B1 для той же формы убирается из результатов.

**Обязательное требование к B-детекторам:** включать `form_index: int`
(0-based индекс формы в `soup.find_all("form")`) в `evidence`.
Без `form_index` взаимоисключение не сработает.

---

## PlaywrightWrapper — обязательное поведение

### Стратегия robots.txt — Вариант B (зафиксировано сессия 9)

Инструмент проверяет ПУБЛИЧНОЕ соответствие закону. Целевой пользователь — владелец сайта,
проверяющий свой ресурс. robots.txt — конвенция для веб-краулеров, не запрет на compliance-аудит.

**Решение:** не блокировать при запрещающем robots.txt, а сканировать с предупреждением.
`PlaywrightWrapper.scan()` возвращает `robots_warning=True` если robots.txt ограничивает доступ.
API не возвращает 403 — возвращает полный отчёт с дополнительным полем `robots_warning`.
UI отображает информационный баннер: «robots.txt ограничивает автоматический доступ —
убедитесь, что вы имеете право на проверку этого сайта».

**Почему не игнорировать robots.txt полностью:**
Прозрачность важна — пользователь должен знать, что проверка выполнена вне ограничений.
Ответственность остаётся на пользователе (он авторизован проверять свой сайт).

```python
async def scan(url: str) -> tuple[str, list[dict], bool, bool]:
    # 1. Проверить robots.txt — NOT raises, returns warning flag
    robots_warning = not (await _robots_allowed(url))

    # 2. Настроить перехват сети + stealth fingerprint
    network_log = []
    context = await browser.new_context(user_agent=_PAGE_UA)
    await context.add_init_script(_STEALTH_SCRIPT)  # патч navigator.webdriver и др.
    page = await context.new_page()
    page.on("request", lambda req: network_log.append({
        "url": req.url, "domain": ..., "timestamp": time.time()
    }))

    # 3. Загрузить страницу (всегда, независимо от robots.txt)
    response = await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)  # динамический контент

    # 4. Определить waf_blocked (403/503 + WAF-сигнатура в HTML)
    html = await page.content()
    waf_blocked = _is_waf_blocked(response.status, html)

    # 5. Вернуть HTML + network_log + robots_warning + waf_blocked
    return html, network_log, robots_warning, waf_blocked
```

**Два User-Agent:**
- `_ROBOTS_UA` — честный bot UA для robots.txt (прозрачная идентификация)
- `_PAGE_UA` — реальный Chrome 124 UA для загрузки страницы (WAF пропускает)

**Stealth script** патчит: `navigator.webdriver`, `navigator.plugins`, `window.chrome`, `navigator.languages`.
Запускается через `context.add_init_script()` до первого запроса.
Chromium запускается с `--disable-blink-features=AutomationControlled`.

**WAF detection (`_is_waf_blocked`):** status in (403, 503) AND html содержит одну из сигнатур:
`ddos-guard`, `cloudflare`, `just a moment`, `checking your browser`, `access denied`, `enable javascript and cookies`.

**Rate limiting:** минимум 2 секунды между запросами к одному домену.

---

## Поток данных — полный цикл

```
1.  Пользователь вводит URL в UI
2.  UI → POST /scan → FastAPI
3.  FastAPI → Scanner.scan(url)
4.  Scanner → PlaywrightWrapper.scan(url) → (html, network_log, robots_warning, waf_blocked)
    robots_warning=True если robots.txt ограничивает доступ — НЕ прерывает скан
    waf_blocked=True если WAF вернул challenge-страницу вместо реального сайта
5.  Если waf_blocked=True → violations=[], blocked_excerpt=текст challenge-страницы[:1500]
    Если waf_blocked=False → BeautifulSoup(html) → soup → DetectorEngine.run_all(soup, network_log)
6.  DetectorEngine читает law_base/blocks/*.yaml (загружены при инициализации)
7.  DetectorEngine → для каждого enabled детектора:
    a. detector.detect(soup, network_log) → результат
    b. Если детектор упал → логируем, продолжаем следующий
8.  Движок применяет зависимости (B1/B2 логика)
9.  Scanner возвращает (violations, robots_warning, waf_blocked, blocked_excerpt) в FastAPI
10. FastAPI → ReportEngine.build(violations, url, robots_warning, waf_blocked, blocked_excerpt) → отчёт JSON
11. Если waf_blocked=True → отчёт: violations=[], status="waf_blocked", blocked_excerpt=...
    Если waf_blocked=False → отчёт с полным набором violations/recommendations
12. Отчёт содержит обязательный disclaimer
13. [post-MVP] FastAPI сохраняет результат в DB (история)
14. FastAPI возвращает отчёт в UI
15. UI: если waf_blocked=True → фиолетовый блок с объяснением + pre с blocked_excerpt, нарушения скрыты
    UI: если robots_warning=True && !waf_blocked → синий информационный баннер
    UI: иначе → нарушения / рекомендации / compliant
```

---

## Структура результата детектора

```python
[
    {
        "id": "A1",
        "version": "1.1.0",          # версия критерия из YAML
        "name": "Отсутствует политика обработки персональных данных",
        "severity": "critical",       # critical | warning | info
        "is_recommendation": False,
        "legal_ref": {
            "law": "152-ФЗ",
            "article": "ст. 18.1 ч.2"
        },
        "fine": {
            "article": "ч.3 ст.13.11",
            "amounts": {
                "individual": "1 500 – 3 000 руб.",
                "official": "6 000 – 12 000 руб.",
                "entrepreneur": "10 000 – 20 000 руб.",
                "legal_entity": "30 000 – 60 000 руб."
            }
        },
        "fix": {
            "summary": "...",
            "steps": ["...", "..."]
        },
        "evidence": {
            "detail": "Ссылка с ключевыми словами не найдена в footer, header, nav, body",
            "checked_urls": [],       # для A1: какие URL проверены
            "network_requests": []    # для C1: какие запросы перехвачены
            # для B1: "checkbox_text": str — текст найденного предустановленного чекбокса
            # для B2: "alternative_consent_text": str | None — текст альтернативного согласия
            # для B1/B2/B3: обязательно "form_index": int  ← нужен для _apply_b_mutex()
        }
    }
]
```

---

## Формат ответа POST /scan (report/engine.py)

```json
{
  "url": "https://example.com",
  "scanned_at": "2026-05-22T10:00:00+00:00",
  "robots_warning": false,
  "waf_blocked": false,
  "blocked_excerpt": "",
  "summary": {
    "status": "violations_found",
    "violations_count": 2,
    "recommendations_count": 1
  },
  "violations": [...],
  "recommendations": [...],
  "disclaimer": "ВАЖНО: ..."
}
```

`status`: `"compliant"` | `"recommendations_only"` | `"violations_found"` | `"waf_blocked"`

`robots_warning`: `false` | `true` — robots.txt ограничивает автоматический доступ.
Скан выполнен, отчёт полный. UI показывает синий информационный баннер (только если !waf_blocked).

`waf_blocked`: `false` | `true` — WAF вернул challenge-страницу вместо реального сайта.
При `true`: `violations=[]`, `recommendations=[]`, `status="waf_blocked"`.
UI скрывает violations и показывает фиолетовый блок с объяснением + `blocked_excerpt`.

`blocked_excerpt`: текст challenge-страницы (первые 1500 символов, без HTML-тегов).
Пусто если `waf_blocked=false`.

---

## Обязательный disclaimer в отчёте

Каждый отчёт должен содержать:

```
ВАЖНО: Инструмент проверяет публичный HTML и сетевые запросы страницы.
Результаты не являются юридическим заключением.
Инструмент не проверяет: серверную логику, базы данных, внутренние документы,
фактическое соблюдение требований к хранению данных.
Для полного аудита обратитесь к юристу, специализирующемуся на 152-ФЗ.
```

Это защищает бизнес юридически и формирует правильные ожидания клиента.

---

## Валидация YAML при загрузке

При старте приложения DetectorEngine валидирует все YAML-файлы:
- Обязательные поля: id, version, name, enabled, severity, legal_ref, fine, detector.method
- detector.method должен быть в реестре детекторов
- Если валидация не прошла — приложение не запускается, выводит ошибку

Реализовать через Pydantic-модель или JSON Schema (выбрать при реализации).

---

## Law Monitor — поток данных

```
1. GitHub Actions запускает scheduler.py раз в месяц
2. fetcher.py → GET publication.pravo.gov.ru/api/ (фильтр: 152-ФЗ, КоАП 13.11)
3. Если новых документов нет → лог "no changes", завершение
4. Если есть → parser.py извлекает текст закона
5. analyzer.py → передаёт текст в Anthropic API
6. AI возвращает: что изменилось + предложения правок в YAML
7. notifier.py → отправляет уведомление оператору
8. Оператор проверяет и подтверждает правки вручную
9. После подтверждения → обновление law_base/blocks/*.yaml → коммит → деплой
```
