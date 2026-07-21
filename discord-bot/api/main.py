"""
FastAPI application — Bubble-compatible REST API.
Mounted alongside the Discord bot via asyncio task.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from api.routes import auth, users, logs, stats
from config.settings import settings
from utils.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API server starting...")
    yield
    logger.info("API server shutting down...")


app = FastAPI(
    title="Discord Security Bot API",
    description=(
        "REST API für den Discord Sicherheits- und Moderationsbot. "
        "Optimiert für Bubble-Integration. "
        "Alle Endpunkte erfordern JWT-Authentifizierung (außer /auth/login)."
    ),
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

# CORS — Bubble needs this
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled API exception: %s %s — %s", request.method, request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "type": type(exc).__name__},
    )


# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(stats.router, prefix="/api")


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "Discord Security Bot API", "version": "1.0.0"}


@app.get("/api/health", tags=["Health"])
async def health():
    return {
        "status": "healthy",
        "service": "discord-security-bot-api",
        "version": "1.0.0",
    }
