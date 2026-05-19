"""
scanner/engine.py — Detector Engine.

Ответственности:
1. Загрузка YAML из law_base/blocks/*.yaml при инициализации
2. Pydantic-валидация каждого нарушения (обязательные поля, типы)
3. Фабричный паттерн: dispatch по detector.method → класс детектора
4. run_all(): прогон всех enabled зарегистрированных детекторов

Поведение при ошибках (зафиксировано в architecture.md):
- Невалидный YAML → RuntimeError → приложение не стартует
- Метод не в реестре → warning + skip (детектор ещё не реализован)
- Детектор упал в runtime → exception логируется, остальные продолжают

Использование:
    engine = DetectorEngine()            # загрузка и валидация при инициализации
    results = engine.run_all(soup, network_log)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from bs4 import BeautifulSoup
from pydantic import BaseModel, ValidationError

from scanner.detectors.base import BaseDetector

logger = logging.getLogger(__name__)

# Путь к блокам Law Base относительно корня проекта
_LAW_BASE_DIR = Path(__file__).parent.parent / "law_base" / "blocks"


# ── Pydantic-схема валидации YAML ─────────────────────────────────────────────
# Валидирует обязательные поля из architecture.md:
# id, version, name, enabled, severity, legal_ref, fine, detector.method

class _LegalRef(BaseModel):
    law: str
    article: str
    description: str | None = None


class _FineAmounts(BaseModel):
    individual: str | None = None
    official: str | None = None
    entrepreneur: str | None = None
    legal_entity: str | None = None


class _Fine(BaseModel):
    law: str | None = None
    article: str
    amounts: _FineAmounts


class _DetectorConfig(BaseModel):
    method: str
    params: dict = {}


class _ViolationConfig(BaseModel):
    id: str
    version: str
    name: str
    block: str
    enabled: bool
    severity: Literal["critical", "warning", "info"]
    is_recommendation: bool = False
    legal_ref: _LegalRef
    fine: _Fine
    detector: _DetectorConfig
    fix: dict = {}


# ── Реестр детекторов ─────────────────────────────────────────────────────────
# Ключ   — значение поля detector.method из YAML
# Значение — класс детектора (подкласс BaseDetector)
#
# Импорты раскомментируются по мере реализации детекторов в Этапе 1.
# Реестр методов зафиксирован в architecture.md → таблица "Реестр методов".

# from scanner.detectors.html_link_search import HtmlLinkSearchDetector
# from scanner.detectors.html_checkbox_prechecked import HtmlCheckboxPrecheckedDetector
# from scanner.detectors.html_form_no_consent import HtmlFormNoConsentDetector
# from scanner.detectors.html_form_no_policy_link import HtmlFormNoPolicyLinkDetector
# from scanner.detectors.html_cookie_banner_missing import HtmlCookieBannerMissingDetector
# from scanner.detectors.html_foreign_analytics import HtmlForeignAnalyticsDetector

DETECTOR_REGISTRY: dict[str, type[BaseDetector]] = {
    # "html_link_search":           HtmlLinkSearchDetector,
    # "html_checkbox_prechecked":   HtmlCheckboxPrecheckedDetector,
    # "html_form_no_consent":       HtmlFormNoConsentDetector,
    # "html_form_no_policy_link":   HtmlFormNoPolicyLinkDetector,
    # "html_cookie_banner_missing": HtmlCookieBannerMissingDetector,
    # "html_foreign_analytics":     HtmlForeignAnalyticsDetector,
}


# ── Detector Engine ───────────────────────────────────────────────────────────

class DetectorEngine:
    """
    Загружает Law Base, валидирует, создаёт детекторы (фабричный паттерн),
    прогоняет все enabled зарегистрированные детекторы по HTML + network_log.
    """

    def __init__(self) -> None:
        # Список «сырых» словарей нарушений готовых к обработке:
        # enabled=true И метод зарегистрирован в DETECTOR_REGISTRY
        self._violations: list[dict] = self._load_and_validate()

    # ── Загрузка и валидация Law Base ─────────────────────────────────────────

    def _load_and_validate(self) -> list[dict]:
        """
        Читает все *.yaml из law_base/blocks/.
        Валидирует каждое нарушение через Pydantic.

        Raises:
            FileNotFoundError: если директория пуста
            RuntimeError: если YAML не читается или не проходит валидацию

        Returns:
            Список сырых словарей нарушений (enabled + метод в реестре).
        """
        yaml_files = sorted(_LAW_BASE_DIR.glob("*.yaml"))
        if not yaml_files:
            raise FileNotFoundError(f"Нет YAML-файлов в {_LAW_BASE_DIR}")

        violations: list[dict] = []

        for path in yaml_files:
            raw_file = self._read_yaml(path)
            for raw_violation in raw_file.get("violations", []):
                # Валидация: обязательные поля, типы — fatal при ошибке
                validated = self._validate_violation(raw_violation, path)

                if not validated.enabled:
                    logger.debug("Пропущен (disabled): %s", validated.id)
                    continue

                method = validated.detector.method
                if method not in DETECTOR_REGISTRY:
                    # Детектор ещё не реализован — пропуск, не crash
                    logger.warning(
                        "Детектор не зарегистрирован, пропуск: %s (method=%s)",
                        validated.id,
                        method,
                    )
                    continue

                violations.append(raw_violation)

        logger.info(
            "Law Base загружена: %d активных нарушений из %d файлов",
            len(violations),
            len(yaml_files),
        )
        return violations

    @staticmethod
    def _read_yaml(path: Path) -> dict:
        """Читает YAML-файл. Raises RuntimeError при любой ошибке чтения/парсинга."""
        try:
            with path.open(encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            raise RuntimeError(f"Ошибка чтения {path}: {exc}") from exc

    @staticmethod
    def _validate_violation(raw: dict, source_path: Path) -> _ViolationConfig:
        """
        Валидирует словарь нарушения через Pydantic.
        Raises RuntimeError с подробным описанием при ошибке валидации.
        """
        try:
            return _ViolationConfig.model_validate(raw)
        except ValidationError as exc:
            raise RuntimeError(
                f"Ошибка валидации в {source_path.name}, "
                f"id={raw.get('id', '?')}: {exc}"
            ) from exc

    # ── Фабричный паттерн ─────────────────────────────────────────────────────

    def _create_detector(self, violation_config: dict) -> BaseDetector:
        """
        Создать экземпляр детектора по полю detector.method.

        Метод гарантированно присутствует в реестре —
        проверка выполнена при загрузке в _load_and_validate().

        :param violation_config: сырой словарь нарушения из YAML
        :return: экземпляр конкретного детектора
        """
        method = violation_config["detector"]["method"]
        detector_class = DETECTOR_REGISTRY[method]
        return detector_class(violation_config)

    # ── Прогон детекторов ─────────────────────────────────────────────────────

    def run_all(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        """
        Прогнать все enabled зарегистрированные детекторы.

        Один упавший детектор не останавливает остальные —
        исключение логируется, прогон продолжается.

        TODO (Этап 1, блок B): реализовать передачу контекста форм
        между детекторами B1/B2 (зависимость зафиксирована в architecture.md:
        "B1 запускается только если форма с ПДн найдена",
        "B1 и B2 взаимоисключающие для одной формы").

        :param soup: BeautifulSoup-дерево HTML страницы
        :param network_log: список сетевых запросов от PlaywrightWrapper
        :return: список нарушений (может быть пустым)
        """
        results: list[dict] = []

        for violation_config in self._violations:
            vid = violation_config.get("id", "?")
            try:
                detector = self._create_detector(violation_config)
                found = detector.detect(soup, network_log)
                if found:
                    results.extend(found)
            except Exception:
                logger.exception("Детектор %s упал, продолжаем", vid)

        return results
