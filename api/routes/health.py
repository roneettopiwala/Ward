import asyncio

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter()

CHECK_TIMEOUT_S = 2.0


class ServiceStatus(BaseModel):
    ok: bool
    detail: str | None = None


class DatabaseStatus(ServiceStatus):
    postgis_version: str | None = None


class HealthResponse(BaseModel):
    api: ServiceStatus
    database: DatabaseStatus
    redis: ServiceStatus


async def check_database(request: Request) -> DatabaseStatus:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            async with request.app.state.engine.connect() as conn:
                version = await conn.scalar(text("SELECT postgis_lib_version()"))
        return DatabaseStatus(ok=True, postgis_version=version)
    except Exception as exc:
        return DatabaseStatus(ok=False, detail=f"{type(exc).__name__}: {exc}")


async def check_redis(request: Request) -> ServiceStatus:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_S):
            await request.app.state.redis.ping()
        return ServiceStatus(ok=True)
    except Exception as exc:
        return ServiceStatus(ok=False, detail=f"{type(exc).__name__}: {exc}")


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    database, redis = await asyncio.gather(check_database(request), check_redis(request))
    return HealthResponse(api=ServiceStatus(ok=True), database=database, redis=redis)
