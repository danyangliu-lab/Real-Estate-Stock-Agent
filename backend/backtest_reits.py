"""
C-REITs 策略离线回测脚本

功能：
  - 在历史多个时间点（每月第一个交易日）模拟执行筛选策略
  - 使用纯量化版筛选（不依赖AI模型，适合离线回测）
  - 计算1个月/3个月/6个月收益率
  - 与基准（等权全市场REITs组合）对比
  - 输出详细回测报告

使用方法：
  cd backend
  python backtest_reits.py

注意：需要 iFinD API 可用（用于获取历史行情数据）
"""

import sys
import os
import json
import logging
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

# 确保可以导入 app 模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app import ifind_client
from app.reits_list import UNIQUE_CREITS, REITS_SECTORS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# =====================================================================
# 回测参数配置
# =====================================================================

# 回测时间范围
BACKTEST_START = date(2024, 7, 1)   # 回测起始日
BACKTEST_END = date(2026, 3, 1)     # 回测结束日

# 调仓频率：每月第一个交易日
REBALANCE_FREQ = "monthly"

# 每期推荐数量
TOP_N = 5

# 分红率筛选参数
DIV_MIN = 3.0
DIV_MAX = 10.0
DIV_PREFERRED_MIN = 5.0
DIV_PREFERRED_MAX = 8.0

# 历史行情缓存（避免重复请求）
_price_cache: Dict[str, Any] = {}


# =====================================================================
# 数据获取
# =====================================================================

def fetch_history_cached(code: str, days: int = 730) -> Optional[Any]:
    """带缓存的历史行情获取（回测期间只需获取一次）"""
    if code in _price_cache:
        return _price_cache[code]
    
    logger.info(f"  获取历史行情: {code} (回溯{days}天)")
    df = ifind_client.fetch_reit_history(code, days=days)
    _price_cache[code] = df
    return df


def get_price_on_date(df, target_date: date) -> Optional[float]:
    """获取指定日期（或之后最近交易日）的收盘价"""
    if df is None or df.empty:
        return None
    try:
        rows = df[df["date"] >= target_date]
        if rows.empty:
            return None
        price = rows.iloc[0]["close"]
        return float(price) if price and price > 0 else None
    except Exception:
        return None


def get_actual_trade_date(df, target_date: date) -> Optional[date]:
    """获取指定日期（或之后最近交易日）的实际日期"""
    if df is None or df.empty:
        return None
    try:
        rows = df[df["date"] >= target_date]
        if rows.empty:
            return None
        return rows.iloc[0]["date"]
    except Exception:
        return None


def get_avg_volume(df, as_of_date: date, lookback: int = 10) -> Optional[float]:
    """获取截至某日的近N日日均成交量"""
    if df is None or df.empty:
        return None
    try:
        past = df[df["date"] <= as_of_date].tail(lookback)
        if past.empty:
            return None
        return float(past["volume"].mean())
    except Exception:
        return None


def get_recent_change(df, as_of_date: date, lookback: int = 20) -> Optional[float]:
    """获取截至某日的近N日涨跌幅(%)"""
    if df is None or df.empty:
        return None
    try:
        past = df[df["date"] <= as_of_date].tail(lookback + 1)
        if len(past) < 2:
            return None
        first_close = past.iloc[0]["close"]
        last_close = past.iloc[-1]["close"]
        if first_close and first_close > 0:
            return round((last_close / first_close - 1) * 100, 2)
        return None
    except Exception:
        return None


def check_zero_turnover(df, as_of_date: date, required_days: int = 10) -> bool:
    """检查截至某日的近N个交易日是否全部成交量为0（流动性不足）"""
    if df is None or df.empty:
        return False
    try:
        past = df[df["date"] <= as_of_date].tail(required_days)
        if len(past) < required_days:
            return False
        return (past["volume"] == 0).all()
    except Exception:
        return False


# =====================================================================
# 量化筛选策略（离线版，不依赖AI）
# =====================================================================

def quantitative_screening(
    all_reits: List[Dict],
    as_of_date: date,
    dividend_data: Dict[str, float],
    top_n: int = 5,
) -> Dict[str, Any]:
    """
    纯量化版REITs筛选策略（离线回测用，不调用AI）

    层级：
      1. 分红率筛选 (3-10%)
      2. 剔除连续2周(10交易日)成交量为0的品种
      3. 综合评分排序选出Top N

    综合评分 = 分红率得分(40%) + 流动性得分(25%) + 走势平稳度得分(20%) + 类型多元化(15%)

    Args:
        all_reits: 全部REITs列表
        as_of_date: 筛选截止日
        dividend_data: {code: yield_pct} 分红率数据
        top_n: 推荐数量

    Returns:
        {picks: [{code, name, sector, dividend_yield, score, reason}], filter_log: {...}}
    """
    codes = [r["code"] for r in all_reits]
    name_map = {r["code"]: r["name"] for r in all_reits}
    sector_map = {r["code"]: r["sector"] for r in all_reits}

    filter_log = {"total": len(codes)}

    # ── 第1层：分红率筛选 ──
    passed_div = []
    for code in codes:
        dy = dividend_data.get(code)
        if dy is None:
            passed_div.append(code)  # 无数据的保留
        elif DIV_MIN <= dy <= DIV_MAX:
            passed_div.append(code)
    filter_log["after_dividend"] = len(passed_div)

    # ── 第2层：流动性筛选（剔除连续2周零成交）──
    passed_liq = []
    for code in passed_div:
        df = fetch_history_cached(code)
        if check_zero_turnover(df, as_of_date, required_days=10):
            continue  # 剔除
        passed_liq.append(code)
    filter_log["after_turnover"] = len(passed_liq)

    if not passed_liq:
        return {"picks": [], "filter_log": filter_log}

    # ── 第3层：综合评分排序 ──
    scored = []
    for code in passed_liq:
        df = fetch_history_cached(code)
        dy = dividend_data.get(code, 0) or 0

        # 分红率得分 (0-100): 5-8%区间最优
        if 5.0 <= dy <= 8.0:
            div_score = 100
        elif 4.0 <= dy < 5.0 or 8.0 < dy <= 9.0:
            div_score = 80
        elif 3.0 <= dy < 4.0 or 9.0 < dy <= 10.0:
            div_score = 60
        elif dy > 0:
            div_score = 40  # 有分红但不在理想区间
        else:
            div_score = 30  # 无分红数据

        # 流动性得分 (0-100): 日均成交量越高越好
        avg_vol = get_avg_volume(df, as_of_date, lookback=10)
        if avg_vol and avg_vol > 0:
            # 归一化：超过100万为满分
            liq_score = min(100, avg_vol / 10000)
        else:
            liq_score = 10

        # 走势平稳度得分 (0-100): 近20日涨跌幅越接近0越好（避免暴涨暴跌）
        chg_20d = get_recent_change(df, as_of_date, lookback=20)
        if chg_20d is not None:
            # |涨跌幅| < 3% 最优，> 15% 最差
            abs_chg = abs(chg_20d)
            if abs_chg <= 3:
                stability_score = 100
            elif abs_chg <= 8:
                stability_score = 70
            elif abs_chg <= 15:
                stability_score = 40
            else:
                stability_score = 20
        else:
            stability_score = 50

        # 综合得分
        total = div_score * 0.40 + liq_score * 0.25 + stability_score * 0.20
        # 类型多元化加分在后续处理

        scored.append({
            "code": code,
            "name": name_map.get(code, code),
            "sector": sector_map.get(code, ""),
            "dividend_yield": dy if dy > 0 else None,
            "total_score": total,
            "div_score": div_score,
            "liq_score": liq_score,
            "stability_score": stability_score,
        })

    # 按总分排序
    scored.sort(key=lambda x: x["total_score"], reverse=True)

    # ── 类型多元化约束：确保Top N覆盖至少3种类型 ──
    result = []
    used_sectors = set()

    # 第一轮：每种类型选最高分的1只（确保多元化）
    for s in scored:
        sector = s["sector"]
        if sector not in used_sectors and len(result) < top_n:
            result.append(s)
            used_sectors.add(sector)
        if len(used_sectors) >= min(3, top_n):
            break

    # 第二轮：剩余名额按总分填充
    for s in scored:
        if len(result) >= top_n:
            break
        if s["code"] not in [r["code"] for r in result]:
            result.append(s)

    # 格式化输出
    picks = []
    for i, r in enumerate(result[:top_n]):
        # 最终分数：综合分 + 类型多元化加分(15%)
        sector_diversity = 15 if len(used_sectors) >= 3 else 5
        final_score = round(r["total_score"] + sector_diversity)
        picks.append({
            "code": r["code"],
            "name": r["name"],
            "sector": r["sector"],
            "dividend_yield": r["dividend_yield"],
            "score": min(final_score, 100),
            "reason": f"分红{r['div_score']}/流动{r['liq_score']:.0f}/稳定{r['stability_score']}",
        })

    filter_log["final"] = len(picks)

    return {"picks": picks, "filter_log": filter_log}


# =====================================================================
# 收益率计算
# =====================================================================

def calculate_returns(
    code: str, pick_date: date, hold_days_list: List[int] = None
) -> Dict[str, Optional[float]]:
    """计算单只REITs在多个持有期的收益率

    Args:
        code: REITs代码
        pick_date: 推荐日期
        hold_days_list: 持有天数列表，默认[30, 90, 180]

    Returns:
        {"return_30d": float|None, "return_90d": float|None, "return_180d": float|None}
    """
    if hold_days_list is None:
        hold_days_list = [30, 90, 180]

    df = fetch_history_cached(code)
    result = {}

    if df is None or df.empty:
        for days in hold_days_list:
            result[f"return_{days}d"] = None
        return result

    pick_price = get_price_on_date(df, pick_date)
    if pick_price is None:
        for days in hold_days_list:
            result[f"return_{days}d"] = None
        return result

    today = date.today()

    for days in hold_days_list:
        target_date = pick_date + timedelta(days=days)
        key = f"return_{days}d"
        if target_date <= today:
            target_price = get_price_on_date(df, target_date)
            if target_price:
                result[key] = round((target_price / pick_price - 1) * 100, 2)
            else:
                result[key] = None
        else:
            result[key] = None

    return result


def calculate_benchmark_return(
    all_codes: List[str], pick_date: date, hold_days: int
) -> Optional[float]:
    """计算等权全市场REITs基准收益率

    基准定义：全部可交易REITs等权持有

    Args:
        all_codes: 全部REITs代码
        pick_date: 起始日期
        hold_days: 持有天数

    Returns:
        等权平均收益率(%)
    """
    target_date = pick_date + timedelta(days=hold_days)
    if target_date > date.today():
        return None

    returns = []
    for code in all_codes:
        df = fetch_history_cached(code)
        buy_price = get_price_on_date(df, pick_date)
        sell_price = get_price_on_date(df, target_date)
        if buy_price and sell_price:
            returns.append((sell_price / buy_price - 1) * 100)

    if not returns:
        return None
    return round(sum(returns) / len(returns), 2)


# =====================================================================
# 生成回测时间点
# =====================================================================

def generate_rebalance_dates(
    start: date, end: date, freq: str = "monthly"
) -> List[date]:
    """生成调仓日期序列

    Args:
        start: 起始日期
        end: 结束日期
        freq: "monthly" 或 "biweekly"

    Returns:
        调仓日期列表
    """
    dates = []
    current = start

    if freq == "monthly":
        while current <= end:
            dates.append(current)
            # 下个月1号
            if current.month == 12:
                current = date(current.year + 1, 1, 1)
            else:
                current = date(current.year, current.month + 1, 1)
    elif freq == "biweekly":
        while current <= end:
            dates.append(current)
            current += timedelta(days=14)
    else:
        # 每周一
        while current <= end:
            # 确保是周一
            if current.weekday() != 0:
                current += timedelta(days=(7 - current.weekday()))
            dates.append(current)
            current += timedelta(days=7)

    return [d for d in dates if d <= end]


# =====================================================================
# 主回测流程
# =====================================================================

def run_backtest() -> Dict[str, Any]:
    """运行完整回测

    Returns:
        {
            "periods": [{date, picks, returns_30d, returns_90d, returns_180d, benchmark_30d, ...}],
            "summary": {avg_return_30d, avg_return_90d, avg_return_180d, win_rate_30d, ...},
            "config": {start, end, freq, top_n, reits_count},
        }
    """
    logger.info("=" * 60)
    logger.info("C-REITs 策略回测开始")
    logger.info(f"  回测区间: {BACKTEST_START} ~ {BACKTEST_END}")
    logger.info(f"  调仓频率: {REBALANCE_FREQ}")
    logger.info(f"  推荐数量: Top {TOP_N}")
    logger.info("=" * 60)

    all_reits = UNIQUE_CREITS
    all_codes = [r["code"] for r in all_reits]
    logger.info(f"REITs清单: {len(all_reits)}只")

    # 批量获取所有REITs的历史行情（缓存）
    logger.info("正在获取全部REITs历史行情（首次获取后缓存）...")
    success_count = 0
    for i, r in enumerate(all_reits):
        df = fetch_history_cached(r["code"])
        if df is not None and not df.empty:
            success_count += 1
        if (i + 1) % 10 == 0:
            logger.info(f"  进度: {i+1}/{len(all_reits)}")
    logger.info(f"历史行情获取完成: {success_count}/{len(all_reits)}只有数据")

    # 获取分红率数据（用于筛选）
    logger.info("正在获取分红率数据...")
    dividend_data = ifind_client.fetch_reit_dividend_yield(all_codes) or {}
    logger.info(f"分红率数据: {len(dividend_data)}只有数据")

    # 生成调仓日期
    rebalance_dates = generate_rebalance_dates(BACKTEST_START, BACKTEST_END, REBALANCE_FREQ)
    logger.info(f"调仓日期: {len(rebalance_dates)}期")

    # 逐期回测
    periods = []
    all_returns_30d = []
    all_returns_90d = []
    all_returns_180d = []
    all_excess_30d = []
    all_excess_90d = []
    all_excess_180d = []

    for i, rebal_date in enumerate(rebalance_dates):
        logger.info(f"\n{'─'*40}")
        logger.info(f"第{i+1}期: {rebal_date}")

        # 运行量化筛选
        result = quantitative_screening(all_reits, rebal_date, dividend_data, TOP_N)
        picks = result["picks"]
        filter_log = result["filter_log"]

        if not picks:
            logger.warning(f"  无推荐结果，跳过")
            continue

        logger.info(f"  筛选结果: {filter_log}")
        for p in picks:
            logger.info(f"    {p['code']} {p['name']} | {p['sector']} | 分红率:{p.get('dividend_yield', '?')}% | 分数:{p['score']}")

        # 计算每只推荐REITs的收益率
        period_returns = {"30d": [], "90d": [], "180d": []}
        pick_details = []

        for p in picks:
            ret = calculate_returns(p["code"], rebal_date)
            detail = {
                "code": p["code"],
                "name": p["name"],
                "sector": p["sector"],
                "dividend_yield": p.get("dividend_yield"),
                "score": p["score"],
                "return_30d": ret.get("return_30d"),
                "return_90d": ret.get("return_90d"),
                "return_180d": ret.get("return_180d"),
            }
            pick_details.append(detail)

            if ret.get("return_30d") is not None:
                period_returns["30d"].append(ret["return_30d"])
            if ret.get("return_90d") is not None:
                period_returns["90d"].append(ret["return_90d"])
            if ret.get("return_180d") is not None:
                period_returns["180d"].append(ret["return_180d"])

        # 计算本期组合平均收益
        avg_30d = round(sum(period_returns["30d"]) / len(period_returns["30d"]), 2) if period_returns["30d"] else None
        avg_90d = round(sum(period_returns["90d"]) / len(period_returns["90d"]), 2) if period_returns["90d"] else None
        avg_180d = round(sum(period_returns["180d"]) / len(period_returns["180d"]), 2) if period_returns["180d"] else None

        # 计算基准收益
        bench_30d = calculate_benchmark_return(all_codes, rebal_date, 30)
        bench_90d = calculate_benchmark_return(all_codes, rebal_date, 90)
        bench_180d = calculate_benchmark_return(all_codes, rebal_date, 180)

        # 超额收益
        excess_30d = round(avg_30d - bench_30d, 2) if avg_30d is not None and bench_30d is not None else None
        excess_90d = round(avg_90d - bench_90d, 2) if avg_90d is not None and bench_90d is not None else None
        excess_180d = round(avg_180d - bench_180d, 2) if avg_180d is not None and bench_180d is not None else None

        period_data = {
            "date": str(rebal_date),
            "picks": pick_details,
            "avg_return_30d": avg_30d,
            "avg_return_90d": avg_90d,
            "avg_return_180d": avg_180d,
            "benchmark_30d": bench_30d,
            "benchmark_90d": bench_90d,
            "benchmark_180d": bench_180d,
            "excess_30d": excess_30d,
            "excess_90d": excess_90d,
            "excess_180d": excess_180d,
            "filter_log": filter_log,
        }
        periods.append(period_data)

        # 收集有效数据用于汇总
        if avg_30d is not None:
            all_returns_30d.append(avg_30d)
        if avg_90d is not None:
            all_returns_90d.append(avg_90d)
        if avg_180d is not None:
            all_returns_180d.append(avg_180d)
        if excess_30d is not None:
            all_excess_30d.append(excess_30d)
        if excess_90d is not None:
            all_excess_90d.append(excess_90d)
        if excess_180d is not None:
            all_excess_180d.append(excess_180d)

        logger.info(f"  组合收益: 30d={avg_30d}% | 90d={avg_90d}% | 180d={avg_180d}%")
        logger.info(f"  基准收益: 30d={bench_30d}% | 90d={bench_90d}% | 180d={bench_180d}%")
        if excess_30d is not None:
            logger.info(f"  超额收益: 30d={excess_30d:+.2f}% | 90d={excess_90d}% | 180d={excess_180d}%")

    # ── 汇总统计 ──
    def calc_stats(returns_list):
        if not returns_list:
            return {"avg": None, "median": None, "max": None, "min": None, "win_rate": None, "count": 0}
        sorted_r = sorted(returns_list)
        n = len(sorted_r)
        return {
            "avg": round(sum(sorted_r) / n, 2),
            "median": round(sorted_r[n // 2], 2),
            "max": round(max(sorted_r), 2),
            "min": round(min(sorted_r), 2),
            "win_rate": round(sum(1 for r in sorted_r if r > 0) / n * 100, 1),
            "count": n,
        }

    summary = {
        "return_30d": calc_stats(all_returns_30d),
        "return_90d": calc_stats(all_returns_90d),
        "return_180d": calc_stats(all_returns_180d),
        "excess_30d": calc_stats(all_excess_30d),
        "excess_90d": calc_stats(all_excess_90d),
        "excess_180d": calc_stats(all_excess_180d),
        "total_periods": len(periods),
    }

    config = {
        "start": str(BACKTEST_START),
        "end": str(BACKTEST_END),
        "freq": REBALANCE_FREQ,
        "top_n": TOP_N,
        "reits_count": len(all_reits),
        "data_available": success_count,
        "dividend_data_count": len(dividend_data),
    }

    return {"periods": periods, "summary": summary, "config": config}


# =====================================================================
# 报告生成
# =====================================================================

def print_report(backtest_result: Dict):
    """打印回测报告"""
    summary = backtest_result["summary"]
    config = backtest_result["config"]
    periods = backtest_result["periods"]

    print("\n" + "=" * 70)
    print("           C-REITs 量化筛选策略 — 回测报告")
    print("=" * 70)

    print(f"\n【回测配置】")
    print(f"  回测区间:     {config['start']} ~ {config['end']}")
    print(f"  调仓频率:     {config['freq']}")
    print(f"  每期推荐:     Top {config['top_n']}")
    print(f"  REITs总数:    {config['reits_count']}只 (有行情数据: {config['data_available']}只)")
    print(f"  分红率数据:   {config['dividend_data_count']}只")
    print(f"  回测期数:     {summary['total_periods']}期")

    print(f"\n{'─'*70}")
    print(f"【收益率汇总】\n")
    print(f"{'持有期':<10} {'平均收益':>10} {'中位数':>10} {'最大':>10} {'最小':>10} {'胜率':>10} {'有效期数':>10}")
    print(f"{'─'*70}")

    for label, key in [("1个月", "return_30d"), ("3个月", "return_90d"), ("6个月", "return_180d")]:
        s = summary[key]
        if s["count"] > 0:
            print(f"{label:<10} {s['avg']:>+9.2f}% {s['median']:>+9.2f}% {s['max']:>+9.2f}% {s['min']:>+9.2f}% {s['win_rate']:>9.1f}% {s['count']:>8}期")
        else:
            print(f"{label:<10} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'0':>9}期")

    print(f"\n{'─'*70}")
    print(f"【超额收益（策略 vs 等权全市场基准）】\n")
    print(f"{'持有期':<10} {'平均超额':>10} {'中位数':>10} {'最大':>10} {'最小':>10} {'跑赢率':>10}")
    print(f"{'─'*70}")

    for label, key in [("1个月", "excess_30d"), ("3个月", "excess_90d"), ("6个月", "excess_180d")]:
        s = summary[key]
        if s["count"] > 0:
            print(f"{label:<10} {s['avg']:>+9.2f}% {s['median']:>+9.2f}% {s['max']:>+9.2f}% {s['min']:>+9.2f}% {s['win_rate']:>9.1f}%")
        else:
            print(f"{label:<10} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'N/A':>10} {'N/A':>10}")

    print(f"\n{'─'*70}")
    print(f"【各期明细】\n")

    for p in periods:
        print(f"  {p['date']}:")
        for pick in p["picks"]:
            r30 = f"{pick['return_30d']:+.2f}%" if pick['return_30d'] is not None else "N/A"
            r90 = f"{pick['return_90d']:+.2f}%" if pick['return_90d'] is not None else "N/A"
            r180 = f"{pick['return_180d']:+.2f}%" if pick['return_180d'] is not None else "N/A"
            dy = f"{pick['dividend_yield']:.1f}%" if pick['dividend_yield'] else "?"
            print(f"    {pick['code']} {pick['name']:<20s} | {pick['sector']:<8s} | 分红{dy:<6s} | 30d:{r30:<8s} 90d:{r90:<8s} 180d:{r180}")

        avg30 = f"{p['avg_return_30d']:+.2f}%" if p['avg_return_30d'] is not None else "N/A"
        bench30 = f"{p['benchmark_30d']:+.2f}%" if p['benchmark_30d'] is not None else "N/A"
        excess30 = f"{p['excess_30d']:+.2f}%" if p['excess_30d'] is not None else "N/A"
        print(f"    → 组合30d: {avg30} | 基准30d: {bench30} | 超额30d: {excess30}")
        print()

    print("=" * 70)
    print("  回测说明:")
    print("  - 策略: 纯量化版5层筛选（分红率→流动性→综合评分+类型多元化约束）")
    print("  - 基准: 全部可交易REITs等权组合")
    print("  - 每期调仓买入价: 调仓日收盘价（或最近交易日）")
    print("  - 不含交易成本、冲击成本")
    print("  - 分红率使用当前快照（非历史时点，存在一定前视偏差）")
    print("=" * 70)


def save_report_json(backtest_result: Dict, filepath: str):
    """保存回测结果为JSON"""
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(backtest_result, f, ensure_ascii=False, indent=2)
    logger.info(f"回测结果已保存: {filepath}")


# =====================================================================
# 入口
# =====================================================================

if __name__ == "__main__":
    try:
        result = run_backtest()
        print_report(result)

        # 保存结果
        output_path = os.path.join(os.path.dirname(__file__), "backtest_result.json")
        save_report_json(result, output_path)

        print(f"\n✅ 回测完成，结果已保存到: {output_path}")

    except Exception as e:
        logger.error(f"回测执行失败: {e}", exc_info=True)
        sys.exit(1)
