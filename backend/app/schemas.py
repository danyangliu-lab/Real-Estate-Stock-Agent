from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel


class StockOut(BaseModel):
    id: int
    code: str
    name: str
    market: str
    sector: str
    is_active: int

    class Config:
        from_attributes = True


class RatingOut(BaseModel):
    id: int
    code: str
    name: str
    market: str
    date: date
    trend_score: float
    momentum_score: float
    volatility_score: float
    volume_score: float
    value_score: float
    ai_score: float
    total_score: float
    rating: str
    reason: str

    class Config:
        from_attributes = True


class PriceOut(BaseModel):
    date: date
    open: Optional[float]
    high: Optional[float]
    low: Optional[float]
    close: Optional[float]
    volume: Optional[float]
    change_pct: Optional[float]

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    total_stocks: int
    rated_today: int
    avg_score: float
    market_distribution: dict
    rating_distribution: dict


class RatingHistoryOut(BaseModel):
    date: date
    total_score: float
    rating: str

    class Config:
        from_attributes = True
