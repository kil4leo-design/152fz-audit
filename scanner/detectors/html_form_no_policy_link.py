"""
scanner/detectors/html_form_no_policy_link.py — Детектор B3.

Нарушение: ст. 9 ч.2 152-ФЗ → ч.2 ст.13.11 КоАП.
Штраф для юрлица: 300 000 – 700 000 руб.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.detectors.base import BaseDetector

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


class HtmlFormNoPolicyLinkDetector(BaseDetector):
    """
    Детектор B3: форма с ПДн не содержит ссылки на политику обработки ПДн.

    Алгоритм (три уровня поиска):
    1. Внутри <form> — <a> с policy_keyword в тексте или href.
    2. В родительских контейнерах до max_depth уровней (form_and_parent).
    3. В тексте кнопки submit (check_submit_text).
    Нарушение → evidence с form_index (обязательно для _apply_b_mutex).
    """

    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        pd_fields = [f.lower() for f in self.params.get("pd_fields", [])]
        pd_input_types = [t.lower() for t in self.params.get("pd_input_types", [])]
        policy_keywords = [kw.lower() for kw in self.params.get("policy_keywords", [])]
        max_depth = self.params.get("max_depth", 2)
        check_submit_text = self.params.get("check_submit_text", False)
        submit_keywords = [kw.lower() for kw in self.params.get("submit_keywords", [])]

        violations = []
        for form_index, form in enumerate(soup.find_all("form")):
            if not _form_has_pd_fields(form, pd_fields, pd_input_types):
                continue
            if _find_policy_link(form, policy_keywords, max_depth, check_submit_text, submit_keywords):
                continue
            violations.append(self._build_result({
                "form_index": form_index,
                "found": False,
                "detail": "Ссылка на политику обработки ПДн не найдена рядом с формой",
            }))
        return violations


def _form_has_pd_fields(
    form: Tag, pd_fields: list[str], pd_input_types: list[str]
) -> bool:
    """Возвращает True если форма содержит поля, собирающие персональные данные."""
    _skip_types = {"hidden", "submit", "button", "reset", "image"}
    for inp in form.find_all("input"):
        input_type = (inp.get("type") or "text").lower()
        if input_type in _skip_types:
            continue
        if input_type in pd_input_types:
            return True
        name = (inp.get("name") or "").lower()
        placeholder = (inp.get("placeholder") or "").lower()
        if any(f in name or f in placeholder for f in pd_fields):
            return True
    return False


def _find_policy_link(
    form: Tag,
    policy_keywords: list[str],
    max_depth: int,
    check_submit_text: bool,
    submit_keywords: list[str],
) -> bool:
    """
    Ищет ссылку на политику в трёх зонах.
    Возвращает True если ссылка найдена.
    """
    # Уровень 1: внутри <form>
    if _container_has_policy_link(form, policy_keywords):
        return True

    # Уровень 2: родительские контейнеры до max_depth
    container = form.parent
    for _ in range(max_depth):
        if container is None or getattr(container, "name", None) in (None, "[document]"):
            break
        if _container_has_policy_link(container, policy_keywords):
            return True
        container = container.parent

    # Уровень 3: текст кнопки submit
    if check_submit_text:
        for submit in form.find_all(["input", "button"], type="submit"):
            btn_text = (
                submit.get("value") or submit.get_text(separator=" ", strip=True) or ""
            ).lower()
            if any(kw in btn_text for kw in submit_keywords):
                return True

    return False


def _container_has_policy_link(container: Tag, policy_keywords: list[str]) -> bool:
    """Возвращает True если контейнер содержит <a> с policy_keyword в тексте или href."""
    for a in container.find_all("a", href=True):
        href = (a.get("href") or "").lower()
        text = a.get_text(strip=True).lower()
        if any(kw in href or kw in text for kw in policy_keywords):
            return True
    return False
