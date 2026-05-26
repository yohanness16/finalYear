"""Favorites and ratings endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.favorite import Favorite
from app.models.rating import Rating
from app.models.user import User
from app.schemas.tracking import FavoriteCreate, RatingCreate

router = APIRouter()


@router.post("/favorites")
async def add_favorite(body: FavoriteCreate, db: AsyncSession = Depends(get_db)):
    fav = Favorite(user_id=body.user_id, route_id=body.route_id, nickname=body.nickname)
    db.add(fav)
    await db.flush()
    await db.refresh(fav)
    return {
        "id": fav.id,
        "user_id": body.user_id,
        "route_id": body.route_id,
        "nickname": body.nickname,
    }


@router.get("/favorites/{user_id}")
async def list_favorites(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Favorite).where(Favorite.user_id == user_id))
    return list(result.scalars().all())


@router.delete("/favorites/{favorite_id}")
async def delete_favorite(
    favorite_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a favorite route (must own it or be admin)."""
    fav = await db.get(Favorite, favorite_id)
    if not fav:
        raise HTTPException(404, "Favorite not found")
    if fav.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(403, "Not your favorite")
    await db.delete(fav)
    await db.flush()
    return {"status": "deleted", "id": favorite_id}


@router.post("/ratings")
async def add_rating(body: RatingCreate, db: AsyncSession = Depends(get_db)):
    if not 1 <= body.score <= 5:
        raise HTTPException(400, "Score must be 1-5")
    rating = Rating(
        user_id=body.user_id,
        assignment_id=body.assignment_id,
        score=body.score,
        comment=body.comment,
    )
    db.add(rating)
    await db.flush()
    await db.refresh(rating)
    return {"id": rating.id, "score": body.score}


@router.get("/ratings/{assignment_id}")
async def list_ratings(assignment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Rating).where(Rating.assignment_id == assignment_id)
    )
    return list(result.scalars().all())
