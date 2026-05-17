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
    ├── [Playwright Wrapper] — загружает страницу, возвращает HTML
    │        │
    │        ▼ HTML
    │   [BeautifulSoup] — парсит HTML в дерево
    │        │
    │        ▼ soup
    └── [Detector Engine] — прогоняет детекторы
             │
             ├── [Detector A1] ──┐
             ├── [Detector B1] ──┤
             ├── [Detector B2] ──┼── читает [Law Base / YAML]
             ├── [Detector B3] ──┤
             ├── [Detector C1] ──┤
             └── [Detector C2] ──┘
                      │
                      ▼ список нарушений
             [Report Engine]
                      │
                      ▼ отчёт (JSON / HTML)
             [API — FastAPI]
                      │
                      ▼
             [UI — React]
                      │
                      ▼
             [DB — SQLite] — сохранение истории

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

**Playwright + BeautifulSoup — разделение ответственности.**
- Playwright: загрузка страницы с полным JS-рендерингом, получение итогового HTML
- BeautifulSoup: парсинг HTML в дерево для детекторов
- Детекторы работают с объектом `soup` (BeautifulSoup), не с Playwright напрямую

**Law Base — единственный источник правил.**
Детекторы читают параметры из YAML (keywords, selectors, pd_fields и т.д.).
Изменение правила = изменение YAML, не кода детектора.

**Один детектор — одна ответственность.**
Каждый детектор проверяет ровно одно нарушение. Результат: список нарушений или пустой список.

---

## Поток данных — полный цикл

```
1. Пользователь вводит URL в UI
2. UI → POST /scan → FastAPI
3. FastAPI → Scanner.scan(url)
4. Scanner → PlaywrightWrapper.get_html(url) → HTML строка
5. Scanner → BeautifulSoup(html) → soup объект
6. Scanner → DetectorEngine.run_all(soup, config)
7. DetectorEngine читает law_base/blocks/*.yaml
8. DetectorEngine → для каждого enabled детектора → detector.detect(soup)
9. Детектор возвращает [] или [{"id", "name", "severity", "fine", "fix", ...}]
10. DetectorEngine собирает все результаты
11. Scanner возвращает список нарушений в FastAPI
12. FastAPI → ReportEngine.build(violations) → отчёт JSON + HTML
13. [post-MVP] FastAPI сохраняет результат в DB (история — модуль History)
14. FastAPI возвращает отчёт в UI
15. UI отображает нарушения / рекомендации
```

---

## Law Monitor — поток данных

```
1. GitHub Actions запускает scheduler.py раз в месяц
2. fetcher.py → GET publication.pravo.gov.ru/api/ (фильтр: 152-ФЗ, КоАП 13.11)
3. Если новых документов нет → лог "no changes", завершение
4. Если есть → parser.py извлекает текст закона
5. analyzer.py → передаёт текст в Anthropic API
6. AI возвращает: что изменилось + предложения правок в YAML
7. notifier.py → отправляет email/уведомление оператору
8. Оператор проверяет и подтверждает правки вручную
9. После подтверждения — обновление law_base/blocks/*.yaml → коммит → деплой
```

---

## Структура результата детектора

Каждый детектор возвращает список объектов:

```python
[
    {
        "id": "A1",
        "name": "Отсутствует политика обработки персональных данных",
        "severity": "critical",
        "is_recommendation": False,
        "legal_ref": {"law": "152-ФЗ", "article": "ст. 18.1 ч.2"},
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
        "evidence": "..."  # что именно найдено / не найдено на странице
    }
]
```
