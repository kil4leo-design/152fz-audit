# Changelog

## [Unreleased]

### Added
- `scanner/detectors/base.py` — абстрактный базовый класс `BaseDetector`:
  сигнатура `detect(soup, network_log)`, хелпер `_build_result()`
- `scanner/engine.py` — `DetectorEngine`: загрузка Law Base, Pydantic-валидация YAML,
  фабричный паттерн (dispatch по `detector.method`), `run_all()`
- `scanner/__init__.py`, `scanner/detectors/__init__.py` — Python-пакеты (fix: ImportError)
- `pydantic>=2.0` в `requirements.txt` — явная зависимость (ранее только транзитивная через FastAPI)

### Infrastructure (Этап 0)
- Репозиторий, ветки main/dev, branch protection
- CI: lint.yml (ruff), test.yml (pytest)
- Шаблоны: PR, Issues (bug / feature / detector)
- Law Base MVP: A.yaml (A1), B.yaml (B1, B2, B3), C.yaml (C1, C2), sources.yaml — верифицированы
- docs/: decisions.md, roadmap.md, architecture.md, START.md
