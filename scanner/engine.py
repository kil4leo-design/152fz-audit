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
from typing import TYPE_CHECKING, Any, Literal

import yaml
from pydantic import BaseModel, ValidationError

from scanner.detectors.base import BaseDetector

# BeautifulSoup используется только в аннотациях — не нужен в runtime.
# from __future__ import annotations превращает аннотации в строки.
if TYPE_CHECKING:
    from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Путь к блокам Law Base относительно корня проекта
_LAW_BASE_DIR = Path(__file__).parent.parent / "law_base" / "blocks"


# ── Pydantic-схема валидации YAML ─────────────────────────────────────────────
# Валидирует обязательные поля из architecture.md:
# id, version, name, enabled, severity, legal_ref, fine, detector.method, fix

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


class _Fix(BaseModel):
    """Валидирует структуру блока fix. Оба поля обязательны — дефолтов нет."""
    summary: str
    steps: list[str]


class _DetectorConfig(BaseModel):
    method: str
    params: dict[str, Any] = {}


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
    fix: _Fix


# ── Реестр детекторов ─────────────────────────────────────────────────────────
# Ключ   — значение поля detector.method из YAML
# Значение — класс детектора (подкласс BaseDetector)
#
# Реестр методов зафиксирован в architecture.md → таблица "Реестр методов".
#
# АКТИВАЦИЯ НОВОГО ДЕТЕКТОРА — два шага обязательно вместе:
#   1. Раскомментировать import ниже
#   2. Раскомментировать строку в DETECTOR_REGISTRY
# Если сделать только один шаг:
#   - реестр без импорта  → NameError при старте (имя класса не определено)
#   - импорт без реестра  → нет ошибки, но детектор молча не запускается

from scanner.detectors.html_link_search import HtmlLinkSearchDetector
from scanner.detectors.html_checkbox_prechecked import HtmlCheckboxPrecheckedDetector
from scanner.detectors.html_form_no_consent import HtmlFormNoConsentDetector
# from scanner.detectors.html_form_no_policy_link import HtmlFormNoPolicyLinkDetector
# from scanner.detectors.html_cookie_banner_missing import HtmlCookieBannerMissingDetector
# from scanner.detectors.html_foreign_analytics import HtmlForeignAnalyticsDetector

DETECTOR_REGISTRY: dict[str, type[BaseDetector]] = {
    "html_link_search":           HtmlLinkSearchDetector,
    "html_checkbox_prechecked":   HtmlCheckboxPrecheckedDetector,
    "html_form_no_consent":       HtmlFormNoConsentDetector,
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
        # Список словарей нарушений (validated.model_dump()):
        # enabled=true И метод зарегистрирован в DETECTOR_REGISTRY
        self._violations: list[dict] = self._load_and_validate()

    # ── Загрузка и валидация Law Base ─────────────────────────────────────────

    def _load_and_validate(self) -> list[dict]:
        """
        Читает все *.yaml из law_base/blocks/.
        Валидирует каждое нарушение через Pydantic.

        Raises:
            RuntimeError: если директория пуста, YAML не читается
                          или нарушение не проходит Pydantic-валидацию

        Returns:
            Список словарей нарушений validated.model_dump() (enabled + метод в реестре).
        """
        yaml_files = sorted(_LAW_BASE_DIR.glob("*.yaml"))
        if not yaml_files:
            raise RuntimeError(f"Нет YAML-файлов в {_LAW_BASE_DIR}")

        violations: list[dict] = []

        for path in yaml_files:
            raw_file = self._read_yaml(path)
            for raw_violation in (raw_file.get("violations") or []):
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

                violations.append(validated.model_dump())

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

        :param violation_config: словарь нарушения из validated.model_dump()
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

        После прогона применяется _apply_b_mutex() — фильтр взаимоисключения
        B1/B2 на уровне формы (зафиксировано в architecture.md).

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

        return self._apply_b_mutex(results)

    @staticmethod
    def _apply_b_mutex(results: list[dict]) -> list[dict]:
        """
        B2 (нет чекбокса) и B1 (предустановлен) взаимоисключающие для одной формы.
        Если оба сработали на одном form_index — оставить B2, убрать B1.
        Предусловие: B-детекторы включают form_index: int в evidence.
        """
        b2_forms: set[int] = {
            r["evidence"]["form_index"]
            for r in results
            if r["id"] == "B2"
            and isinstance(r.get("evidence", {}).get("form_index"), int)
        }
        if not b2_forms:
            return results
        return [
            r for r in results
            if not (
                r["id"] == "B1"
                and r.get("evidence", {}).get("form_index") in b2_forms
            )
        ]
