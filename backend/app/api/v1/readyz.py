"""Readiness probe — verifies Postgres connectivity."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session

router = APIRouter(tags=["health"])


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict:
    result = await session.execute(text("SELECT 1"))
    value = result.scalar_one()
    return {"status": "ready", "db": value}
