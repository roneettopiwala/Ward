from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncConnection

from services import drawing

router = APIRouter(prefix="/draw", tags=["draw"])


async def connection(request: Request) -> AsyncIterator[AsyncConnection]:
    async with request.app.state.engine.connect() as conn:
        yield conn


Conn = Annotated[AsyncConnection, Depends(connection)]


@router.post("/route")
async def route(conn: Conn, body: drawing.RouteRequest) -> drawing.Route:
    """A line along the streets through the clicked points, avoiding highways."""
    try:
        return await drawing.route(conn, body.points)
    except drawing.RouteError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/validate")
async def validate(conn: Conn, body: drawing.ValidateRequest) -> drawing.Validation:
    """Check a drawn shape: size, inside Toronto, off water and highways, what it covers."""
    try:
        return await drawing.validate(conn, body.geometry, body.type)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
