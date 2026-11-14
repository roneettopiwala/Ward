from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from services import features
from services.features import FeatureDetail

router = APIRouter(prefix="/features", tags=["features"])


async def connection(request: Request) -> AsyncIterator[AsyncConnection]:
    async with request.app.state.engine.connect() as conn:
        yield conn


Conn = Annotated[AsyncConnection, Depends(connection)]


@router.get("/{fid}")
async def feature_detail(conn: Conn, fid: str) -> FeatureDetail:
    """Any map feature by fid: building, parcel, park, transit, cycling or street."""
    detail = await features.detail(conn, fid)
    if detail is None:
        raise HTTPException(404, "not_found")
    return detail
