"""Application entry point for File Utility Suite."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from routers.media import router as media_router
from services.cleanup import cleanup_old_files, ensure_storage_directories

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None, None]:
    """Prepare storage and remove stale files when the application starts."""
    ensure_storage_directories(UPLOADS_DIR, OUTPUTS_DIR)
    cleanup_old_files((UPLOADS_DIR, OUTPUTS_DIR), max_age_hours=24)
    cleanup_task = asyncio.create_task(_run_periodic_cleanup())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


async def _run_periodic_cleanup() -> None:
    """Remove expired uploads and outputs hourly while the app is running."""
    while True:
        await asyncio.sleep(60 * 60)
        await asyncio.to_thread(
            cleanup_old_files,
            (UPLOADS_DIR, OUTPUTS_DIR),
            max_age_hours=24,
        )


app = FastAPI(
    title="File Utility Suite",
    description="Browser-based file tools with FastAPI audio and video editing.",
    version="1.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.include_router(media_router, prefix="/api")
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add baseline browser security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self'; "
        "font-src 'self'; media-src 'self' blob:; connect-src 'self'; "
        "form-action 'none'; frame-ancestors 'none'; "
        "base-uri 'self'"
    )
    return response


def render_error(
    request: Request,
    message: str,
    status_code: int,
) -> HTMLResponse:
    """Render a user-friendly error page."""
    return templates.TemplateResponse(
        request=request,
        name="error.html",
        context={"message": message, "status_code": status_code},
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse, name="home")
async def home(request: Request) -> HTMLResponse:
    """Render the home dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"request": request},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(
    request: Request,
    exc: HTTPException,
) -> HTMLResponse | JSONResponse:
    """Render expected HTTP failures without exposing a traceback."""
    detail = (
        str(exc.detail)
        if isinstance(exc.detail, str)
        else "The request could not be completed."
    )
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"error": {"code": "REQUEST_FAILED", "message": detail}},
            status_code=exc.status_code,
        )
    return render_error(request, detail, exc.status_code)


@app.exception_handler(RequestValidationError)
async def request_validation_handler(
    request: Request,
    _: RequestValidationError,
) -> HTMLResponse | JSONResponse:
    """Turn missing or malformed form values into a helpful page."""
    message = (
        "Some required information is missing or invalid. "
        "Please check the form and try again."
    )
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"error": {"code": "VALIDATION_ERROR", "message": message}},
            status_code=422,
        )
    return render_error(
        request,
        message,
        422,
    )


@app.exception_handler(Exception)
async def unexpected_exception_handler(
    request: Request,
    exc: Exception,
) -> HTMLResponse:
    """Log unexpected failures and return a generic error page."""
    logger.exception("Unhandled application error: %s", exc)
    return render_error(
        request,
        "Something went wrong while processing your request. Please try again.",
        500,
    )
