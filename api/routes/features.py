from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from services.features import FeatureDetail, building_at, building_detail, in_loaded_area

router = APIRouter(prefix="/features", tags=["features"])


async def connection(request: Request) -> AsyncIterator[AsyncConnection]:
    async with request.app.state.engine.connect() as conn:
        yield conn


Conn = Annotated[AsyncConnection, Depends(connection)]


class FeatureRef(BaseModel):
    fid: str


@router.get("/at")
async def feature_at(
    conn: Conn,
    lng: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
) -> FeatureRef:
    """The building at a point. 404 detail is "outside_area" or "no_building"."""
    fid = await building_at(conn, lng, lat)
    if fid:
        return FeatureRef(fid=fid)
    covered = await in_loaded_area(conn, lng, lat)
    raise HTTPException(404, "no_building" if covered else "outside_area")


@router.get("/{fid}")
async def feature_detail(conn: Conn, fid: str) -> FeatureDetail:
    detail = await building_detail(conn, fid)
    if detail is None:
        raise HTTPException(404, "not_found")
    return detail
