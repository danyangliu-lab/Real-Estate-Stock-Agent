"""
API路由 - 包含评级、认证、点评、报告模块
"""

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import aiofiles
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form, Request
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import select, func, desc, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import (
    hash_password, verify_password, create_token,
    get_current_user, require_user, require_admin,
)
from app.config import UPLOAD_DIR
from app.database import get_db
from app.models import Stock, Rating, StockPrice, User, Commentary, Report, Watchlist, PortfolioWeight, DailyDigest, AIPick
from app.news_fetcher import fetch_filtered_news, fetch_stock_news
from app.ifind_client import fetch_recent_announcements, fetch_reports
from app.scheduler import refresh_all_data
from app.schemas import (
    StockOut, RatingOut, PriceOut, DashboardStats, RatingHistoryOut,
    LoginRequest, RegisterRequest, TokenResponse, UserOut,
    CommentaryCreate, CommentaryUpdate, CommentaryOut,
    ReportOut,
    WatchlistAdd, WatchlistOut, WatchlistAnalysisItem,
    PortfolioWeightUpdate, PortfolioWeightOut, PortfolioPerformance, PortfolioDailyReturn,
    DailyDigestOut,
    AIPickItem, AIPicksOut,
)

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

# 确保上传目录存在
os.makedirs(UPLOAD_DIR, exist_ok=True)


# ========== 认证接口 ==========

@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """用户登录"""
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    token = create_token(user.id, user.username, user.is_admin)
    return TokenResponse(
        access_token=token,
        user=UserOut.model_validate(user),
    )


@router.get("/auth/me", response_model=UserOut)
async def get_me(user: User = Depends(require_user)):
    """获取当前用户信息"""
    return UserOut.model_validate(user)


# ========== 用户管理接口（管理员） ==========

MAX_USERS = 100


@router.get("/users", response_model=list[UserOut])
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """获取用户列表（管理员）"""
    result = await db.execute(select(User).order_by(User.id))
    return result.scalars().all()


@router.post("/users", response_model=UserOut)
async def create_user(
    req: RegisterRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建用户（管理员）"""
    total = await db.scalar(select(func.count(User.id)))
    if total and total >= MAX_USERS:
        raise HTTPException(status_code=400, detail=f"用户数量已达上限({MAX_USERS})")
    existing = await db.execute(select(User).where(User.username == req.username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")
    user = User(
        username=req.username,
        hashed_password=hash_password(req.password),
        display_name=req.display_name or req.username,
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{uid}")
async def delete_user(
    uid: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除用户（管理员，不能删除自己）"""
    if uid == admin.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()
    return {"ok": True}


# ========== 管理员操作 ==========

# 用于防止并发重复刷新
import asyncio as _asyncio
_refresh_lock = _asyncio.Lock()
_refresh_running = False


@router.post("/admin/refresh-ratings")
async def admin_refresh_ratings(user: User = Depends(require_admin)):
    """管理员手动触发全体评分刷新（后台异步执行）"""
    global _refresh_running
    if _refresh_running:
        raise HTTPException(status_code=409, detail="评分刷新正在进行中，请稍后再试")

    async def _run_refresh():
        global _refresh_running
        async with _refresh_lock:
            _refresh_running = True
            try:
                logger.info(f"管理员 {user.username} 手动触发全体评分刷新")
                count = await refresh_all_data()
                logger.info(f"管理员手动刷新完成，成功评分 {count} 只股票")
            except Exception as e:
                logger.error(f"管理员手动刷新失败: {e}")
            finally:
                _refresh_running = False

    _asyncio.get_event_loop().create_task(_run_refresh())
    return {"ok": True, "message": "评分刷新已启动，将在后台执行，预计需要数分钟完成"}


@router.get("/admin/refresh-status")
async def admin_refresh_status(user: User = Depends(require_admin)):
    """查询评分刷新是否在进行中"""
    return {"running": _refresh_running}


# ========== 仪表盘和评级接口（保持原有） ==========

@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard(
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """仪表盘统计数据"""
    total = await db.scalar(select(func.count(Stock.id)).where(Stock.is_active == 1))
    latest_date = await db.scalar(
        select(func.max(Rating.date)).where(Rating.model_type == model_type)
    )
    if not latest_date:
        return DashboardStats(
            total_stocks=total or 0, rated_today=0, avg_score=0,
            market_distribution={}, rating_distribution={}
        )
    rated_q = (
        select(Rating)
        .join(Stock, Rating.code == Stock.code)
        .where(Rating.date == latest_date, Rating.model_type == model_type, Stock.is_active == 1)
    )
    result = await db.execute(rated_q)
    ratings = result.scalars().all()
    rated_count = len(ratings)
    avg_score = round(sum(r.total_score for r in ratings) / max(rated_count, 1), 2)
    market_dist = {}
    rating_dist = {}
    ai_success = 0
    quant_only = 0
    latest_time = None
    for r in ratings:
        market_dist[r.market] = market_dist.get(r.market, 0) + 1
        rating_dist[r.rating] = rating_dist.get(r.rating, 0) + 1
        if r.ai_score and r.ai_score > 0:
            ai_success += 1
        else:
            quant_only += 1
        if r.created_at and (latest_time is None or r.created_at > latest_time):
            latest_time = r.created_at
    # 将时间转为北京时间显示（兼容 SQLite UTC 存储和系统时区已设为 Asia/Shanghai 两种情况）
    if latest_time:
        # 如果 latest_time 是 naive datetime，假定为系统本地时间（Docker 已设 TZ=Asia/Shanghai）
        refresh_time_str = latest_time.strftime("%Y-%m-%d %H:%M")
    else:
        refresh_time_str = None
    return DashboardStats(
        total_stocks=total or 0,
        rated_today=rated_count,
        avg_score=avg_score,
        market_distribution=market_dist,
        rating_distribution=rating_dist,
        ai_success_count=ai_success,
        quant_only_count=quant_only,
        refresh_time=refresh_time_str,
    )


@router.get("/news")
async def get_news(
    code: Optional[str] = Query(None),
    name: Optional[str] = Query(None),
    limit: int = Query(5, ge=1, le=20),
):
    """获取房地产行业新闻+公告资讯（AI筛选）
    limit: 返回条数（默认5，可扩展到10）
    """
    import asyncio

    # 行业新闻：经过 AI 筛选的 top N
    industry_news = await fetch_filtered_news(limit)

    # 个股新闻
    stock_news = []
    if code and name:
        stock_news = await asyncio.to_thread(fetch_stock_news, code, name, limit)

    # 个股公告（来自iFinD）
    announcements = []
    if code:
        try:
            market = "A"
            # 从数据库查询股票的市场类型
            # 简单判断：5位数字开头为港股
            if code.startswith("0") and len(code) == 5:
                market = "HK"
            elif not code[0].isdigit():
                market = "US"
            raw = await asyncio.to_thread(
                fetch_recent_announcements, code, market, 60
            )
            if raw:
                for line in raw.split("\n"):
                    line = line.strip()
                    if line.startswith("["):
                        # 格式: [2026-02-20] 标题
                        parts = line.split("]", 1)
                        if len(parts) == 2:
                            date_str = parts[0].lstrip("[").strip()
                            title = parts[1].strip()
                            announcements.append({
                                "title": title,
                                "source": "iFinD公告",
                                "time": date_str,
                                "url": "",
                                "type": "announcement",
                            })
        except Exception:
            pass

    return {
        "industry_news": industry_news[:limit],
        "stock_news": stock_news[:limit],
        "announcements": announcements[:limit],
    }


@router.get("/announcements/{code}")
async def get_stock_announcements(
    code: str,
    days: int = Query(90, ge=1, le=365),
    limit: int = Query(10, ge=1, le=30),
):
    """获取单只股票的近期公告与财报（来自iFinD）"""
    import asyncio

    # 判断市场
    market = "A"
    if code.startswith("0") and len(code) == 5:
        market = "HK"
    elif not code[0].isdigit():
        market = "US"

    # 并发获取：全部公告 + 财报类关键词公告
    all_reports, financial_reports = await asyncio.gather(
        asyncio.to_thread(fetch_reports, [code], market, days),
        asyncio.to_thread(fetch_reports, [code], market, min(days, 365), "903", "年度报告,半年度报告,季度报告,业绩预告,业绩快报"),
    )

    # 财报标题集合（用于标记）
    fin_titles = set()
    if financial_reports:
        for r in financial_reports:
            fin_titles.add(r.get("report_title", ""))

    # 关键公告关键词（高亮重点）
    KEY_WORDS = ["年度报告", "半年度报告", "季度报告", "业绩预告", "业绩快报",
                 "利润分配", "分红", "增持", "减持", "回购", "股权激励",
                 "重大合同", "中标", "收购", "出售", "关联交易", "担保",
                 "评级", "信用", "债券"]

    items = []
    if all_reports:
        for r in all_reports:
            title = r.get("report_title", "")
            if not title:
                continue
            is_financial = title in fin_titles or any(kw in title for kw in ["年度报告", "半年度报告", "季度报告", "业绩预告", "业绩快报"])
            is_key = is_financial or any(kw in title for kw in KEY_WORDS)
            items.append({
                "title": title,
                "date": r.get("report_date", ""),
                "pdf_url": r.get("pdf_url", ""),
                "is_financial": is_financial,
                "is_key": is_key,
            })

    # 重点公告排前面，同等级别按日期倒序
    items.sort(key=lambda x: (not x["is_financial"], not x["is_key"], x["date"]), reverse=False)
    # 修正排序：先财报、再重点、再普通，每组内按日期倒序
    items.sort(key=lambda x: (0 if x["is_financial"] else (1 if x["is_key"] else 2), x["date"]), reverse=False)
    items.sort(key=lambda x: (0 if x["is_financial"] else (1 if x["is_key"] else 2)))
    # 每个类别内按日期倒序
    from itertools import groupby
    sorted_items = []
    for _, group in groupby(items, key=lambda x: (0 if x["is_financial"] else (1 if x["is_key"] else 2))):
        g = sorted(list(group), key=lambda x: x["date"], reverse=True)
        sorted_items.extend(g)

    return sorted_items[:limit]


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
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取最新一期评级"""
    latest_date = await db.scalar(
        select(func.max(Rating.date)).where(Rating.model_type == model_type)
    )
    if not latest_date:
        return []
    q = (
        select(Rating)
        .join(Stock, Rating.code == Stock.code)
        .where(Rating.date == latest_date, Rating.model_type == model_type, Stock.is_active == 1)
    )
    if market:
        q = q.where(Rating.market == market)
    if rating:
        q = q.where(Rating.rating == rating)
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
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取某只股票的历史评级"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating)
        .where(Rating.code == code, Rating.date >= since, Rating.model_type == model_type)
        .order_by(desc(Rating.date))
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/date/{target_date}", response_model=list[RatingOut])
async def get_ratings_by_date(
    target_date: date,
    market: Optional[str] = Query(None),
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取指定日期的评级"""
    q = (
        select(Rating)
        .join(Stock, Rating.code == Stock.code)
        .where(Rating.date == target_date, Rating.model_type == model_type, Stock.is_active == 1)
    )
    if market:
        q = q.where(Rating.market == market)
    q = q.order_by(desc(Rating.total_score))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/ratings/dates", response_model=list[date])
async def get_available_dates(
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取所有有评级数据的日期"""
    q = (
        select(Rating.date)
        .where(Rating.model_type == model_type)
        .distinct()
        .order_by(desc(Rating.date))
        .limit(90)
    )
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
    model_type: str = Query("quant_ai"),
    db: AsyncSession = Depends(get_db),
):
    """获取评分趋势"""
    since = date.today() - timedelta(days=days)
    q = (
        select(Rating.date, Rating.total_score, Rating.rating)
        .where(Rating.code == code, Rating.date >= since, Rating.model_type == model_type)
        .order_by(Rating.date)
    )
    result = await db.execute(q)
    return [
        RatingHistoryOut(date=row[0], total_score=row[1], rating=row[2])
        for row in result.all()
    ]


# ========== 市场点评接口 ==========

@router.get("/commentaries", response_model=list[CommentaryOut])
async def list_commentaries(
    category: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取点评列表（公开）"""
    q = select(Commentary).where(Commentary.is_published == True)
    if category:
        q = q.where(Commentary.category == category)
    q = q.order_by(desc(Commentary.publish_date), desc(Commentary.id)).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/commentaries/{cid}", response_model=CommentaryOut)
async def get_commentary(cid: int, db: AsyncSession = Depends(get_db)):
    """获取单条点评"""
    result = await db.execute(select(Commentary).where(Commentary.id == cid))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="点评不存在")
    return item


@router.post("/commentaries", response_model=CommentaryOut)
async def create_commentary(
    req: CommentaryCreate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """创建点评（管理员）"""
    item = Commentary(
        title=req.title,
        content=req.content,
        category=req.category,
        stock_codes=req.stock_codes or "",
        author=admin.display_name or admin.username,
        publish_date=req.publish_date or date.today(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/commentaries/{cid}", response_model=CommentaryOut)
async def update_commentary(
    cid: int,
    req: CommentaryUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """更新点评（管理员）"""
    result = await db.execute(select(Commentary).where(Commentary.id == cid))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="点评不存在")
    for field, value in req.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/commentaries/{cid}")
async def delete_commentary(
    cid: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除点评（管理员）"""
    await db.execute(delete(Commentary).where(Commentary.id == cid))
    await db.commit()
    return {"ok": True}


# ========== 研究报告接口 ==========

ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@router.get("/reports", response_model=list[ReportOut])
async def list_reports(
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取报告列表（公开）"""
    q = (
        select(Report)
        .where(Report.is_published == True)
        .order_by(desc(Report.publish_date), desc(Report.id))
        .limit(limit)
    )
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/reports", response_model=ReportOut)
async def upload_report(
    title: str = Form(...),
    summary: str = Form(""),
    institution: str = Form(""),
    publish_date: Optional[str] = Form(None),
    file: UploadFile = File(...),
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """上传研究报告（管理员）"""
    # 验证文件类型
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，允许: {', '.join(ALLOWED_EXTENSIONS)}")

    # 读取文件
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="文件大小不能超过50MB")

    # 生成唯一文件名
    stored_name = f"{uuid.uuid4().hex}{ext}"
    filepath = os.path.join(UPLOAD_DIR, stored_name)
    async with aiofiles.open(filepath, "wb") as f:
        await f.write(content)

    p_date = date.today()
    if publish_date:
        try:
            p_date = date.fromisoformat(publish_date)
        except ValueError:
            pass

    report = Report(
        title=title,
        summary=summary,
        institution=institution,
        filename=stored_name,
        original_name=file.filename or "unknown",
        file_size=len(content),
        author=admin.display_name or admin.username,
        publish_date=p_date,
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return report


@router.get("/reports/{rid}/download")
async def download_report(rid: int, db: AsyncSession = Depends(get_db)):
    """下载报告文件"""
    result = await db.execute(select(Report).where(Report.id == rid))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    filepath = os.path.join(UPLOAD_DIR, report.filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    from urllib.parse import quote
    encoded_name = quote(report.original_name, safe='')
    return FileResponse(
        filepath,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_name}",
        },
    )


@router.get("/reports/{rid}/preview")
async def preview_report(rid: int, db: AsyncSession = Depends(get_db)):
    """在线预览报告文件（PDF 以 inline 方式返回）"""
    result = await db.execute(select(Report).where(Report.id == rid))
    report = result.scalar_one_or_none()
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    ext = os.path.splitext(report.filename)[1].lower()
    if ext != ".pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件在线预览")
    filepath = os.path.join(UPLOAD_DIR, report.filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="文件不存在")
    from urllib.parse import quote
    encoded_name = quote(report.original_name, safe='')
    return FileResponse(
        filepath,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded_name}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/reports/{rid}")
async def delete_report(
    rid: int,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """删除报告（管理员）"""
    result = await db.execute(select(Report).where(Report.id == rid))
    report = result.scalar_one_or_none()
    if report:
        filepath = os.path.join(UPLOAD_DIR, report.filename)
        if os.path.exists(filepath):
            os.remove(filepath)
        await db.execute(delete(Report).where(Report.id == rid))
        await db.commit()
    return {"ok": True}


# ========== 自选股票池接口 ==========

MAX_WATCHLIST = 15


@router.get("/watchlist", response_model=list[WatchlistOut])
async def get_watchlist(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户自选股列表"""
    q = select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at)
    result = await db.execute(q)
    return result.scalars().all()


@router.post("/watchlist", response_model=WatchlistOut)
async def add_to_watchlist(
    req: WatchlistAdd,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """添加股票到自选（最多15只）"""
    # 检查数量限制
    count = await db.scalar(
        select(func.count(Watchlist.id)).where(Watchlist.user_id == user.id)
    )
    if count and count >= MAX_WATCHLIST:
        raise HTTPException(status_code=400, detail=f"自选股数量已达上限({MAX_WATCHLIST}只)")

    # 检查是否已在自选中
    existing = await db.execute(
        select(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == req.stock_code,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该股票已在自选中")

    # 验证股票是否在系统中
    stock_result = await db.execute(
        select(Stock).where(Stock.code == req.stock_code, Stock.is_active == 1)
    )
    stock = stock_result.scalar_one_or_none()
    if not stock:
        raise HTTPException(status_code=400, detail="无效的股票代码")

    item = Watchlist(
        user_id=user.id,
        stock_code=stock.code,
        stock_name=stock.name,
        market=stock.market,
        note=req.note or "",
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.put("/watchlist/{stock_code}")
async def update_watchlist_note(
    stock_code: str,
    req: WatchlistAdd,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """更新自选股备注"""
    result = await db.execute(
        select(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == stock_code,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="自选股不存在")
    item.note = req.note or ""
    await db.commit()
    return {"ok": True}


@router.delete("/watchlist/{stock_code}")
async def remove_from_watchlist(
    stock_code: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """从自选中移除股票"""
    await db.execute(
        delete(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.stock_code == stock_code,
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/watchlist/analysis", response_model=list[WatchlistAnalysisItem])
async def get_watchlist_analysis(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取自选股AI操作建议分析

    基于最新评级数据 + 近期趋势，由三模型联合生成操作建议。
    """
    import asyncio
    from app.llm_client import chat_deepseek, chat_glm, chat_kimi
    from app.config import DEEPSEEK_ENABLED, GLM_ENABLED, KIMI_ENABLED

    # 获取用户自选股
    wl_result = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user.id).order_by(Watchlist.added_at)
    )
    watchlist = wl_result.scalars().all()
    if not watchlist:
        return []

    codes = [w.stock_code for w in watchlist]

    # 批量获取最新评级（两个模型）
    latest_ratings = {}
    prev_ratings = {}
    for model_type in ("quant_ai", "soochow"):
        latest_date = await db.scalar(
            select(func.max(Rating.date)).where(Rating.model_type == model_type)
        )
        if latest_date:
            result = await db.execute(
                select(Rating).where(
                    Rating.date == latest_date,
                    Rating.model_type == model_type,
                    Rating.code.in_(codes),
                )
            )
            for r in result.scalars().all():
                key = f"{r.code}_{model_type}"
                latest_ratings[key] = r

            # 获取前一日评级（计算变化）
            prev_date = await db.scalar(
                select(func.max(Rating.date)).where(
                    Rating.model_type == model_type,
                    Rating.date < latest_date,
                )
            )
            if prev_date:
                result = await db.execute(
                    select(Rating).where(
                        Rating.date == prev_date,
                        Rating.model_type == model_type,
                        Rating.code.in_(codes),
                    )
                )
                for r in result.scalars().all():
                    key = f"{r.code}_{model_type}"
                    prev_ratings[key] = r

    # 构建每只股票的摘要，用于AI分析
    stock_summaries = []
    items_base = []
    for w in watchlist:
        qa_key = f"{w.stock_code}_quant_ai"
        sw_key = f"{w.stock_code}_soochow"
        qa = latest_ratings.get(qa_key)
        sw = latest_ratings.get(sw_key)
        best = qa or sw
        prev_qa = prev_ratings.get(qa_key)

        score = best.total_score if best else None
        rating = best.rating if best else None
        prev_score = prev_qa.total_score if prev_qa else None
        score_change = round(score - prev_score, 1) if score is not None and prev_score is not None else None

        items_base.append({
            "stock_code": w.stock_code,
            "stock_name": w.stock_name,
            "market": w.market,
            "latest_rating": rating,
            "latest_score": score,
            "score_change": score_change,
        })

        # 为AI prompt准备
        summary = f"{w.stock_name}({w.stock_code}, {w.market}股)"
        if best:
            summary += f"：综合评分{best.total_score}分，评级「{best.rating}」"
            if best.reason:
                reason_short = best.reason[:200]
                summary += f"，分析：{reason_short}"
        if score_change is not None:
            summary += f"，较前日变化{score_change:+.1f}分"
        stock_summaries.append(summary)

    # 调用AI生成操作建议
    if not stock_summaries:
        return [WatchlistAnalysisItem(**item, suggestion="暂无数据", reason="暂无评级数据") for item in items_base]

    prompt = f"""你是一位专业的房地产行业股票投资顾问。以下是用户自选股票池中{len(stock_summaries)}只股票的最新评级数据：

{"；".join(stock_summaries)}

请对每只股票给出简明的操作建议。要求：
1. 针对每只股票给出明确的操作建议：「买入」「加仓」「持有」「减仓」「观望」「回避」之一
2. 给出1-2句理由（不超过80字）
3. 综合考虑评分趋势变化、当前评级、市场环境

请严格按以下JSON数组格式返回，不要附加其他文字：
[{{"code":"股票代码","suggestion":"操作建议","reason":"理由"}}]"""

    system = "你是房地产行业资深投资顾问，擅长根据量化评级和基本面数据给出操作建议。请直接返回JSON，不要有其他文字。"

    tasks = []
    task_labels = []
    if DEEPSEEK_ENABLED:
        tasks.append(chat_deepseek(prompt, system=system, temperature=0.3))
        task_labels.append("DeepSeek")
    if GLM_ENABLED:
        tasks.append(chat_glm(prompt, system=system, temperature=0.3))
        task_labels.append("GLM-5")
    if KIMI_ENABLED:
        tasks.append(chat_kimi(prompt, system=system))
        task_labels.append("Kimi")

    suggestions_map = {}
    if tasks:
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)
        for resp, label in zip(raw_results, task_labels):
            if isinstance(resp, Exception) or not resp:
                continue
            try:
                # 提取JSON部分
                import re
                json_match = re.search(r'\[.*\]', resp, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    for item in parsed:
                        code = item.get("code", "")
                        if code and code not in suggestions_map:
                            suggestions_map[code] = {
                                "suggestion": item.get("suggestion", "观望"),
                                "reason": item.get("reason", ""),
                                "source": label,
                            }
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"解析{label}自选股建议失败: {e}")

    # 组装结果
    result = []
    for item in items_base:
        sug = suggestions_map.get(item["stock_code"], {})
        result.append(WatchlistAnalysisItem(
            **item,
            suggestion=sug.get("suggestion", "暂无建议"),
            reason=sug.get("reason", "等待AI分析"),
        ))
    return result


# ========== 模拟仓位接口 ==========

@router.get("/portfolio/weights", response_model=list[PortfolioWeightOut])
async def get_portfolio_weights(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取用户模拟仓位配置"""
    q = (
        select(PortfolioWeight, Watchlist.stock_name, Watchlist.market)
        .join(Watchlist, (Watchlist.user_id == PortfolioWeight.user_id) & (Watchlist.stock_code == PortfolioWeight.stock_code))
        .where(PortfolioWeight.user_id == user.id)
    )
    rows = (await db.execute(q)).all()
    return [
        PortfolioWeightOut(stock_code=pw.stock_code, stock_name=name, market=market, weight=pw.weight)
        for pw, name, market in rows
    ]


@router.put("/portfolio/weights")
async def update_portfolio_weights(
    req: PortfolioWeightUpdate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """批量更新模拟仓位（百分比之和须等于100）"""
    total = sum(w.weight for w in req.weights)
    if abs(total - 100) > 0.01 and total > 0:
        raise HTTPException(status_code=400, detail=f"仓位百分比之和须等于100%，当前为{total:.1f}%")

    # 验证股票都在自选中
    wl_result = await db.execute(
        select(Watchlist.stock_code).where(Watchlist.user_id == user.id)
    )
    wl_codes = set(wl_result.scalars().all())
    for w in req.weights:
        if w.stock_code not in wl_codes:
            raise HTTPException(status_code=400, detail=f"{w.stock_code} 不在自选股中")

    # 清除旧配置，写入新配置
    await db.execute(
        delete(PortfolioWeight).where(PortfolioWeight.user_id == user.id)
    )
    for w in req.weights:
        if w.weight > 0:
            db.add(PortfolioWeight(user_id=user.id, stock_code=w.stock_code, weight=w.weight))
    await db.commit()
    return {"ok": True}


@router.get("/portfolio/performance", response_model=PortfolioPerformance)
async def get_portfolio_performance(
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """计算模拟仓位每日收益率"""
    # 获取仓位配置
    q = (
        select(PortfolioWeight, Watchlist.stock_name, Watchlist.market)
        .join(Watchlist, (Watchlist.user_id == PortfolioWeight.user_id) & (Watchlist.stock_code == PortfolioWeight.stock_code))
        .where(PortfolioWeight.user_id == user.id, PortfolioWeight.weight > 0)
    )
    rows = (await db.execute(q)).all()
    if not rows:
        return PortfolioPerformance(weights=[], daily_returns=[], total_return=0)

    weights_out = [
        PortfolioWeightOut(stock_code=pw.stock_code, stock_name=name, market=market, weight=pw.weight)
        for pw, name, market in rows
    ]
    weight_map = {pw.stock_code: pw.weight / 100.0 for pw, _, _ in rows}
    codes = list(weight_map.keys())

    # 获取每只股票近N天的收盘价
    start_date = date.today() - timedelta(days=days + 10)
    price_q = (
        select(StockPrice)
        .where(StockPrice.code.in_(codes), StockPrice.date >= start_date)
        .order_by(StockPrice.date)
    )
    price_rows = (await db.execute(price_q)).scalars().all()

    # 按日期、股票组织价格
    from collections import defaultdict
    price_by_code = defaultdict(list)
    for p in price_rows:
        price_by_code[p.code].append((p.date, p.close))

    # 计算每只股票的每日收益率
    daily_returns_by_code = {}
    for code, prices in price_by_code.items():
        prices.sort(key=lambda x: x[0])
        returns = []
        for i in range(1, len(prices)):
            if prices[i-1][1] and prices[i-1][1] > 0:
                ret = (prices[i][1] - prices[i-1][1]) / prices[i-1][1] * 100
                returns.append((prices[i][0], ret))
        daily_returns_by_code[code] = dict(returns)

    # 汇总所有交易日期
    all_dates = sorted(set(
        d for rets in daily_returns_by_code.values() for d in rets.keys()
    ))
    # 只取最近 days 天
    all_dates = all_dates[-days:] if len(all_dates) > days else all_dates

    # 计算加权组合收益率
    daily_returns = []
    cumulative = 0
    cum_factor = 1.0
    for d in all_dates:
        portfolio_ret = 0
        for code, w in weight_map.items():
            stock_ret = daily_returns_by_code.get(code, {}).get(d, 0)
            portfolio_ret += stock_ret * w
        cum_factor *= (1 + portfolio_ret / 100)
        cumulative = (cum_factor - 1) * 100
        daily_returns.append(PortfolioDailyReturn(
            date=str(d),
            daily_return=round(portfolio_ret, 2),
            cumulative_return=round(cumulative, 2),
        ))

    total_return = round(cumulative, 2)

    # 7日年化收益率：取最近7个交易日的收益率来年化
    annualized = None
    if len(daily_returns) >= 2:
        recent_n = min(7, len(daily_returns))
        recent_factor = 1.0
        for dr in daily_returns[-recent_n:]:
            recent_factor *= (1 + dr.daily_return / 100)
        annualized = round(((recent_factor ** (365 / 7)) - 1) * 100, 2)

    # 最大回撤
    max_drawdown = None
    if daily_returns:
        peak = -999
        mdd = 0
        for dr in daily_returns:
            if dr.cumulative_return > peak:
                peak = dr.cumulative_return
            dd = peak - dr.cumulative_return
            if dd > mdd:
                mdd = dd
        max_drawdown = round(mdd, 2)

    # 获取基准指数数据（沪深300 + 房地产指数）
    try:
        benchmark_data = await _fetch_benchmark_returns(all_dates)
        for dr in daily_returns:
            d_str = dr.date
            if d_str in benchmark_data.get("hs300", {}):
                dr.benchmark_hs300 = benchmark_data["hs300"][d_str]
            if d_str in benchmark_data.get("realestate", {}):
                dr.benchmark_realestate = benchmark_data["realestate"][d_str]
    except Exception as e:
        logger.warning(f"获取基准指数数据失败: {e}")

    return PortfolioPerformance(
        weights=weights_out,
        daily_returns=daily_returns,
        total_return=total_return,
        annualized_return=annualized,
        max_drawdown=max_drawdown,
    )


# ========== 基准指数数据 ==========

import asyncio as _asyncio


def _fetch_index_hist(symbol: str, days: int):
    """直接用指定 symbol（如 sh000300）从腾讯财经获取指数日K线"""
    import requests
    import pandas as pd
    from datetime import datetime, timedelta

    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)
    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?"
        f"param={symbol},day,{start_date.strftime('%Y-%m-%d')},"
        f"{end_date.strftime('%Y-%m-%d')},{days},qfq"
    )
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        kline_data = data.get("data", {}).get(symbol, {})
        day_data = kline_data.get("qfqday") or kline_data.get("day")
        if not day_data:
            return None
        rows = []
        for item in day_data:
            if len(item) >= 5:
                rows.append({"date": item[0], "close": float(item[2])})
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df
    except Exception as e:
        logger.warning(f"腾讯指数 {symbol} 获取失败: {e}")
        return None


async def _fetch_benchmark_returns(dates: list) -> dict:
    """获取沪深300和中证地产指数的累计收益率（与组合同期对比）"""
    import asyncio

    if not dates:
        return {}

    first_date = dates[0]
    days_needed = (date.today() - first_date).days + 20

    # 沪深300: sh000300, 中证地产(399393): sz399393
    hs300_df, re_df = await asyncio.gather(
        asyncio.to_thread(_fetch_index_hist, "sh000300", days_needed),
        asyncio.to_thread(_fetch_index_hist, "sz399393", days_needed),
    )

    result = {"hs300": {}, "realestate": {}}
    date_strs = set(str(d) for d in dates)

    for label, df in [("hs300", hs300_df), ("realestate", re_df)]:
        if df is None or df.empty:
            continue
        df = df.sort_values("date")
        closes = list(zip(df["date"].tolist(), df["close"].tolist()))
        # 找到起始日或之前最近的价格作为基准
        base_price = None
        for d_val, c in closes:
            d_str = str(d_val)
            if d_str >= str(first_date):
                if base_price is None:
                    base_price = c
                break
            base_price = c
        if base_price is None or base_price <= 0:
            continue
        # 实际用第一天之前的收盘价做基准
        prev_price = None
        for d_val, c in closes:
            if str(d_val) >= str(first_date):
                break
            prev_price = c
        if prev_price and prev_price > 0:
            base_price = prev_price

        for d_val, c in closes:
            d_str = str(d_val)
            if d_str in date_strs and c and base_price > 0:
                result[label][d_str] = round((c / base_price - 1) * 100, 2)

    return result


# ========== AI推荐选股接口 ==========

@router.get("/ai-picks")
async def get_ai_picks(
    force: bool = Query(False),
    days: int = Query(default=30, ge=1, le=365),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取AI推荐选股组合（每日缓存）"""
    today = date.today()

    # 查找缓存
    picks_data = None
    if not force:
        cached = await db.execute(
            select(AIPick).where(AIPick.pick_date == today)
        )
        existing = cached.scalar_one_or_none()
        if existing:
            picks_data = json.loads(existing.picks_json)
            model_sources = existing.model_sources

    if picks_data is None:
        # 生成AI选股
        picks_data, model_sources = await _generate_ai_picks(db)
        if not picks_data:
            raise HTTPException(status_code=500, detail="AI选股生成失败，请稍后重试")

        # 保存
        if force:
            await db.execute(delete(AIPick).where(AIPick.pick_date == today))
        pick_record = AIPick(
            pick_date=today,
            picks_json=json.dumps(picks_data, ensure_ascii=False),
            model_sources=model_sources,
        )
        db.add(pick_record)
        await db.commit()

    # 构建返回并计算收益率
    picks_out = []
    weight_map = {}
    for p in picks_data:
        code = p["code"]
        stock_result = await db.execute(
            select(Stock).where(Stock.code == code, Stock.is_active == 1)
        )
        stock = stock_result.scalar_one_or_none()
        name = stock.name if stock else p.get("name", code)
        market = stock.market if stock else p.get("market", "A")
        weight = p.get("weight", 0)

        # 获取评级
        rating_val = None
        score_val = None
        for mt in ("quant_ai", "soochow"):
            latest_date = await db.scalar(
                select(func.max(Rating.date)).where(Rating.model_type == mt)
            )
            if latest_date:
                r = await db.execute(
                    select(Rating).where(Rating.code == code, Rating.date == latest_date, Rating.model_type == mt)
                )
                r_obj = r.scalar_one_or_none()
                if r_obj:
                    rating_val = r_obj.rating
                    score_val = r_obj.total_score
                    break

        picks_out.append(AIPickItem(
            stock_code=code,
            stock_name=name,
            market=market,
            weight=weight,
            rating=rating_val,
            score=score_val,
            reason=p.get("reason", ""),
        ))
        if weight > 0:
            weight_map[code] = weight / 100.0

    # 计算组合收益率
    perf = None
    if weight_map:
        codes = list(weight_map.keys())
        start_date = today - timedelta(days=days + 10)
        price_q = (
            select(StockPrice)
            .where(StockPrice.code.in_(codes), StockPrice.date >= start_date)
            .order_by(StockPrice.date)
        )
        price_rows = (await db.execute(price_q)).scalars().all()
        from collections import defaultdict
        price_by_code = defaultdict(list)
        for p in price_rows:
            price_by_code[p.code].append((p.date, p.close))

        daily_returns_by_code = {}
        for code, prices in price_by_code.items():
            prices.sort(key=lambda x: x[0])
            returns = []
            for i in range(1, len(prices)):
                if prices[i-1][1] and prices[i-1][1] > 0:
                    ret = (prices[i][1] - prices[i-1][1]) / prices[i-1][1] * 100
                    returns.append((prices[i][0], ret))
            daily_returns_by_code[code] = dict(returns)

        all_dates = sorted(set(
            d for rets in daily_returns_by_code.values() for d in rets.keys()
        ))
        all_dates = all_dates[-days:] if len(all_dates) > days else all_dates

        daily_rets = []
        cum_factor = 1.0
        for d in all_dates:
            port_ret = 0
            for code, w in weight_map.items():
                stock_ret = daily_returns_by_code.get(code, {}).get(d, 0)
                port_ret += stock_ret * w
            cum_factor *= (1 + port_ret / 100)
            cumulative = (cum_factor - 1) * 100
            daily_rets.append(PortfolioDailyReturn(
                date=str(d),
                daily_return=round(port_ret, 2),
                cumulative_return=round(cumulative, 2),
            ))

        total_ret = round((cum_factor - 1) * 100, 2)
        ann = None
        if len(daily_rets) >= 2:
            recent_n = min(7, len(daily_rets))
            recent_factor = 1.0
            for dr in daily_rets[-recent_n:]:
                recent_factor *= (1 + dr.daily_return / 100)
            ann = round(((recent_factor ** (365 / 7)) - 1) * 100, 2)
        mdd = 0
        peak = -999
        for dr in daily_rets:
            if dr.cumulative_return > peak:
                peak = dr.cumulative_return
            dd = peak - dr.cumulative_return
            if dd > mdd:
                mdd = dd

        # 基准对比
        try:
            bm = await _fetch_benchmark_returns(all_dates)
            for dr in daily_rets:
                if dr.date in bm.get("hs300", {}):
                    dr.benchmark_hs300 = bm["hs300"][dr.date]
                if dr.date in bm.get("realestate", {}):
                    dr.benchmark_realestate = bm["realestate"][dr.date]
        except Exception:
            pass

        perf = PortfolioPerformance(
            weights=[PortfolioWeightOut(
                stock_code=p.stock_code, stock_name=p.stock_name,
                market=p.market, weight=p.weight
            ) for p in picks_out if p.weight > 0],
            daily_returns=daily_rets,
            total_return=total_ret,
            annualized_return=ann,
            max_drawdown=round(mdd, 2) if mdd > 0 else None,
        )

    return AIPicksOut(
        picks=picks_out,
        generated_date=str(today),
        model_sources=model_sources,
        performance=perf,
    )


async def _generate_ai_picks(db: AsyncSession) -> tuple:
    """AI三模型联合生成推荐选股组合"""
    import asyncio
    import re
    from app.llm_client import chat_deepseek, chat_glm, chat_kimi
    from app.config import DEEPSEEK_ENABLED, GLM_ENABLED, KIMI_ENABLED

    # 获取最新评级数据
    summaries = []
    for model_type in ("quant_ai", "soochow"):
        latest_date = await db.scalar(
            select(func.max(Rating.date)).where(Rating.model_type == model_type)
        )
        if not latest_date:
            continue
        result = await db.execute(
            select(Rating)
            .join(Stock, Rating.code == Stock.code)
            .where(Rating.date == latest_date, Rating.model_type == model_type, Stock.is_active == 1)
            .order_by(desc(Rating.total_score))
        )
        ratings = result.scalars().all()
        top10 = ratings[:10]
        for r in top10:
            summaries.append(
                f"{r.name}({r.code},{r.market}股): {model_type}评分{r.total_score:.1f}/{r.rating}"
                + (f", 理由:{r.reason[:120]}" if r.reason else "")
            )

    if not summaries:
        return None, ""

    prompt = f"""你是一位专业的房地产行业量化投资组合经理。以下是当前评级系统中排名靠前的房地产股票：

{chr(10).join(summaries)}

请从中选出5-8只股票构建一个最优投资组合，并分配仓位权重（百分比之和=100%）。要求：
1. 综合考虑评分、评级、不同市场分散性
2. 优选评级的股票给予更高权重
3. A股、港股适当分散
4. 每只股票给出简短的入选理由（不超过50字）

请严格按以下JSON数组格式返回，不要附加其他文字：
[{{"code":"股票代码","name":"股票名称","market":"A/HK/US","weight":仓位百分比,"reason":"入选理由"}}]"""

    system = "你是房地产行业量化投资组合经理，请直接返回JSON数组，不要有其他文字。"

    tasks = []
    task_labels = []
    if DEEPSEEK_ENABLED:
        tasks.append(chat_deepseek(prompt, system=system, temperature=0.3))
        task_labels.append("DeepSeek")
    if GLM_ENABLED:
        tasks.append(chat_glm(prompt, system=system, temperature=0.3))
        task_labels.append("GLM-5")
    if KIMI_ENABLED:
        tasks.append(chat_kimi(prompt, system=system))
        task_labels.append("Kimi")

    if not tasks:
        return None, ""

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    for resp, label in zip(raw_results, task_labels):
        if isinstance(resp, Exception) or not resp:
            continue
        try:
            json_match = re.search(r'\[.*\]', resp, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if parsed and len(parsed) >= 3:
                    # 验证并规范化权重
                    total_w = sum(p.get("weight", 0) for p in parsed)
                    if total_w > 0:
                        for p in parsed:
                            p["weight"] = round(p.get("weight", 0) / total_w * 100, 1)
                        # 修正最后一个使总和精确为100
                        diff = 100 - sum(p["weight"] for p in parsed)
                        parsed[-1]["weight"] = round(parsed[-1]["weight"] + diff, 1)
                        return parsed, ",".join(task_labels)
        except Exception as e:
            logger.warning(f"解析{label}AI选股失败: {e}")

    return None, ""


# ========== 每日AI日报接口 ==========

async def _build_industry_digest_prompt(db: AsyncSession) -> str:
    """构建行业日报的 prompt，汇总当日评级数据"""
    today = date.today()

    # 获取两个模型最新评级
    summaries = []
    for model_type, label in [("quant_ai", "量化AI"), ("soochow", "东吴地产")]:
        latest_date = await db.scalar(
            select(func.max(Rating.date)).where(Rating.model_type == model_type)
        )
        if not latest_date:
            continue
        result = await db.execute(
            select(Rating)
            .join(Stock, Rating.code == Stock.code)
            .where(Rating.date == latest_date, Rating.model_type == model_type, Stock.is_active == 1)
            .order_by(desc(Rating.total_score))
        )
        ratings = result.scalars().all()
        if not ratings:
            continue

        total = len(ratings)
        avg_score = sum(r.total_score for r in ratings) / total
        dist = {}
        for r in ratings:
            dist[r.rating] = dist.get(r.rating, 0) + 1

        top5 = ratings[:5]
        bottom3 = ratings[-3:]

        summary = f"【{label}模型】评级日期{latest_date}，共{total}只股票，均分{avg_score:.1f}。"
        summary += f"评级分布：" + "、".join(f"{k}{v}只" for k, v in dist.items()) + "。"
        summary += f"Top5：" + "、".join(f"{r.name}({r.total_score:.1f}分/{r.rating})" for r in top5) + "。"
        summary += f"末位：" + "、".join(f"{r.name}({r.total_score:.1f}分/{r.rating})" for r in bottom3) + "。"

        # 找有基本面数据的优选股
        featured = [r for r in ratings if r.rating == "优选" and r.reason][:3]
        if featured:
            summary += "重点优选股分析：" + "；".join(
                f"{r.name}—{r.reason[:150]}" for r in featured
            )
        summaries.append(summary)

    if not summaries:
        return ""

    return f"""你是一位资深房地产行业研究员，请基于以下AI评级系统的最新数据，撰写一份专业的房地产行业每日日报。

评级数据汇总：
{"  ".join(summaries)}

要求：
1. 标题：简明扼要概括今日行情重点（15-25字）
2. 内容分4个部分，使用Markdown格式：
   - **市场总览**：今日房地产板块整体表现、评级分布变化
   - **重点个股**：综合两个模型评级结果，点评表现突出和值得关注的个股（3-5只）
   - **风险提示**：评级下调或谨慎评级的个股及原因
   - **明日展望**：短期趋势判断和操作建议

请严格按以下JSON格式返回，不要附加其他文字：
{{"title": "日报标题", "content": "Markdown格式的日报正文"}}"""


async def _build_watchlist_digest_prompt(
    db: AsyncSession, user_id: int
) -> str:
    """构建自选股日报的 prompt，结合仓位和评级"""
    # 获取用户自选股
    wl_result = await db.execute(
        select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.added_at)
    )
    watchlist = wl_result.scalars().all()
    if not watchlist:
        return ""

    codes = [w.stock_code for w in watchlist]

    # 获取仓位
    pw_result = await db.execute(
        select(PortfolioWeight).where(
            PortfolioWeight.user_id == user_id,
            PortfolioWeight.stock_code.in_(codes),
        )
    )
    weight_map = {pw.stock_code: pw.weight for pw in pw_result.scalars().all()}

    # 获取评级数据
    stock_details = []
    for w in watchlist:
        detail = f"{w.stock_name}({w.stock_code}, {w.market}股)"
        pw = weight_map.get(w.stock_code, 0)
        if pw > 0:
            detail += f"，仓位{pw:.1f}%"
        else:
            detail += "，未配置仓位"

        for model_type, label in [("quant_ai", "量化AI"), ("soochow", "东吴地产")]:
            latest_date = await db.scalar(
                select(func.max(Rating.date)).where(Rating.model_type == model_type)
            )
            if latest_date:
                r_result = await db.execute(
                    select(Rating).where(
                        Rating.code == w.stock_code,
                        Rating.date == latest_date,
                        Rating.model_type == model_type,
                    )
                )
                r = r_result.scalar_one_or_none()
                if r:
                    detail += f"；{label}评分{r.total_score:.1f}/{r.rating}"
                    if r.reason:
                        detail += f"({r.reason[:100]})"
        stock_details.append(detail)

    # 组合收益率简要
    perf_note = ""
    has_weights = any(v > 0 for v in weight_map.values())
    if has_weights:
        from collections import defaultdict
        start_date = date.today() - timedelta(days=40)
        price_q = (
            select(StockPrice)
            .where(StockPrice.code.in_(codes), StockPrice.date >= start_date)
            .order_by(StockPrice.date)
        )
        price_rows = (await db.execute(price_q)).scalars().all()
        price_by_code = defaultdict(list)
        for p in price_rows:
            price_by_code[p.code].append((p.date, p.close))
        daily_rets = defaultdict(dict)
        for code, prices in price_by_code.items():
            prices.sort(key=lambda x: x[0])
            for i in range(1, len(prices)):
                if prices[i-1][1] and prices[i-1][1] > 0:
                    ret = (prices[i][1] - prices[i-1][1]) / prices[i-1][1] * 100
                    daily_rets[code][prices[i][0]] = ret
        all_dates = sorted(set(d for rets in daily_rets.values() for d in rets.keys()))[-30:]
        cum_factor = 1.0
        for d in all_dates:
            port_ret = 0
            for code in codes:
                w_pct = weight_map.get(code, 0) / 100.0
                port_ret += daily_rets.get(code, {}).get(d, 0) * w_pct
            cum_factor *= (1 + port_ret / 100)
        total_ret = (cum_factor - 1) * 100
        perf_note = f"模拟组合近30日累计收益率：{total_ret:+.2f}%。"

    total_weight = sum(weight_map.values())
    weight_status = f"总仓位{total_weight:.1f}%（{'已满配' if abs(total_weight - 100) < 0.01 else '未满配'}）"

    return f"""你是一位专业的房地产股票投资顾问。以下是用户自选股票池（{len(watchlist)}只）的最新情况：

{weight_status}。{perf_note}

各股票详情：
{"；".join(stock_details)}

请基于以上数据，撰写一份个性化的自选股每日综合日报。要求：
1. 标题：简明概括自选组合今日要点（15-25字）
2. 内容分4个部分，使用Markdown格式：
   - **组合概览**：自选股整体表现，仓位配置合理性评估
   - **个股点评**：逐一简评每只自选股的最新评级表现和趋势（每只1-2句话）
   - **仓位建议**：基于最新评级，建议是否调整仓位配置（具体到个股）
   - **风险与机会**：需要关注的风险因素和潜在机会

请严格按以下JSON格式返回，不要附加其他文字：
{{"title": "日报标题", "content": "Markdown格式的日报正文"}}"""


async def _generate_digest_with_multi_model(prompt: str) -> dict:
    """三模型并发生成日报，融合结果"""
    import asyncio
    import re
    from app.llm_client import chat_deepseek, chat_glm, chat_kimi
    from app.config import DEEPSEEK_ENABLED, GLM_ENABLED, KIMI_ENABLED

    system = "你是房地产行业资深研究员，擅长撰写专业的投研日报。请直接返回JSON，不要有其他文字。"

    tasks = []
    task_labels = []
    if DEEPSEEK_ENABLED:
        tasks.append(chat_deepseek(prompt, system=system, temperature=0.4, enable_search=True))
        task_labels.append("DeepSeek")
    if GLM_ENABLED:
        tasks.append(chat_glm(prompt, system=system, temperature=0.4))
        task_labels.append("GLM-5")
    if KIMI_ENABLED:
        tasks.append(chat_kimi(prompt, system=system))
        task_labels.append("Kimi")

    if not tasks:
        return {"title": "", "content": "", "sources": ""}

    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    parsed_results = []
    sources = []
    for resp, label in zip(raw_results, task_labels):
        if isinstance(resp, Exception) or not resp:
            continue
        try:
            json_match = re.search(r'\{.*\}', resp, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if parsed.get("title") and parsed.get("content"):
                    parsed_results.append({"label": label, **parsed})
                    sources.append(label)
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"解析{label}日报失败: {e}")

    if not parsed_results:
        return {"title": "", "content": "", "sources": ""}

    if len(parsed_results) == 1:
        r = parsed_results[0]
        return {"title": r["title"], "content": r["content"], "sources": r["label"]}

    # 多模型融合：取第一个模型的标题，内容融合
    title = parsed_results[0]["title"]
    # 融合策略：取最长的那个作为主体（通常质量更好），附上模型来源
    best = max(parsed_results, key=lambda x: len(x["content"]))
    content = best["content"]
    source_str = ",".join(sources)

    return {"title": title, "content": content, "sources": source_str}





@router.get("/digest/industry", response_model=DailyDigestOut)
async def get_industry_digest(
    force: bool = Query(False),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取/生成行业日报（每日缓存，force=True强制重新生成）"""
    today = date.today()

    # 查找今日缓存
    if not force:
        cached = await db.execute(
            select(DailyDigest).where(
                DailyDigest.digest_date == today,
                DailyDigest.digest_type == "industry",
                DailyDigest.user_id == 0,
            )
        )
        existing = cached.scalar_one_or_none()
        if existing:
            return existing

    # 生成新日报
    prompt = await _build_industry_digest_prompt(db)
    if not prompt:
        raise HTTPException(status_code=404, detail="暂无评级数据，无法生成行业日报")

    result = await _generate_digest_with_multi_model(prompt)
    if not result["title"]:
        raise HTTPException(status_code=500, detail="AI生成日报失败，请稍后重试")

    # 如果 force，删除旧的
    if force:
        await db.execute(
            delete(DailyDigest).where(
                DailyDigest.digest_date == today,
                DailyDigest.digest_type == "industry",
                DailyDigest.user_id == 0,
            )
        )

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
    await db.refresh(digest)
    return digest


@router.get("/digest/watchlist", response_model=DailyDigestOut)
async def get_watchlist_digest(
    force: bool = Query(False),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取/生成自选股日报（每日每用户缓存）"""
    today = date.today()

    if not force:
        cached = await db.execute(
            select(DailyDigest).where(
                DailyDigest.digest_date == today,
                DailyDigest.digest_type == "watchlist",
                DailyDigest.user_id == user.id,
            )
        )
        existing = cached.scalar_one_or_none()
        if existing:
            return existing

    # 检查用户有自选股
    wl_count = await db.scalar(
        select(func.count(Watchlist.id)).where(Watchlist.user_id == user.id)
    )
    if not wl_count:
        raise HTTPException(status_code=404, detail="请先添加自选股")

    prompt = await _build_watchlist_digest_prompt(db, user.id)
    if not prompt:
        raise HTTPException(status_code=404, detail="暂无数据，无法生成日报")

    result = await _generate_digest_with_multi_model(prompt)
    if not result["title"]:
        raise HTTPException(status_code=500, detail="AI生成日报失败，请稍后重试")

    if force:
        await db.execute(
            delete(DailyDigest).where(
                DailyDigest.digest_date == today,
                DailyDigest.digest_type == "watchlist",
                DailyDigest.user_id == user.id,
            )
        )

    digest = DailyDigest(
        digest_date=today,
        digest_type="watchlist",
        user_id=user.id,
        title=result["title"],
        content=result["content"],
        model_sources=result["sources"],
    )
    db.add(digest)
    await db.commit()
    await db.refresh(digest)
    return digest


async def _build_ai_picks_digest_prompt(db: AsyncSession) -> str:
    """构建AI推荐选股日报的 prompt，汇总AI选股组合数据"""
    today = date.today()

    # 获取今日AI选股缓存
    cached = await db.execute(
        select(AIPick).where(AIPick.pick_date == today)
    )
    ai_pick = cached.scalar_one_or_none()
    if not ai_pick:
        return ""

    picks_data = json.loads(ai_pick.picks_json)
    if not picks_data:
        return ""

    # 构建选股详情
    stock_details = []
    for p in picks_data:
        code = p.get("code", "")
        name = p.get("name", "")
        market = p.get("market", "")
        weight = p.get("weight", 0)
        reason = p.get("reason", "")
        detail = f"{name}({code}, {market}股)，建议仓位{weight:.1f}%"
        if reason:
            detail += f"，推荐理由：{reason[:120]}"

        # 获取最新评级
        for model_type, label in [("quant_ai", "量化AI"), ("soochow", "东吴地产")]:
            latest_date = await db.scalar(
                select(func.max(Rating.date)).where(Rating.model_type == model_type)
            )
            if latest_date:
                r_result = await db.execute(
                    select(Rating).where(
                        Rating.code == code,
                        Rating.date == latest_date,
                        Rating.model_type == model_type,
                    )
                )
                r = r_result.scalar_one_or_none()
                if r:
                    detail += f"；{label}评分{r.total_score:.1f}/{r.rating}"
        stock_details.append(detail)

    # 计算组合近30日收益率
    codes = [p.get("code", "") for p in picks_data]
    weight_map = {p.get("code", ""): p.get("weight", 0) for p in picks_data}
    perf_note = ""
    from collections import defaultdict
    start_date = today - timedelta(days=40)
    price_q = (
        select(StockPrice)
        .where(StockPrice.code.in_(codes), StockPrice.date >= start_date)
        .order_by(StockPrice.date)
    )
    price_rows = (await db.execute(price_q)).scalars().all()
    if price_rows:
        price_by_code = defaultdict(list)
        for p in price_rows:
            price_by_code[p.code].append((p.date, p.close))
        daily_rets = defaultdict(dict)
        for code, prices in price_by_code.items():
            prices.sort(key=lambda x: x[0])
            for i in range(1, len(prices)):
                if prices[i-1][1] and prices[i-1][1] > 0:
                    ret = (prices[i][1] - prices[i-1][1]) / prices[i-1][1] * 100
                    daily_rets[code][prices[i][0]] = ret
        all_dates = sorted(set(d for rets in daily_rets.values() for d in rets.keys()))[-30:]
        cum_factor = 1.0
        for d in all_dates:
            port_ret = 0
            for code in codes:
                w_pct = weight_map.get(code, 0) / 100.0
                port_ret += daily_rets.get(code, {}).get(d, 0) * w_pct
            cum_factor *= (1 + port_ret / 100)
        total_ret = (cum_factor - 1) * 100
        perf_note = f"AI推荐组合近30日模拟累计收益率：{total_ret:+.2f}%。"

    return f"""你是一位专业的房地产股票投资顾问。以下是AI智能选股系统（三模型融合：DeepSeek V3.2 + GLM-5 + Kimi K2.5）今日推荐的股票组合（{len(picks_data)}只）：

{perf_note}

各股票详情：
{"；".join(stock_details)}

请基于以上AI推荐组合数据，撰写一份AI推荐选股每日综合日报。要求：
1. 标题：简明概括AI选股组合今日要点（15-25字）
2. 内容分4个部分，使用Markdown格式：
   - **组合概览**：AI选股组合的整体配置策略、行业/市场分布特征
   - **重点推荐解读**：解读仓位最重的2-3只股票的推荐逻辑
   - **组合表现与展望**：收益率分析，近期趋势判断，预期走势
   - **风险提示**：组合主要风险因素和建议关注的事项

请严格按以下JSON格式返回，不要附加其他文字：
{{"title": "日报标题", "content": "Markdown格式的日报正文"}}"""


@router.get("/digest/ai-picks", response_model=DailyDigestOut)
async def get_ai_picks_digest(
    force: bool = Query(False),
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    """获取/生成AI推荐选股日报（每日缓存）"""
    today = date.today()

    if not force:
        cached = await db.execute(
            select(DailyDigest).where(
                DailyDigest.digest_date == today,
                DailyDigest.digest_type == "ai_picks",
                DailyDigest.user_id == 0,
            )
        )
        existing = cached.scalar_one_or_none()
        if existing:
            return existing

    prompt = await _build_ai_picks_digest_prompt(db)
    if not prompt:
        raise HTTPException(status_code=404, detail="暂无AI推荐选股数据，请先生成AI推荐组合")

    result = await _generate_digest_with_multi_model(prompt)
    if not result["title"]:
        raise HTTPException(status_code=500, detail="AI生成日报失败，请稍后重试")

    if force:
        await db.execute(
            delete(DailyDigest).where(
                DailyDigest.digest_date == today,
                DailyDigest.digest_type == "ai_picks",
                DailyDigest.user_id == 0,
            )
        )

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
    await db.refresh(digest)
    return digest


# ========== 公开分享页面（无需登录） ==========

def _share_html(title: str, description: str, content_html: str, meta_extra: str = "", request: Request = None) -> str:
    """生成分享页面 HTML（含 Open Graph meta 标签供微信抓取）"""
    base_url = ""
    if request:
        base_url = f"{request.url.scheme}://{request.headers.get('host', '')}"
    safe_title = title.replace('"', '&quot;').replace('<', '&lt;')
    safe_desc = description[:150].replace('"', '&quot;').replace('<', '&lt;').replace('\n', ' ')
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>{safe_title} - AI Haoxing@东吴地产</title>
<meta property="og:title" content="{safe_title}" />
<meta property="og:description" content="{safe_desc}" />
<meta property="og:type" content="article" />
<meta property="og:site_name" content="AI Haoxing@东吴地产" />
<meta name="description" content="{safe_desc}" />
<meta name="twitter:card" content="summary" />
<meta name="twitter:title" content="{safe_title}" />
<meta name="twitter:description" content="{safe_desc}" />
{meta_extra}
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:#f5f5f5;color:#1a1a1a;line-height:1.6}}
.share-page{{max-width:680px;margin:0 auto;padding:16px}}
.share-header{{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;padding:24px 20px;border-radius:12px 12px 0 0}}
.share-header h1{{font-size:20px;font-weight:600;margin-bottom:8px}}
.share-meta{{font-size:13px;opacity:0.85;display:flex;flex-wrap:wrap;gap:12px}}
.share-meta span{{display:inline-flex;align-items:center;gap:4px}}
.share-body{{background:#fff;padding:24px 20px;border-radius:0 0 12px 12px;box-shadow:0 2px 12px rgba(0,0,0,0.08)}}
.share-body p,.share-body div{{font-size:15px;line-height:1.8;color:#333;white-space:normal;word-break:break-word}}
.share-tag{{display:inline-block;padding:2px 10px;border-radius:12px;font-size:12px;font-weight:500;margin-right:8px}}
.tag-industry{{background:rgba(255,255,255,0.2);color:#fff}}
.tag-stock{{background:rgba(255,255,255,0.2);color:#fff}}
.tag-report{{background:rgba(255,255,255,0.2);color:#fff}}
.share-stocks{{margin-top:16px;padding-top:12px;border-top:1px solid #eee;font-size:13px;color:#666}}
.share-footer{{text-align:center;padding:20px;color:#999;font-size:12px}}
.share-footer a{{color:#667eea;text-decoration:none}}
.share-cta{{display:block;width:100%;max-width:320px;margin:20px auto 0;padding:12px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:500;cursor:pointer;text-align:center;text-decoration:none}}
.share-cta:active{{opacity:0.85}}
.dl-btn{{display:inline-block;padding:10px 32px;background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:500;cursor:pointer;text-decoration:none;margin-top:12px}}
.dl-btn:active{{opacity:0.85}}
</style>
</head>
<body>
<div class="share-page">
{content_html}
<div class="share-footer">
<p>来自 <strong>AI Haoxing@东吴地产</strong></p>
<p style="margin-top:4px">AI评级仅供参考，不构成投资建议</p>
{f'<a href="{base_url}" class="share-cta">打开完整系统 →</a>' if base_url else ''}
</div>
</div>
</body>
</html>"""


@router.get("/share/commentary/{cid}", response_class=HTMLResponse)
async def share_commentary(cid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """市场点评公开分享页面（无需登录）"""
    result = await db.execute(select(Commentary).where(Commentary.id == cid, Commentary.is_published == True))
    item = result.scalar_one_or_none()
    if not item:
        return HTMLResponse("<h1>内容不存在或已下架</h1>", status_code=404)

    tag_cls = "tag-industry" if item.category == "industry" else "tag-stock"
    tag_label = "行业点评" if item.category == "industry" else "个股点评"

    stocks_html = ""
    if item.stock_codes:
        stocks_html = f'<div class="share-stocks">关联股票：{item.stock_codes}</div>'

    content_html = f"""
<div class="share-header">
<h1>{item.title}</h1>
<div class="share-meta">
<span class="share-tag {tag_cls}">{tag_label}</span>
<span>{item.author}</span>
<span>{item.publish_date}</span>
</div>
</div>
<div class="share-body">
<div>{'</div><div style="margin-bottom:12px">'.join(p for p in item.content.split(chr(10)) if p.strip())}</div>
{stocks_html}
</div>"""

    return _share_html(
        title=item.title,
        description=item.content[:150],
        content_html=content_html,
        request=request,
    )


@router.get("/share/report/{rid}", response_class=HTMLResponse)
async def share_report(rid: int, request: Request, db: AsyncSession = Depends(get_db)):
    """研究报告公开分享页面（无需登录）"""
    result = await db.execute(select(Report).where(Report.id == rid, Report.is_published == True))
    report = result.scalar_one_or_none()
    if not report:
        return HTMLResponse("<h1>内容不存在或已下架</h1>", status_code=404)

    import html as html_mod
    safe_title = html_mod.escape(report.title)
    safe_institution = html_mod.escape(report.institution or "")
    safe_author = html_mod.escape(report.author or "")
    safe_summary = html_mod.escape(report.summary or "")
    safe_original_name = html_mod.escape(report.original_name or "")

    file_size_str = f"{report.file_size / (1024*1024):.1f} MB" if report.file_size > 1024*1024 else f"{report.file_size / 1024:.1f} KB"
    download_url = f"/api/reports/{rid}/download"
    preview_url = f"/api/reports/{rid}/preview"
    ext = os.path.splitext(report.filename)[1].lower()

    summary_html = ""
    if safe_summary:
        # 智能分段：双换行一定分段；单换行时，如果上一行以句号等结尾则分段，否则合并（PDF碎片断行）
        import re as _re
        # 先统一换行符
        text = safe_summary.replace('\r\n', '\n').replace('\r', '\n')
        # 双换行替换为占位符保留段落
        text = _re.sub(r'\n{2,}', '\n\n', text)
        lines = text.split('\n')
        paragraphs = []
        current = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                # 空行 = 段落分隔
                if current:
                    paragraphs.append(' '.join(current))
                    current = []
                continue
            current.append(stripped)
            # 如果该行以段落结束标点结尾，视为段落结束
            if _re.search(r'[。！？.!?\u201d"】）)；;：:]$', stripped):
                paragraphs.append(' '.join(current))
                current = []
        if current:
            paragraphs.append(' '.join(current))
        summary_html = ''.join(f"<p style='margin-bottom:12px'>{p}</p>" for p in paragraphs if p)

    # PDF 文件提供 iframe 内嵌预览 + 错误容错
    if ext == ".pdf":
        preview_html = f"""<div style="margin-top:16px">
<iframe src="{preview_url}" style="width:100%;height:70vh;border:1px solid #eee;border-radius:8px" allowfullscreen
  onerror="this.style.display='none';document.getElementById('pdf-fallback').style.display='block'"></iframe>
<div id="pdf-fallback" style="display:none;padding:20px;text-align:center;background:#f8f9fa;border-radius:8px">
<p style="color:#666">PDF预览加载失败，请直接下载查看</p>
</div>
<div style="text-align:center;margin-top:12px">
<a href="{download_url}" class="dl-btn">下载报告</a>
</div>
</div>"""
    else:
        preview_html = f"""<div style="margin-top:16px;padding:16px;background:#f8f9fa;border-radius:8px;text-align:center">
<div style="font-size:36px;margin-bottom:8px">📄</div>
<div style="font-size:14px;color:#666;margin-bottom:4px">{safe_original_name}</div>
<div style="font-size:12px;color:#999">{file_size_str}</div>
<a href="{download_url}" class="dl-btn">下载报告</a>
</div>"""

    content_html = f"""
<div class="share-header">
<h1>{safe_title}</h1>
<div class="share-meta">
<span class="share-tag tag-report">研究报告</span>
{f'<span>{safe_institution}</span>' if safe_institution else ''}
<span>{safe_author}</span>
<span>{report.publish_date}</span>
</div>
</div>
<div class="share-body">
{summary_html}
{preview_html}
</div>"""

    desc = report.summary or f"{report.institution}研究报告：{report.title}"
    return _share_html(
        title=report.title,
        description=desc,
        content_html=content_html,
        request=request,
    )
