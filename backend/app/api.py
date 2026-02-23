"""
API路由
"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Stock, Rating, StockPrice
from app.schemas import StockOut, RatingOut, PriceOut, DashboardStats, RatingHistoryOut

router = APIRouter(prefix="/api")


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    """仪表盘统计数据"""
    # 总股票数
    total = await db.scalar(select(func.count(Stock.id)).where(Stock.is_active == 1))

    # 查找最新评级日期
    latest_date = await db.scalar(select(func.max(Rating.date)))
    if not latest_date:
        return DashboardStats(
            total_stocks=total or 0, rated_today=0, avg_score=0,
            market_distribution={}, rating_distribution={}
        )

    rated_q = select(Rating).where(Rating.date == latest_date)
    result = await db.execute(rated_q)
    ratings = result.scalars().all()

    rated_count = len(ratings)
    avg_score = round(sum(r.total_score for r in ratings) / max(rated_count, 1), 1)

    # 市场分布
    market_dist = {}
    rating_dist = {}
    for r in ratings:
        market_dist[r.market] = market_dist.get(r.market, 0) + 1
        rating_dist[r.rating] = rating_dist.get(r.rating, 0) + 1

    return DashboardStats(
        total_stocks=total or 0,
        rated_today=rated_count,
        avg_score=avg_score,
        market_distribution=market_dist,
        rating_distribution=rating_dist,
    )


@router.get("/stocks", response_model=list[StockOut])
async def get_stocks(
    market: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """股票列表"""
    q = select(Stock).where(Stock.is_active == 1)
    if market:
        q = q.where(Stock.market == market)
    q = q.order_by(Stock.market, Stock.code)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/latest", response_model=list[RatingOut])
async def get_latest_ratings(
    market: Optional[str] = Query(None),
    rating: Optional[str] = Query(None),
    sort_by: Optional[str] = Query("total_score"),
    sort_dir: Optional[str] = Query("desc"),
    db: AsyncSession = Depends(get_db),
):
    """获取最新一期评级"""
    latest_date = await db.scalar(select(func.max(Rating.date)))
    if not latest_date:
        return []

    q = select(Rating).where(Rating.date == latest_date)
    if market:
        q = q.where(Rating.market == market)
    if rating:
        q = q.where(Rating.rating == rating)

    # 排序白名单
    allowed_sort = {"total_score", "trend_score", "momentum_score",
                    "volatility_score", "volume_score", "value_score", "ai_score", "name", "code"}
    if sort_by not in allowed_sort:
        sort_by = "total_score"
    sort_col = getattr(Rating, sort_by, Rating.total_score)
    if sort_dir == "asc":
        q = q.order_by(sort_col.asc())
    else:
        q = q.order_by(sort_col.desc())

    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/history/{code}", response_model=list[RatingOut])
async def get_rating_history(
    code: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """获取某只股票的历史评级"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating)
        .where(Rating.code == code, Rating.date >= since)
        .order_by(desc(Rating.date))
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/date/{target_date}", response_model=list[RatingOut])
async def get_ratings_by_date(
    target_date: date,
    market: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取指定日期的评级"""
    q = select(Rating).where(Rating.date == target_date)
    if market:
        q = q.where(Rating.market == market)
    q = q.order_by(desc(Rating.total_score))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/dates", response_model=list[date])
async def get_available_dates(db: AsyncSession = Depends(get_db)):
    """获取所有有评级数据的日期"""
    q = select(Rating.date).distinct().order_by(desc(Rating.date)).limit(90)
    result = await db.execute(q)
    return [row[0] for row in result.all()]


@router.get("/prices/{code}", response_model=list[PriceOut])
async def get_prices(
    code: str,
    days: int = Query(60, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """获取股票价格数据"""
    since = date.today() - timedelta(days=days)
    q = (
        select(StockPrice)
        .where(StockPrice.code == code, StockPrice.date >= since)
        .order_by(StockPrice.date)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/rating-trend/{code}", response_model=list[RatingHistoryOut])
async def get_rating_trend(
    code: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """获取评分趋势"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating.date, Rating.total_score, Rating.rating)
        .where(Rating.code == code, Rating.date >= since)
        .order_by(Rating.date)
    )
    result = await db.execute(q)
    return [
        RatingHistoryOut(date=row[0], total_score=row[1], rating=row[2])
        for row in result.all()
    ]
