"""
scanner/detectors/html_checkbox_prechecked.py — Детектор B1.

Нарушение: ст. 9 152-ФЗ → ч.2 ст.13.11 КоАП.
Штраф для юрлица: 300 000 – 700 000 руб.
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from scanner.detectors.base import BaseDetector

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


class HtmlCheckboxPrecheckedDetector(BaseDetector):
    """
    Детектор B1: форма с ПДн содержит предустановленный чекбокс согласия.

    Алгоритм:
    1. Перебрать все <form> (form_index = 0-based порядок в soup).
    2. Если форма не собирает ПДн (нет pd_fields / pd_input_types) — пропустить.
    3. Найти все <input type="checkbox" checked> в форме.
    4. Проверить что чекбокс относится к согласию на ПДн (consent_keywords).
    5. Исключить чекбоксы matching exclude_keywords.
    6. Нарушение → evidence с form_index (обязательно для _apply_b_mutex).
    """

    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        pd_fields = [f.lower() for f in self.params.get("pd_fields", [])]
        pd_input_types = [t.lower() for t in self.params.get("pd_input_types", [])]
        consent_keywords = [kw.lower() for kw in self.params.get("consent_keywords", [])]
        exclude_keywords = [kw.lower() for kw in self.params.get("exclude_keywords", [])]

        violations = []
        for form_index, form in enumerate(soup.find_all("form")):
            if not _form_has_pd_fields(form, pd_fields, pd_input_types):
                continue
            checkbox_text = _find_prechecked_consent_checkbox(
                form, consent_keywords, exclude_keywords
            )
            if checkbox_text is not None:
                violations.append(self._build_result({
                    "form_index": form_index,
                    "detail": "Чекбокс согласия на обработку ПДн предустановлен (checked)",
                    "checkbox_text": checkbox_text,
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
        for f in pd_fields:
            # name= атрибут: word-component match — "name" совпадает с "name", "first_name",
            # но не с "filename" или "username" (нет разделителя _ или -)
            if re.search(r'(?:^|[_\-])' + re.escape(f) + r'(?:[_\-]|$)', name):
                return True
            # placeholder= — человекочитаемый текст, substring достаточно
            if f in placeholder:
                return True
    return False


def _find_prechecked_consent_checkbox(
    form: Tag,
    consent_keywords: list[str],
    exclude_keywords: list[str],
) -> str | None:
    """
    Ищет <input type="checkbox" checked> относящийся к согласию на ПДн.
    Возвращает текст метки или None если не найдено.
    """
    for checkbox in form.find_all("input", type="checkbox"):
        if checkbox.get("checked") is None:
            continue
        label_text = _get_checkbox_label(form, checkbox).lower()
        if not any(kw in label_text for kw in consent_keywords):
            continue
        if any(kw in label_text for kw in exclude_keywords):
            continue
        return label_text
    return None


def _get_checkbox_label(form: Tag, checkbox: Tag) -> str:
    """
    Получает текст метки чекбокса тремя способами:
    1. <label for="id"> — явная связь
    2. Родительский <label> (обёртка)
    3. Следующий sibling-текст или <label>
    """
    checkbox_id = checkbox.get("id")
    if checkbox_id:
        label = form.find("label", attrs={"for": checkbox_id})
        if label:
            return label.get_text(strip=True)

    parent = checkbox.parent
    if parent and parent.name == "label":
        return parent.get_text(strip=True)

    for sibling in checkbox.next_siblings:
        if sibling.name is None:  # NavigableString
            text = str(sibling).strip()
            if text:
                return text
        elif sibling.name == "label":
            return sibling.get_text(strip=True)
        else:
            break

    return ""
