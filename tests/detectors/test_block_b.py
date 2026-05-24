"""
tests/detectors/test_block_b.py — Тесты детекторов B1, B2, B3.
"""
from pathlib import Path

import yaml
from bs4 import BeautifulSoup

from scanner.detectors.html_checkbox_prechecked import HtmlCheckboxPrecheckedDetector
from scanner.detectors.html_form_no_consent import HtmlFormNoConsentDetector
from scanner.detectors.html_form_no_policy_link import HtmlFormNoPolicyLinkDetector

FIXTURES = Path(__file__).parent / "fixtures"
LAW_BASE = Path(__file__).parent.parent.parent / "law_base" / "blocks"


def _load_b1_config() -> dict:
    with (LAW_BASE / "B.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return next(v for v in data["violations"] if v["id"] == "B1")


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_b1_violation_checkbox_prechecked():
    """Форма с ПДн и предустановленным чекбоксом согласия — нарушение B1."""
    html = (FIXTURES / "b1_violation.html").read_text(encoding="utf-8")
    result = HtmlCheckboxPrecheckedDetector(_load_b1_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "B1"
    assert result[0]["evidence"]["form_index"] == 0
    assert result[0]["evidence"]["checkbox_text"] != ""


def test_b1_compliant_checkbox_unchecked():
    """Форма с ПДн и непредустановленным чекбоксом согласия — нарушений нет."""
    html = (FIXTURES / "b1_compliant.html").read_text(encoding="utf-8")
    result = HtmlCheckboxPrecheckedDetector(_load_b1_config()).detect(_soup(html), [])

    assert result == []


# ── B2 ────────────────────────────────────────────────────────────────────────

def _load_b2_config() -> dict:
    with (LAW_BASE / "B.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return next(v for v in data["violations"] if v["id"] == "B2")


def test_b2_violation_no_consent_checkbox():
    """Форма с ПДн без чекбокса согласия — нарушение B2."""
    html = (FIXTURES / "b2_violation.html").read_text(encoding="utf-8")
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "B2"
    assert result[0]["is_recommendation"] is False
    assert result[0]["evidence"]["form_index"] == 0
    assert result[0]["evidence"]["detail"] != ""
    assert len(result[0]["evidence"]["matched_fields"]) > 0


def test_b2_compliant_has_consent_checkbox():
    """Форма с ПДн и чекбоксом согласия — нарушений нет."""
    html = (FIXTURES / "b2_compliant.html").read_text(encoding="utf-8")
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])

    assert result == []


def test_b2_alternative_consent_is_recommendation():
    """Форма без чекбокса, но с согласием в тексте кнопки — рекомендация, не нарушение."""
    html = (FIXTURES / "b2_alternative_consent.html").read_text(encoding="utf-8")
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "B2"
    assert result[0]["is_recommendation"] is True
    assert result[0]["evidence"]["form_index"] == 0
    assert result[0]["evidence"]["alternative_consent_text"] is not None
    assert len(result[0]["evidence"]["matched_fields"]) > 0


# ── B3 ────────────────────────────────────────────────────────────────────────

def _load_b3_config() -> dict:
    with (LAW_BASE / "B.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return next(v for v in data["violations"] if v["id"] == "B3")


def test_b3_violation_no_policy_link():
    """Форма с чекбоксом согласия, но без ссылки на политику — нарушение B3."""
    html = (FIXTURES / "b3_violation.html").read_text(encoding="utf-8")
    result = HtmlFormNoPolicyLinkDetector(_load_b3_config()).detect(_soup(html), [])

    assert len(result) == 1
    assert result[0]["id"] == "B3"
    assert result[0]["is_recommendation"] is False
    assert result[0]["evidence"]["form_index"] == 0
    assert result[0]["evidence"]["detail"] != ""


def test_b3_compliant_has_policy_link():
    """Форма со ссылкой на политику внутри — нарушений нет."""
    html = (FIXTURES / "b3_compliant.html").read_text(encoding="utf-8")
    result = HtmlFormNoPolicyLinkDetector(_load_b3_config()).detect(_soup(html), [])

    assert result == []


# ── Регрессионные тесты Bug 2 — pd_fields word-boundary ──────────────────────

def test_b2_no_false_positive_filename_field():
    """Форма с name='filename'/'username' не должна триггерить B2 — 'name' не подстрока."""
    html = """
    <form>
      <input type="text" name="filename" placeholder="Путь к файлу">
      <input type="text" name="username" placeholder="Логин">
      <input type="submit" value="Загрузить">
    </form>
    """
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])
    assert result == [], f"Ложное срабатывание B2 на форму без ПДн: {result}"


def test_b2_true_positive_name_field():
    """Форма с name='name' (точное совпадение) — должна триггерить B2.
    Placeholder нейтральный — тест изолирует name= атрибут, не placeholder."""
    html = """
    <form>
      <input type="text" name="name" placeholder="Введите данные">
      <input type="submit" value="Отправить">
    </form>
    """
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])
    assert len(result) == 1 and result[0]["id"] == "B2"
    assert "name=name" in result[0]["evidence"]["matched_fields"]


def test_b2_true_positive_first_name_field():
    """Форма с name='first_name' (компонент через _) — должна триггерить B2.
    Placeholder нейтральный — тест изолирует name= атрибут, не placeholder."""
    html = """
    <form>
      <input type="text" name="first_name" placeholder="Введите данные">
      <input type="submit" value="Отправить">
    </form>
    """
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])
    assert len(result) == 1 and result[0]["id"] == "B2"
    assert "name=first_name" in result[0]["evidence"]["matched_fields"]


def test_b2_implicit_submit_button_alternative_consent():
    """<button> без type= — неявный submit по HTML-спеку — должен обнаруживаться."""
    html = """
    <form>
      <input type="text" name="name" placeholder="Введите данные">
      <button>Нажимая, вы соглашаетесь с условиями обработки данных</button>
    </form>
    """
    result = HtmlFormNoConsentDetector(_load_b2_config()).detect(_soup(html), [])
    assert len(result) == 1
    assert result[0]["id"] == "B2"
    assert result[0]["is_recommendation"] is True
