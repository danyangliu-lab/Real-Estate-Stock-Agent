"""
AI Haoxing@东吴地产 - 后端服务
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, func, delete

from app.api import router
from app.config import ADMIN_USERNAME, ADMIN_PASSWORD, UPLOAD_DIR, API_KEY, JWT_SECRET, JWT_ALGORITHM
from app.database import init_db, async_session
from app.models import Rating, Stock, User, DailyDigest, WeeklyDigest, AIPick, REITItem, REITWeeklyPick
from app.auth import hash_password
from app.scheduler import init_stock_list, refresh_all_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")


async def init_admin():
    """首次启动时创建默认管理员账户"""
    async with async_session() as session:
        result = await session.execute(select(User).where(User.username == ADMIN_USERNAME))
        admin = result.scalar_one_or_none()
        if admin is None:
            admin = User(
                username=ADMIN_USERNAME,
                hashed_password=hash_password(ADMIN_PASSWORD),
                display_name="Jianghaoxing",
                is_admin=True,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            logger.info(f"默认管理员账户已创建: {ADMIN_USERNAME}")
        else:
            # 更新已有管理员的显示名称
            if admin.display_name != "Jianghaoxing":
                admin.display_name = "Jianghaoxing"
                await session.commit()
                logger.info("管理员显示名称已更新为 Jianghaoxing")
            else:
                logger.info("管理员账户已存在，跳过创建")


async def check_and_refresh():
    """检查本周是否已有足够的评级数据，不足则自动刷新（评分已改为每周一次）"""
    from datetime import timedelta
    today = date.today()
    # 检查最近7天内是否有评级数据
    week_ago = today - timedelta(days=7)
    async with async_session() as session:
        # 分别检查两个模型最近7天的评级数量
        quant_count = await session.scalar(
            select(func.count(Rating.id)).where(
                Rating.date >= week_ago, Rating.model_type == "quant_ai"
            )
        )
        soochow_count = await session.scalar(
            select(func.count(Rating.id)).where(
                Rating.date >= week_ago, Rating.model_type == "soochow"
            )
        )
        # 检查活跃股票总数
        stock_count = await session.scalar(
            select(func.count(Stock.id)).where(Stock.is_active == 1)
        )

    logger.info(f"本周评级检查: quant_ai={quant_count}, soochow={soochow_count}, 活跃股票={stock_count}")

    # 任一模型评级数量不足活跃股票数的80%，就触发全量刷新
    threshold = int(stock_count * 0.8) if stock_count else 0
    if quant_count < threshold or soochow_count < threshold:
        logger.info(f"本周评级数据不完整(阈值={threshold})，启动自动刷新...")
        await refresh_all_data()
    else:
        logger.info(f"本周双模型评级数据已完整，跳过刷新")


async def generate_all_digests():
    """每日自动生成所有日报（行业日报 + AI选股日报）"""
    from app.api import (
        _build_industry_digest_prompt,
        _build_ai_picks_digest_prompt,
        _generate_digest_with_multi_model,
    )

    today = date.today()
    logger.info(f"开始自动生成每日日报 ({today})...")

    async with async_session() as db:
        # 1. 行业日报
        try:
            existing = await db.execute(
                select(DailyDigest).where(
                    DailyDigest.digest_date == today,
                    DailyDigest.digest_type == "industry",
                    DailyDigest.user_id == 0,
                )
            )
            if existing.scalar_one_or_none():
                logger.info("行业日报今日已存在，跳过")
            else:
                prompt = await _build_industry_digest_prompt(db)
                if prompt:
                    result = await _generate_digest_with_multi_model(prompt)
                    if result["title"]:
                        digest = DailyDigest(
                            digest_date=today,
                            digest_type="industry",
                            user_id=0,
                            title=result["title"],
                            content=result["content"],
                            model_sources=result["sources"],
                        )
                        db.add(digest)
                        await db.commit()
                        logger.info(f"✓ 行业日报已生成: {result['title'][:30]}")
                    else:
                        logger.warning("行业日报: AI生成失败")
                else:
                    logger.warning("行业日报: 暂无评级数据，跳过")
        except Exception as e:
            logger.error(f"行业日报生成失败: {e}")

        # 2. AI选股日报
        try:
            existing = await db.execute(
                select(DailyDigest).where(
                    DailyDigest.digest_date == today,
                    DailyDigest.digest_type == "ai_picks",
                    DailyDigest.user_id == 0,
                )
            )
            if existing.scalar_one_or_none():
                logger.info("AI选股日报今日已存在，跳过")
            else:
                prompt = await _build_ai_picks_digest_prompt(db)
                if prompt:
                    result = await _generate_digest_with_multi_model(prompt)
                    if result["title"]:
                        digest = DailyDigest(
                            digest_date=today,
                            digest_type="ai_picks",
                            user_id=0,
                            title=result["title"],
                            content=result["content"],
                            model_sources=result["sources"],
                        )
                        db.add(digest)
                        await db.commit()
                        logger.info(f"✓ AI选股日报已生成: {result['title'][:30]}")
                    else:
                        logger.warning("AI选股日报: AI生成失败")
                else:
                    logger.warning("AI选股日报: 暂无AI选股数据，跳过")
        except Exception as e:
            logger.error(f"AI选股日报生成失败: {e}")

    logger.info("每日日报自动生成完成")


async def generate_all_weeklies():
    """每周五自动生成所有周报（行业周报 + AI选股周报）"""
    from app.api import (
        _build_weekly_industry_prompt,
        _build_weekly_ai_picks_prompt,
        _generate_digest_with_multi_model,
        _get_week_range,
    )

    week_start, week_end = _get_week_range()
    logger.info(f"开始自动生成周报 ({week_start} ~ {week_end})...")

    async with async_session() as db:
        # 1. 行业周报
        try:
            existing = await db.execute(
                select(WeeklyDigest).where(
                    WeeklyDigest.week_start == week_start,
                    WeeklyDigest.digest_type == "industry",
                    WeeklyDigest.user_id == 0,
                )
            )
            if existing.scalar_one_or_none():
                logger.info("行业周报本周已存在，跳过")
            else:
                prompt = await _build_weekly_industry_prompt(db)
                if prompt:
                    result = await _generate_digest_with_multi_model(prompt)
                    if result["title"]:
                        digest = WeeklyDigest(
                            week_start=week_start,
                            week_end=week_end,
                            digest_type="industry",
                            user_id=0,
                            title=result["title"],
                            content=result["content"],
                            model_sources=result["sources"],
                        )
                        db.add(digest)
                        await db.commit()
                        logger.info(f"✓ 行业周报已生成: {result['title'][:30]}")
                    else:
                        logger.warning("行业周报: AI生成失败")
                else:
                    logger.warning("行业周报: 暂无评级数据，跳过")
        except Exception as e:
            logger.error(f"行业周报生成失败: {e}")

        # 2. AI选股周报
        try:
            existing = await db.execute(
                select(WeeklyDigest).where(
                    WeeklyDigest.week_start == week_start,
                    WeeklyDigest.digest_type == "ai_picks",
                    WeeklyDigest.user_id == 0,
                )
            )
            if existing.scalar_one_or_none():
                logger.info("AI选股周报本周已存在，跳过")
            else:
                prompt = await _build_weekly_ai_picks_prompt(db)
                if prompt:
                    result = await _generate_digest_with_multi_model(prompt)
                    if result["title"]:
                        digest = WeeklyDigest(
                            week_start=week_start,
                            week_end=week_end,
                            digest_type="ai_picks",
                            user_id=0,
                            title=result["title"],
                            content=result["content"],
                            model_sources=result["sources"],
                        )
                        db.add(digest)
                        await db.commit()
                        logger.info(f"✓ AI选股周报已生成: {result['title'][:30]}")
                    else:
                        logger.warning("AI选股周报: AI生成失败")
                else:
                    logger.warning("AI选股周报: 暂无AI选股数据，跳过")
        except Exception as e:
            logger.error(f"AI选股周报生成失败: {e}")

    logger.info("每周周报自动生成完成")


async def init_reits_list():
    """初始化C-REITs清单到数据库"""
    from app.reits_list import UNIQUE_CREITS

    async with async_session() as session:
        existing_count = await session.scalar(select(func.count(REITItem.id)))
        if existing_count and existing_count >= len(UNIQUE_CREITS) * 0.8:
            logger.info(f"C-REITs已初始化({existing_count}只)，跳过")
            return

        added = 0
        for reit in UNIQUE_CREITS:
            result = await session.execute(
                select(REITItem).where(REITItem.code == reit["code"])
            )
            if result.scalar_one_or_none():
                continue
            item = REITItem(
                code=reit["code"],
                name=reit["name"],
                sector=reit["sector"],
                is_active=1,
            )
            session.add(item)
            added += 1

        if added:
            await session.commit()
            logger.info(f"C-REITs清单已初始化: 新增{added}只")
        else:
            logger.info("C-REITs清单无需更新")


async def generate_reit_weekly_picks():
    """每周一自动生成C-REITs推荐"""
    from app.api import _generate_reit_weekly_picks, _update_reit_backtests

    logger.info("开始自动生成C-REITs每周推荐...")
    async with async_session() as db:
        try:
            result = await _generate_reit_weekly_picks(db)
            if result:
                logger.info(f"✓ C-REITs每周推荐已生成")
            else:
                logger.warning("C-REITs每周推荐生成失败")
        except Exception as e:
            logger.error(f"C-REITs每周推荐异常: {e}")

        # 同时更新回测数据
        try:
            await _update_reit_backtests(db)
            logger.info("✓ C-REITs回测数据已更新")
        except Exception as e:
            logger.error(f"C-REITs回测更新异常: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    # 启动
    await init_db()
    await init_stock_list()
    await init_reits_list()
    await init_admin()
    logger.info("数据库初始化完成")

    # 定时任务1: 每周日 1:00 自动刷新地产股数据和评分（一周一次）
    scheduler.add_job(
        refresh_all_data,
        "cron",
        day_of_week="sun",
        hour=1,
        minute=0,
        id="refresh_sun_01",
        replace_existing=True,
    )
    # 定时任务2: 每周日 1:00 自动生成C-REITs每周推荐（与评分同步）
    scheduler.add_job(
        generate_reit_weekly_picks,
        "cron",
        day_of_week="sun",
        hour=1,
        minute=5,
        id="reits_sun_0105",
        replace_existing=True,
    )
    # 定时任务3: 每周日 9:30 自动生成所有日报（评分完成后）
    scheduler.add_job(
        generate_all_digests,
        "cron",
        day_of_week="sun",
        hour=9,
        minute=30,
        id="digest_sun_0930",
        replace_existing=True,
    )
    # 定时任务4: 每周五 17:00 自动生成周报（收盘后汇总全周数据）
    scheduler.add_job(
        generate_all_weeklies,
        "cron",
        day_of_week="fri",
        hour=17,
        minute=0,
        id="weekly_fri_17",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("定时任务已启动: 每周日 1:00 评分+REITs推荐 + 9:30 生成日报 + 每周五 17:00 生成周报")

    # 启动时检查并自动刷新（后台异步执行，不阻塞启动）
    asyncio.create_task(check_and_refresh())

    yield

    # 关闭
    scheduler.shutdown()


app = FastAPI(title="AI Haoxing@东吴地产", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== API Key 鉴权中间件 ==========
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from jose import JWTError, jwt as jose_jwt

# 不需要鉴权的路径前缀白名单
_AUTH_WHITELIST = ("/api/auth/login", "/api/share/", "/health", "/docs", "/openapi.json")


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """对所有 /api/ 请求进行鉴权：需要有效的 JWT Token 或 API Key"""

    async def dispatch(self, request, call_next):
        path = request.url.path

        # 非 /api/ 路径（前端静态文件等）直接放行
        if not path.startswith("/api/"):
            return await call_next(request)

        # 白名单路径直接放行
        for prefix in _AUTH_WHITELIST:
            if path.startswith(prefix):
                return await call_next(request)

        # 检查 Authorization header（JWT Token）
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            try:
                jose_jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
                return await call_next(request)
            except JWTError:
                pass

        # 检查 X-API-Key header
        api_key = request.headers.get("x-api-key", "")
        if API_KEY and api_key == API_KEY:
            return await call_next(request)

        # 都不满足，拒绝访问
        return JSONResponse(
            status_code=401,
            content={"detail": "未授权访问，请提供有效的登录令牌或 API Key"},
        )


if API_KEY:
    app.add_middleware(APIKeyAuthMiddleware)
    logger.info("API Key 鉴权中间件已启用")
else:
    logger.warning("未配置 API_KEY，API 鉴权中间件未启用（所有接口公开访问）")


app.include_router(router)


# 挂载前端静态文件 (生产环境)
import os
frontend_dist = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
