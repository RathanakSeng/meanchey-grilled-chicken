import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.attendance.scheduler import run_forever
from app.bootstrap import bootstrap
from app.bot.runtime import create_runtime
from app.bot.webhook import router as telegram_webhook_router
from app.config import get_settings
from app.core.errors import install_error_handlers
from app.db import SessionLocal, engine
from app.services.redaction import ViewerContextMiddleware

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Webhook mode: one Bot + Dispatcher per process, used by /api/telegram/webhook.
    telegram = create_runtime(get_settings())
    app.state.telegram = telegram
    async with SessionLocal() as session:
        await bootstrap(session, telegram)
    # Attendance: absent records, forgot check-out and reminders, every minute (one worker at a
    # time through an advisory lock).
    scheduler = None
    if get_settings().attendance_scheduler_enabled:
        scheduler = asyncio.create_task(run_forever(lambda: app.state.telegram))
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await scheduler
        if telegram is not None:
            await telegram.close()
        app.state.telegram = None
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Mean Chey Grilled Chicken API",
        description="មាន់អាំងមានជ័យ — authentication, users and permissions (Phase 1).",
        version="0.1.0",
        lifespan=lifespan,
        # Interactive docs describe every role, so they are off outside development.
        docs_url="/docs" if settings.api_docs else None,
        redoc_url="/redoc" if settings.api_docs else None,
        openapi_url="/openapi.json" if settings.api_docs else None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ViewerContextMiddleware)
    install_error_handlers(app)
    app.state.telegram = None  # set by the lifespan in webhook mode
    app.include_router(api_router)
    app.include_router(telegram_webhook_router)

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
