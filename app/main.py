import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.logging_config import configure_logging
from app.api.v1.router import v1_router
from app.database import engine, Base

configure_logging(settings.app_env)
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting media-master-api", env=settings.app_env)
    # Create temp dir
    import os
    os.makedirs(settings.temp_dir, exist_ok=True)
    yield
    logger.info("Shutting down media-master-api")
    await engine.dispose()


app = FastAPI(
    title="Media Master API",
    description="Autonomous media generation API for n8n automation workflows",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(v1_router, prefix="/api/v1")
