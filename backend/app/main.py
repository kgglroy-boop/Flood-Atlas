import logging

import psycopg
from fastapi import FastAPI, HTTPException

from app.database import check_database, open_database
from app.scenarios import ScenarioCatalog, ScenarioCatalogUnavailable, read_scenario_catalog
from app.analysis_routes import router as analysis_router
from app.tiles import router as tiles_router
from app.case_routes import router as cases_router
from app.case_import_routes import router as imports_router

app = FastAPI(title="Urban Flood WebGIS", version="0.1.0")
app.include_router(analysis_router)
app.include_router(tiles_router)
app.include_router(cases_router)
app.include_router(imports_router)


@app.get('/api/v1/scenarios', response_model=ScenarioCatalog)
def scenarios():
    try:
        with open_database() as connection:
            return read_scenario_catalog(connection)
    except ScenarioCatalogUnavailable:
        logger.warning('Scenario catalog validation failed')
        raise HTTPException(status_code=503, detail='scenario catalog unavailable') from None
    except psycopg.Error:
        logger.warning('Scenario database read failed')
        raise HTTPException(status_code=503, detail='database unavailable') from None
logger = logging.getLogger("urban_flood.health")


@app.get("/api/v1/health", tags=["health"])
def health() -> dict[str, str]:
    """Readiness includes a real database connection and PostGIS function call."""
    try:
        check_database()
    except psycopg.Error:
        # Driver exception strings can contain credentials; never log them.
        logger.warning("Database readiness check failed")
        raise HTTPException(status_code=503, detail="database unavailable") from None
    return {"status": "ok"}
