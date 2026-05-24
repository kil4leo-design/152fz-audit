"""
scanner/detectors/base.py — Базовый класс детектора нарушений 152-ФЗ.

Контракт:
- detect() никогда не бросает исключение наружу — обработка в DetectorEngine
- detect() возвращает [] (нарушений нет) или список нарушений
- Каждый детектор проверяет ровно одно нарушение
- Все параметры берутся из self.params (YAML), никакого хардкода

Сигнатура метода зафиксирована в architecture.md:
    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup


class BaseDetector(ABC):
    """
    Абстрактный базовый класс для всех детекторов нарушений.

    Подклассы реализуют detect() и при необходимости вызывают _build_result()
    для формирования стандартного словаря нарушения.
    """

    def __init__(self, violation_config: dict) -> None:
        """
        :param violation_config: словарь одного нарушения из YAML
                                 (id, version, name, severity, detector.params, ...)
        """
        self.config = violation_config
        self.params: dict = violation_config.get("detector", {}).get("params", {})

    @abstractmethod
    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        """
        Выполнить проверку нарушения.

        :param soup: BeautifulSoup-дерево HTML страницы (после networkidle + 2s timeout)
        :param network_log: список сетевых запросов от PlaywrightWrapper
                            формат каждого элемента:
                            {"url": str, "domain": str, "timestamp": float}
        :return: [] если нарушений нет, иначе список словарей нарушений
                 (каждый — результат _build_result())
        """

    def _build_result(self, evidence: dict) -> dict:
        """
        Собрать стандартный словарь нарушения из конфига + доказательная база.

        Предусловие: violation_config прошёл Pydantic-валидацию в DetectorEngine.
        Обязательные поля (прямой доступ): id, version, name, severity,
                                            legal_ref, fine, fix.
        С default в Pydantic (через .get()): is_recommendation.

        Формат evidence зависит от детектора:
        - A1:   {"detail": str, "checked_urls": list}
        - B1:   {"form_index": int, "detail": str, "checkbox_text": str}
        - B2:   {"form_index": int, "detail": str} или
                {"form_index": int, "detail": str, "alternative_consent_text": str}
        - B3:   {"form_index": int, "detail": str}
        - C1:   {"detail": str, "network_requests": list}

        :param evidence: доказательная база (что найдено / не найдено и где)
        :return: словарь нарушения в стандартном формате отчёта
        """
        cfg = self.config
        return {
            "id": cfg["id"],
            "version": cfg["version"],
            "name": cfg["name"],
            "severity": cfg["severity"],
            "is_recommendation": cfg.get("is_recommendation", False),
            "legal_ref": cfg["legal_ref"],
            "fine": cfg["fine"],
            "fix": cfg["fix"],
            "evidence": evidence,
        }
