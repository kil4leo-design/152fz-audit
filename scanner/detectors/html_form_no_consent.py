"""
scanner/detectors/html_form_no_consent.py — Детектор B2.

Нарушение: ст. 9 152-ФЗ → ч.2 ст.13.11 КоАП.
Штраф для юрлица: 300 000 – 700 000 руб.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.detectors.base import BaseDetector

if TYPE_CHECKING:
    from bs4 import BeautifulSoup, Tag


class HtmlFormNoConsentDetector(BaseDetector):
    """
    Детектор B2: форма с ПДн не содержит чекбокса согласия.

    Алгоритм:
    1. Перебрать все <form> (form_index = 0-based).
    2. Если форма не собирает ПДн — пропустить.
    3. Проверить наличие consent-чекбокса (input[type=checkbox] + consent_keywords,
       без exclude_keywords).
    4. Если чекбокс найден — нарушения нет.
    5. Если нет — проверить alternative_consent (текст у кнопки submit).
       Альтернативное согласие юридически спорно → is_recommendation=True.
    6. Нарушение → evidence с form_index (обязательно для _apply_b_mutex).
    """

    def detect(self, soup: BeautifulSoup, network_log: list[dict]) -> list[dict]:
        pd_fields = [f.lower() for f in self.params.get("pd_fields", [])]
        pd_input_types = [t.lower() for t in self.params.get("pd_input_types", [])]
        consent_keywords = [kw.lower() for kw in self.params.get("consent_keywords", [])]
        exclude_keywords = [kw.lower() for kw in self.params.get("exclude_keywords", [])]
        alt_consent_cfg = self.params.get("alternative_consent", {})

        violations = []
        for form_index, form in enumerate(soup.find_all("form")):
            if not _form_has_pd_fields(form, pd_fields, pd_input_types):
                continue
            if _form_has_consent_checkbox(form, consent_keywords, exclude_keywords):
                continue

            # Чекбокса нет — проверяем альтернативное согласие
            alt = None
            if alt_consent_cfg.get("check_near_submit"):
                alt_keywords = [kw.lower() for kw in alt_consent_cfg.get("keywords", [])]
                alt = _find_alternative_consent(form, alt_keywords)

            if alt is not None:
                # Альтернативное согласие юридически спорно →
                # фиксируем как рекомендацию, не как нарушение
                result = self._build_result({
                    "form_index": form_index,
                    "detail": "Чекбокс согласия отсутствует; найдено альтернативное согласие в тексте кнопки",
                    "alternative_consent_text": alt,
                })
                result["is_recommendation"] = True
                violations.append(result)
            else:
                violations.append(self._build_result({
                    "form_index": form_index,
                    "detail": "Форма собирает персональные данные без чекбокса согласия",
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


def _form_has_consent_checkbox(
    form: Tag, consent_keywords: list[str], exclude_keywords: list[str]
) -> bool:
    """Возвращает True если форма содержит хотя бы один consent-чекбокс."""
    for checkbox in form.find_all("input", type="checkbox"):
        label_text = _get_checkbox_label(form, checkbox).lower()
        if not any(kw in label_text for kw in consent_keywords):
            continue
        if any(kw in label_text for kw in exclude_keywords):
            continue
        return True
    return False


def _find_alternative_consent(form: Tag, alt_keywords: list[str]) -> str | None:
    """
    Ищет альтернативное согласие: текст рядом с кнопкой submit содержит
    ключевое слово типа «нажимая», «соглашаетесь» и т.д.
    Проверяет: текст кнопки, соседний <p>/<div>/<span>, родительский контейнер.
    """
    for submit in form.find_all(["input", "button"], type="submit"):
        # Текст самой кнопки
        btn_text = (submit.get("value") or submit.get_text(strip=True) or "").lower()
        if any(kw in btn_text for kw in alt_keywords):
            return btn_text

        # Текст родительского контейнера
        parent = submit.parent
        if parent:
            parent_text = parent.get_text(separator=" ", strip=True).lower()
            if any(kw in parent_text for kw in alt_keywords):
                return parent_text

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
