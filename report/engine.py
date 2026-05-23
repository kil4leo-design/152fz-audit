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
    "Для полного аудита обратитесь к юристу, специализирующемуся на 152-ФЗ."
)


def build(
    violations: list[dict],
    url: str,
    robots_warning: bool = False,
    waf_blocked: bool = False,
) -> dict:
    """
    Собрать отчёт из списка нарушений.

    :param violations: список нарушений из Scanner.scan() / DetectorEngine.run_all()
    :param url: сканируемый URL
    :param robots_warning: True если robots.txt ограничивает доступ (Вариант B)
    :param waf_blocked: True если WAF вернул challenge-страницу — результаты ненадёжны
    :return: JSON-сериализуемый словарь отчёта
    """
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
        "waf_blocked": waf_blocked,
        "summary": {
            "status": status,
            "violations_count": len(found),
            "recommendations_count": len(recommendations),
        },
        "violations": found,
        "recommendations": recommendations,
        "disclaimer": DISCLAIMER,
    }
