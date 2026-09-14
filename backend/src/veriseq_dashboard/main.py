from __future__ import annotations

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api import router
from .auth_routes import router as auth_router
from .config import get_settings
from .errors import DashboardError


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield


app = FastAPI(
    title="VeriSeq Dashboard API",
    version="0.1.0",
    lifespan=lifespan,
)
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-Dev-User-Email", "X-CSRF-Token", "Idempotency-Key"],
)
app.include_router(router)
app.include_router(auth_router)


@app.exception_handler(DashboardError)
async def dashboard_error_handler(request: Request, exc: DashboardError) -> JSONResponse:
    trace_id = request.headers.get("X-Trace-ID") or __import__("uuid").uuid4().hex
    if exc.code in {"AUTHENTICATION_REQUIRED", "LOGIN_FAILED"}:
        status_code = 401
    elif exc.code in {"ACCESS_DENIED", "ADMIN_REQUIRED", "CSRF_VALIDATION_FAILED"}:
        status_code = 403
    elif exc.code.endswith("NOT_FOUND"):
        status_code = 404
    else:
        status_code = 409
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "trace_id": trace_id,
                "details": exc.details,
            }
        },
    )


def run() -> None:
    uvicorn.run("veriseq_dashboard.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()
