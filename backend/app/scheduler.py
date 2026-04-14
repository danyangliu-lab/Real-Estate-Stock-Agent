"""
定时任务调度器
每天收盘后自动刷新数据和评级
"""

import asyncio
import logging
import random
from datetime import date

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models import Stock, StockPrice, Rating
from app.stock_list import REAL_ESTATE_STOCKS
from app.data_fetcher import fetch_stock_hist
from app.rating_engine import rate_stock, rate_stock_soochow

logger = logging.getLogger(__name__)


async def init_stock_list():
    """初始化/同步股票列表到数据库（新增缺失的，停用已移除的）"""
    target_codes = {s["code"] for s in REAL_ESTATE_STOCKS}
    target_map = {s["code"]: s for s in REAL_ESTATE_STOCKS}

    async with async_session() as session:
        result = await session.execute(select(Stock))
        existing = result.scalars().all()
        existing_codes = {s.code for s in existing}

        # 新增
        added = 0
        for s in REAL_ESTATE_STOCKS:
            if s["code"] not in existing_codes:
                session.add(Stock(code=s["code"], name=s["name"], market=s["market"]))
                added += 1

        # 重新激活已存在但被停用的，停用已移除的
        reactivated = 0
        deactivated = 0
        for stock in existing:
            if stock.code in target_codes:
                if not stock.is_active:
                    stock.is_active = 1
                    reactivated += 1
                # 更新名称（防止改名）
                info = target_map[stock.code]
                if stock.name != info["name"]:
                    stock.name = info["name"]
            else:
                if stock.is_active:
                    stock.is_active = 0
                    deactivated += 1

        await session.commit()
        if added or reactivated or deactivated:
            logger.info(f"股票列表同步: 新增{added}, 重新激活{reactivated}, 停用{deactivated}, 目标{len(REAL_ESTATE_STOCKS)}只")
        else:
            logger.info(f"股票列表已是最新({len(target_codes)}只)")


async def refresh_all_data():
    """刷新所有股票数据和评级（核心定时任务）"""
    logger.info("开始刷新股票数据和评级...")
    async with async_session() as session:
        result = await session.execute(select(Stock).where(Stock.is_active == 1))
        stocks = result.scalars().all()

    today = date.today()
    success_count = 0

    for stock in stocks:
        try:
            df = await asyncio.to_thread(fetch_stock_hist, stock.code, stock.market, 120)
            if df is None or df.empty:
                logger.warning(f"跳过 {stock.name}({stock.code}): 无数据")
                continue

            # 保存最近价格数据
            async with async_session() as session:
                # 删除该股票旧价格数据，重新写入
                await session.execute(
                    delete(StockPrice).where(StockPrice.code == stock.code)
                )
                for _, row in df.iterrows():
                    price = StockPrice(
                        code=stock.code,
                        date=row["date"],
                        open=float(row["open"]) if row["open"] else None,
                        high=float(row["high"]) if row["high"] else None,
                        low=float(row["low"]) if row["low"] else None,
                        close=float(row["close"]) if row["close"] else None,
                        volume=float(row["volume"]) if row["volume"] else None,
                        turnover=float(row.get("turnover", 0)) if row.get("turnover") else None,
                        change_pct=float(row.get("change_pct", 0)) if row.get("change_pct") else None,
                    )
                    session.add(price)
                await session.commit()

            # 评级模型1：量化AI选股
            rating_result = await rate_stock(df, stock.name, stock.code, stock.market)
            if rating_result:
                async with async_session() as session:
                    await session.execute(
                        delete(Rating).where(
                            Rating.code == stock.code,
                            Rating.date == today,
                            Rating.model_type == "quant_ai",
                        )
                    )
                    rating = Rating(
                        code=stock.code,
                        name=stock.name,
                        market=stock.market,
                        date=today,
                        model_type="quant_ai",
                        **rating_result,
                    )
                    session.add(rating)
                    await session.commit()
                success_count += 1
                logger.info(f"✓ [量化AI] {stock.name}({stock.code}) - {rating_result['rating']} ({rating_result['total_score']})")

            # 评级模型2：东吴地产选股
            soochow_result = await rate_stock_soochow(df, stock.name, stock.code, stock.market)
            if soochow_result:
                async with async_session() as session:
                    await session.execute(
                        delete(Rating).where(
                            Rating.code == stock.code,
                            Rating.date == today,
                            Rating.model_type == "soochow",
                        )
                    )
                    rating = Rating(
                        code=stock.code,
                        name=stock.name,
                        market=stock.market,
                        date=today,
                        model_type="soochow",
                        **soochow_result,
                    )
                    session.add(rating)
                    await session.commit()
                logger.info(f"✓ [东吴地产] {stock.name}({stock.code}) - {soochow_result['rating']} ({soochow_result['total_score']})")

            # 避免请求过快，随机间隔 2~4 秒
            await asyncio.sleep(random.uniform(2.0, 4.0))

        except Exception as e:
            logger.error(f"处理 {stock.name}({stock.code}) 失败: {e}")

    logger.info(f"刷新完成: {success_count}/{len(stocks)} 成功")

    return success_count
