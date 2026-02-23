from sqlalchemy import Column, String, Float, Integer, DateTime, Date, Text, Index
from sqlalchemy.sql import func
from app.database import Base


class Stock(Base):
    __tablename__ = "stocks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)  # A, HK, US
    sector = Column(String(50), default="房地产")
    market_cap = Column(Float, nullable=True)
    is_active = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class StockPrice(Base):
    __tablename__ = "stock_prices"
    __table_args__ = (Index("ix_price_code_date", "code", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False)
    date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(Float)
    turnover = Column(Float)
    change_pct = Column(Float)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (Index("ix_rating_code_date", "code", "date"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False)
    name = Column(String(100), nullable=False)
    market = Column(String(10), nullable=False)
    date = Column(Date, nullable=False)
    # 评分维度 (0-100)
    trend_score = Column(Float, default=0)
    momentum_score = Column(Float, default=0)
    volatility_score = Column(Float, default=0)
    volume_score = Column(Float, default=0)
    value_score = Column(Float, default=0)
    ai_score = Column(Float, default=0)
    # 综合评分
    total_score = Column(Float, default=0)
    # 评级: 强烈推荐/推荐/中性/谨慎/回避
    rating = Column(String(20), nullable=False)
    # 评级理由
    reason = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())
