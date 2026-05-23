"""
Whale Ship-Strike Risk Navigator — FastAPI application entry point.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.services.data_loader import load_all_data
from app.services.scheduler import start_scheduler, stop_scheduler
from app.routers import risk, species, incidents, whale_zones, vessels


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Whale Strike Navigator API...")
    load_all_data()
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Shutting down.")


app = FastAPI(
    title="Whale Ship-Strike Risk Navigator",
    description=(
        "Real-time overlay of global shipping traffic with seasonal whale "
        "migration zones. Identifies and scores high-risk overlap areas to "
        "protect endangered whale species."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(risk.router,         prefix="/risk",        tags=["risk"])
app.include_router(species.router,      prefix="/species",     tags=["species"])
app.include_router(incidents.router,    prefix="/incidents",   tags=["incidents"])
app.include_router(whale_zones.router,  prefix="/whale-zones", tags=["whale-zones"])
app.include_router(vessels.router,      prefix="/vessels",     tags=["vessels"])


@app.get("/health", tags=["meta"])
async def health():
    return {
        "status": "ok",
        "env": settings.app_env,
        "ais_refresh_interval_minutes": settings.ais_refresh_interval_minutes,
    }