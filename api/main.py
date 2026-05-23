"""
api/main.py — FastAPI приложение.

Эндпоинты:
    POST /scan   — сканировать URL, вернуть отчёт JSON
    GET  /health — статус сервиса

Scanner запускается один раз через FastAPI lifespan:
браузер живёт всё время работы сервиса, не создаётся на каждый запрос.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AnyHttpUrl, BaseModel

from report.engine import build as build_report
from scanner.scanner import Scanner

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with Scanner() as scanner:
        app.state.scanner = scanner
        yield


app = FastAPI(
    title="152-ФЗ Audit API",
    description="Проверка сайтов на соответствие 152-ФЗ (персональные данные, РФ)",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS: разрешить запросы с любого origin для MVP.
# В production сужать до домена UI.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    url: AnyHttpUrl


@app.post("/scan")
async def scan(body: ScanRequest, req: Request) -> dict:
    """
    Сканировать URL и вернуть отчёт о нарушениях 152-ФЗ.

    - **422** — невалидный URL
    - **500** — ошибка загрузки страницы (сеть, таймаут и т.д.)

    robots.txt не блокирует скан — отчёт содержит поле robots_warning если доступ ограничен.
    """
    url = str(body.url)
    try:
        violations, robots_warning, waf_blocked, blocked_excerpt = await req.app.state.scanner.scan(url)
    except Exception as exc:
        logger.exception("Ошибка сканирования %s", url)
        raise HTTPException(status_code=500, detail=str(exc))
    return build_report(violations, url, robots_warning, waf_blocked, blocked_excerpt)


@app.get("/health")
async def health() -> dict:
    """Статус сервиса."""
    return {"status": "ok"}
