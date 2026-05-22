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
| `html_foreign_analytics` | `HtmlForeignAnalyticsDetector` | `scanner/detectors/html_foreign_analytics.py` |

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

```python
async def scan(url: str) -> tuple[str, list[dict]]:
    # 1. Проверить robots.txt
    if not robots_allowed(url):
        raise RobotsDisallowedError(url)

    # 2. Настроить перехват сети
    network_log = []
    page.on("request", lambda req: network_log.append({
        "url": req.url,
        "domain": extract_domain(req.url),
        "timestamp": time.time()
    }))

    # 3. Загрузить страницу
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await page.wait_for_timeout(2000)  # динамический контент

    # 4. Вернуть HTML + network_log
    html = await page.content()
    return html, network_log
```

**Обязательные заголовки:**
```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; 152fz-audit/1.0; +https://github.com/kil4leo-design/152fz-audit)"
}
```

**Rate limiting:** минимум 2 секунды между запросами к одному домену.

---

## Поток данных — полный цикл

```
1.  Пользователь вводит URL в UI
2.  UI → POST /scan → FastAPI
3.  FastAPI → Scanner.scan(url)
4.  Scanner → robots.txt check (если запрещён → вернуть ошибку)
5.  Scanner → PlaywrightWrapper.scan(url) → (html, network_log)
6.  Scanner → BeautifulSoup(html) → soup
7.  Scanner → DetectorEngine.run_all(soup, network_log, config)
8.  DetectorEngine читает law_base/blocks/*.yaml
9.  DetectorEngine → для каждого enabled детектора:
    a. detector.detect(soup, network_log) → результат
    b. Если детектор упал → логируем, продолжаем следующий
10. Движок применяет зависимости (B1/B2 логика)
11. Scanner возвращает список нарушений + evidence в FastAPI
12. FastAPI → ReportEngine.build(violations) → отчёт JSON + HTML
13. Отчёт содержит обязательный disclaimer (см. ниже)
14. [post-MVP] FastAPI сохраняет результат в DB (история)
15. FastAPI возвращает отчёт в UI
16. UI отображает нарушения / рекомендации
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
