"""GumaWeb API - application factory."""

from __future__ import annotations

import logging
import re
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import GumaWebError
from app.core.logging import configure_logging

logger = logging.getLogger("gumaweb.api")

REQUESTS = Counter("gumaweb_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("gumaweb_http_request_duration_seconds", "HTTP request latency", ["method", "route"])


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    app = FastAPI(
        title="GumaWeb API",
        version="0.1.0",
        description="Autonomous Website Factory: discover → generate → publish → claim → convert.",
        docs_url="/docs",
        openapi_url=f"{settings.api_v1_prefix}/openapi.json",
    )

    # Generated sites (*.gumaweb.io, or the local static server) call the public endpoints.
    site_origin = rf"https://([a-z0-9-]+\.)?{re.escape(settings.public_site_domain)}"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=rf"^({site_origin}|http://localhost:\d+)$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def metrics_and_security_headers(request: Request, call_next):
        start = time.perf_counter()
        response: Response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")
        LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
        REQUESTS.labels(request.method, path, response.status_code).inc()
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if "frame-ancestors" not in response.headers.get("Content-Security-Policy", ""):
            response.headers.setdefault("X-Frame-Options", "DENY")  # a route may allow named framers via CSP
        return response

    @app.exception_handler(GumaWebError)
    async def domain_error_handler(_: Request, exc: GumaWebError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "detail": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"error": "validation_failed", "detail": errors})

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    if settings.environment in ("development", "test"):
        # Convenience preview of published sites without the nginx static server.
        settings.generated_sites_dir.mkdir(parents=True, exist_ok=True)
        app.mount("/sites", StaticFiles(directory=settings.generated_sites_dir, html=True), name="sites")

    return app


app = create_app()
