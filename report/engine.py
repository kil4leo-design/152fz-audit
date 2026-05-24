"""
report/engine.py — Формирование отчёта из списка нарушений.

Принимает violations (результат Scanner.scan), URL и возвращает
JSON-сериализуемый словарь готового отчёта.

Обязательный disclaimer зафиксирован в architecture.md.
"""
from __future__ import annotations

from datetime import datetime, timezone

DISCLAIMER = (
    "ВАЖНО: Инструмент проверяет публичный HTML и сетевые запросы страницы. "
    "Результаты не являются юридическим заключением. "
    "Инструмент не проверяет: серверную логику, базы данных, внутренние документы, "
    "фактическое соблюдение требований к хранению данных. "
    "Для полного аудита обратитесь к юристу, специализирующемуся на 152-ФЗ. "
    "Для сверки результатов с реальным видом сайта открывайте его в режиме инкогнито: "
    "сканер всегда работает без cookie, как при первом визите."
)


def build(
    violations: list[dict],
    url: str,
    robots_warning: bool = False,
    waf_blocked: bool = False,
    blocked_excerpt: str = "",
    passed: list[dict] | None = None,
) -> dict:
    """
    Собрать отчёт из списка нарушений.

    :param violations: список нарушений из Scanner.scan() / DetectorEngine.run_all()
    :param url: сканируемый URL
    :param robots_warning: True если robots.txt ограничивает доступ (Вариант B)
    :param waf_blocked: True если WAF вернул challenge-страницу — violations не показываются
    :param blocked_excerpt: первые 1500 символов текста challenge-страницы (если waf_blocked)
    :return: JSON-сериализуемый словарь отчёта
    """
    passed = passed or []

    if waf_blocked:
        return {
            "url": url,
            "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
            "robots_warning": robots_warning,
            "waf_blocked": True,
            "blocked_excerpt": blocked_excerpt,
            "summary": {"status": "waf_blocked", "violations_count": 0, "recommendations_count": 0, "passed_count": 0},
            "violations": [],
            "recommendations": [],
            "passed": [],
            "disclaimer": DISCLAIMER,
        }

    found = [v for v in violations if not v.get("is_recommendation", False)]
    recommendations = [v for v in violations if v.get("is_recommendation", False)]

    if found:
        status = "violations_found"
    elif recommendations:
        status = "recommendations_only"
    else:
        status = "compliant"

    return {
        "url": url,
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "robots_warning": robots_warning,
        "waf_blocked": False,
        "blocked_excerpt": "",
        "summary": {
            "status": status,
            "violations_count": len(found),
            "recommendations_count": len(recommendations),
            "passed_count": len(passed),
        },
        "violations": found,
        "recommendations": recommendations,
        "passed": passed,
        "disclaimer": DISCLAIMER,
    }
