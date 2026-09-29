"""FastAPI-приложение сайта: сборка, middleware, обработчики ошибок."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from app.config import Config, get_config
from app.db.session import make_engine, make_session_factory
from app.utils.logging import get_logger, setup_logging
from app.web.deps import LoginRequired
from app.web.render import render

log = get_logger("web.main")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or get_config()
    setup_logging(cfg.log_level)
    Path(cfg.receipts_dir).mkdir(parents=True, exist_ok=True)

    from app.web.routes import admin, auth, buy, cabinet, public, webhooks

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(cfg)
        app.state.engine = engine
        app.state.session_factory = make_session_factory(engine)
        log.info("site.started", db=cfg.database_url_resolved, base_url=cfg.site_base_url)
        yield
        from app.services.xui.factory import close_all

        await close_all()
        await engine.dispose()
        log.info("site.stopped")

    app = FastAPI(title=f"{cfg.brand_name} — кабинет", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.cfg = cfg

    app.add_middleware(
        SessionMiddleware,
        secret_key=cfg.session_secret_value,
        session_cookie="vpnsite",
        max_age=14 * 24 * 3600,
        same_site="lax",
        https_only=cfg.cookie_https_only,
    )
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(public.router)
    app.include_router(auth.router)
    app.include_router(cabinet.router)
    app.include_router(buy.router)
    app.include_router(admin.router)
    app.include_router(webhooks.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={exc.next_path}", status_code=303)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # сессия БД могла закрыться при teardown — не трогаем user в шаблонах
        request.state.user = None
        if exc.status_code == 404:
            return render(request, "errors/404.html", {}, status_code=404)
        if exc.status_code == 403:
            return render(request, "errors/403.html", {"detail": exc.detail}, status_code=403)
        return render(request, "errors/500.html", {}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        request.state.user = None
        log.error("site.unhandled_error", err=str(exc), path=request.url.path)
        return render(request, "errors/500.html", {}, status_code=500)

    return app


app = create_app()
