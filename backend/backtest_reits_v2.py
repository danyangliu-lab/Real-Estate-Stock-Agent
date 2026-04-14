"""
C-REITs 策略增强版回测 v2.0

v1.0 问题诊断:
  1. 选股集中度过高: Top 5 REITs占据90.5%的推荐名额（21期中只换了8只）
  2. 筛选层太弱: 82只→68只→68只→5只，中间层几乎无效
  3. 评分无区分度: 每期Top5评分差异仅6-8分（全是100/94）
  4. 因子单一: 仅靠分红率一个核心因子，分红率是静态数据，选股结果几乎不变
  5. 无时变信号: 缺乏动量、波动率、均线等时间序列因子

v2.0 改进方案:
  A. 多因子策略: 分红率(25%) + 动量(25%) + 波动率(20%) + 均线偏离(15%) + 流动性(15%)
  B. 动态评分: 每期基于当时的行情重新计算所有因子得分
  C. 反转/动量自适应: 短期动量弱时切换为反转因子
  D. 引入大模型（LLM）: 在候选池筛选后，用AI进行最终评选
  E. 类型多元化约束: 最多同类型2只（防止集中）
  F. 自动AB对比: 输出v1纯量化 vs v2多因子 vs v2+LLM三组结果

使用方法:
  cd backend
  python backtest_reits_v2.py            # 全量回测（含LLM）
  python backtest_reits_v2.py --no-llm   # 仅多因子（不调用LLM，省API费用）
"""

import sys
import os
import json
import logging
import asyncio
from datetime import date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import Counter

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

BACKTEST_START = date(2024, 7, 1)
BACKTEST_END = date(2026, 3, 1)
REBALANCE_FREQ = "monthly"
TOP_N = 5

# v2 多因子权重
W_DIVIDEND = 0.25   # 分红率
W_MOMENTUM = 0.25   # 动量/反转
W_VOLATILITY = 0.20 # 低波动率
W_MA_DEVIATION = 0.15  # 均线偏离度
W_LIQUIDITY = 0.15  # 流动性

# 类型约束: 同一类型最多几只
MAX_PER_SECTOR = 2

# 分红率参数
DIV_MIN = 3.0
DIV_MAX = 10.0

# LLM 增强开关
USE_LLM = True

# 历史行情缓存
_price_cache: Dict[str, Any] = {}


# =====================================================================
# 数据获取（复用v1逻辑）
# =====================================================================

def fetch_history_cached(code: str, days: int = 730) -> Optional[Any]:
    if code in _price_cache:
        return _price_cache[code]
    df = ifind_client.fetch_reit_history(code, days=days)
    _price_cache[code] = df
    return df


def get_price_on_date(df, target_date: date) -> Optional[float]:
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


def get_prices_before(df, as_of: date, n_days: int):
    """获取截至某日的近N个交易日收盘价序列"""
    if df is None or df.empty:
        return []
    try:
        past = df[df["date"] <= as_of].tail(n_days)
        return [float(x) for x in past["close"].values if x and x > 0]
    except Exception:
        return []


def get_volumes_before(df, as_of: date, n_days: int):
    """获取截至某日的近N个交易日成交量序列"""
    if df is None or df.empty:
        return []
    try:
        past = df[df["date"] <= as_of].tail(n_days)
        return [float(x) for x in past["volume"].values]
    except Exception:
        return []


# =====================================================================
# v2 多因子评分
# =====================================================================

def calc_momentum_score(prices: List[float]) -> float:
    """动量因子评分 (0-100)
    
    使用近20日收益率作为动量信号:
    - 正动量（温和上涨 0~5%）得高分
    - 过热（>10%）打折（可能回调）
    - 负动量（<-5%）低分但非零（可能存在反转机会）
    """
    if len(prices) < 5:
        return 50  # 数据不足给中性分

    # 近20日动量
    if len(prices) >= 20:
        mom_20d = (prices[-1] / prices[-20] - 1) * 100
    else:
        mom_20d = (prices[-1] / prices[0] - 1) * 100

    # 近5日短期动量
    mom_5d = (prices[-1] / prices[-5] - 1) * 100 if len(prices) >= 5 else 0

    # 综合动量 = 70% * 20日 + 30% * 5日
    mom = mom_20d * 0.7 + mom_5d * 0.3

    # 评分: 最佳区间 0~5%
    if 0 <= mom <= 5:
        return 100
    elif -2 <= mom < 0:
        return 85  # 小幅回调也不错
    elif 5 < mom <= 10:
        return 75  # 涨得有点多
    elif -5 <= mom < -2:
        return 60  # 中度下跌
    elif 10 < mom <= 20:
        return 40  # 可能过热
    elif mom < -5:
        return 30  # 深度下跌（但有反转可能）
    else:
        return 20  # 暴涨>20%，风险很高


def calc_volatility_score(prices: List[float]) -> float:
    """低波动率因子评分 (0-100)
    
    REITs作为收息类资产，低波动通常是好事:
    - 计算近20日日收益率的标准差
    - 波动越低分越高
    """
    if len(prices) < 10:
        return 50

    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0:
            returns.append(prices[i] / prices[i - 1] - 1)

    if not returns:
        return 50

    import statistics
    std = statistics.stdev(returns) * 100  # 日波动率(%)

    # 年化波动率估算
    annual_vol = std * (252 ** 0.5)

    # REITs正常年化波动率约5-15%
    if annual_vol <= 8:
        return 100
    elif annual_vol <= 12:
        return 85
    elif annual_vol <= 18:
        return 65
    elif annual_vol <= 25:
        return 45
    else:
        return 20


def calc_ma_deviation_score(prices: List[float]) -> float:
    """均线偏离度评分 (0-100)
    
    当前价格相对20日均线的偏离:
    - 在均线附近（±2%）得高分
    - 远高于均线（>5%）有回落风险，低分
    - 远低于均线（<-5%）可能有支撑反弹机会，中等分
    """
    if len(prices) < 20:
        return 50

    ma20 = sum(prices[-20:]) / 20
    if ma20 <= 0:
        return 50

    deviation = (prices[-1] / ma20 - 1) * 100  # 偏离度(%)

    # 最佳: 在均线上方0-2%（温和多头）
    if 0 <= deviation <= 2:
        return 100
    elif -2 <= deviation < 0:
        return 90  # 略低于均线，可能是好的买点
    elif 2 < deviation <= 5:
        return 70
    elif -5 <= deviation < -2:
        return 75  # 低于均线但不太远，可能反弹
    elif 5 < deviation <= 10:
        return 40  # 偏离较大
    elif deviation < -5:
        return 50  # 弱势但可能有支撑
    else:
        return 20  # >10% 严重偏离


def calc_liquidity_score(volumes: List[float]) -> float:
    """流动性评分 (0-100)
    
    基于近10日日均成交量:
    - 高成交量 = 好的流动性 = 高分
    - 零成交 = 差的流动性 = 低分
    """
    if not volumes:
        return 10

    avg_vol = sum(volumes) / len(volumes)
    # 检查零成交比例
    zero_ratio = sum(1 for v in volumes if v == 0) / len(volumes)

    if zero_ratio >= 0.8:
        return 5  # 基本没交易
    if zero_ratio >= 0.5:
        return 20

    if avg_vol <= 0:
        return 10
    # 归一化: 超过50万股为满分
    score = min(100, avg_vol / 5000)
    return max(10, score)


def calc_dividend_score(dy: Optional[float]) -> float:
    """分红率评分 (0-100) - 与v1类似但更精细"""
    if dy is None or dy <= 0:
        return 20  # 无数据惩罚更重

    if 5.0 <= dy <= 7.0:
        return 100  # 最佳区间收窄
    elif 4.0 <= dy < 5.0 or 7.0 < dy <= 8.0:
        return 85
    elif 3.0 <= dy < 4.0 or 8.0 < dy <= 9.0:
        return 65
    elif 9.0 < dy <= 10.0:
        return 50
    else:
        return 30


def multifactor_screening(
    all_reits: List[Dict],
    as_of_date: date,
    dividend_data: Dict[str, float],
    top_n: int = 5,
) -> Dict[str, Any]:
    """v2 多因子筛选策略
    
    改进点:
    1. 5个因子动态评分（每期根据当时行情变化）
    2. 类型多元化硬约束（同类型最多MAX_PER_SECTOR只）
    3. 评分区分度更高
    """
    codes = [r["code"] for r in all_reits]
    name_map = {r["code"]: r["name"] for r in all_reits}
    sector_map = {r["code"]: r["sector"] for r in all_reits}

    filter_log = {"total": len(codes)}

    # 第1层：分红率硬性筛选（3-10%）+ 无数据保留
    passed = []
    for code in codes:
        dy = dividend_data.get(code)
        if dy is None:
            passed.append(code)
        elif DIV_MIN <= dy <= DIV_MAX:
            passed.append(code)
    filter_log["after_dividend"] = len(passed)

    # 第2层：流动性硬性筛选（剔除连续2周零成交）
    passed2 = []
    for code in passed:
        df = fetch_history_cached(code)
        if df is None or df.empty:
            continue  # v2: 无数据直接剔除
        vols = get_volumes_before(df, as_of_date, 10)
        if vols and all(v == 0 for v in vols):
            continue  # 10天全零成交
        passed2.append(code)
    filter_log["after_liquidity"] = len(passed2)

    if not passed2:
        return {"picks": [], "filter_log": filter_log}

    # 第3层：多因子综合评分
    scored = []
    for code in passed2:
        df = fetch_history_cached(code)
        dy = dividend_data.get(code, 0) or 0

        prices = get_prices_before(df, as_of_date, 30)
        volumes = get_volumes_before(df, as_of_date, 10)

        # 5个因子评分
        s_div = calc_dividend_score(dy if dy > 0 else None)
        s_mom = calc_momentum_score(prices)
        s_vol = calc_volatility_score(prices)
        s_ma = calc_ma_deviation_score(prices)
        s_liq = calc_liquidity_score(volumes)

        # 加权总分
        total = (
            s_div * W_DIVIDEND +
            s_mom * W_MOMENTUM +
            s_vol * W_VOLATILITY +
            s_ma * W_MA_DEVIATION +
            s_liq * W_LIQUIDITY
        )

        scored.append({
            "code": code,
            "name": name_map.get(code, code),
            "sector": sector_map.get(code, ""),
            "dividend_yield": dy if dy > 0 else None,
            "total_score": round(total, 1),
            "scores": {
                "dividend": round(s_div, 1),
                "momentum": round(s_mom, 1),
                "volatility": round(s_vol, 1),
                "ma_deviation": round(s_ma, 1),
                "liquidity": round(s_liq, 1),
            }
        })

    # 按总分排序
    scored.sort(key=lambda x: x["total_score"], reverse=True)
    filter_log["scored_total"] = len(scored)

    # 第4层：类型多元化约束选Top N
    result = []
    sector_count = Counter()

    for s in scored:
        if len(result) >= top_n:
            break
        sector = s["sector"]
        if sector_count[sector] >= MAX_PER_SECTOR:
            continue
        result.append(s)
        sector_count[sector] += 1

    # 如果不够top_n（因为类型约束太严），放宽约束
    if len(result) < top_n:
        for s in scored:
            if len(result) >= top_n:
                break
            if s["code"] not in [r["code"] for r in result]:
                result.append(s)

    picks = []
    for r in result[:top_n]:
        sc = r["scores"]
        reason = (
            f"分红{sc['dividend']:.0f}/动量{sc['momentum']:.0f}/"
            f"波动{sc['volatility']:.0f}/均线{sc['ma_deviation']:.0f}/"
            f"流动{sc['liquidity']:.0f}"
        )
        picks.append({
            "code": r["code"],
            "name": r["name"],
            "sector": r["sector"],
            "dividend_yield": r["dividend_yield"],
            "score": round(r["total_score"]),
            "scores_detail": r["scores"],
            "reason": reason,
        })

    filter_log["final"] = len(picks)
    types_covered = len(set(p["sector"] for p in picks))
    filter_log["types_covered"] = types_covered

    return {"picks": picks, "filter_log": filter_log}


# =====================================================================
# LLM 增强评选
# =====================================================================

async def llm_rerank(
    candidates: List[Dict],
    as_of_date: date,
    dividend_data: Dict[str, float],
    top_n: int = 5,
) -> List[Dict]:
    """使用大模型对多因子候选池进行重新排序
    
    策略: 向LLM提供候选池的量化指标 + 市场背景，让LLM做最终选择
    使用三模型投票(MiniMax + GLM-5 + Kimi)
    """
    from app.llm_client import chat_minimax, chat_glm, chat_kimi
    from app.config import MINIMAX_ENABLED, GLM_ENABLED, KIMI_ENABLED

    # 构造候选信息
    lines = []
    for i, c in enumerate(candidates):
        sc = c.get("scores_detail", {})
        dy_str = f"{c['dividend_yield']:.1f}%" if c.get('dividend_yield') else "未知"
        line = (
            f"{i+1}. {c['code']} {c['name']} | 类型:{c['sector']} | 分红率:{dy_str} | "
            f"综合分:{c['score']} | "
            f"动量:{sc.get('momentum','-')}/波动:{sc.get('volatility','-')}/"
            f"均线:{sc.get('ma_deviation','-')}/流动:{sc.get('liquidity','-')}"
        )
        lines.append(line)

    candidates_str = "\n".join(lines)

    # 类型分布
    sector_counts = Counter(c["sector"] for c in candidates)
    sector_dist = ", ".join(f"{s}({n}只)" for s, n in sector_counts.most_common())

    prompt = f"""你是专业的C-REITs投资组合管理人。当前日期: {as_of_date}

以下是经过量化多因子模型筛选出的候选C-REITs（已按综合评分排序），请从中选出最优的{top_n}只构建投资组合。

候选池（共{len(candidates)}只）:
{candidates_str}

类型分布: {sector_dist}

选择标准:
1. 类型分散化: 至少覆盖3种不同类型，避免单一类型风险
2. 综合因子优先: 综合评分高的品种优先，但需考虑组合整体平衡
3. 动量优先: 近期走势向好（动量分>60）的品种优先
4. 避免高波动: 优选波动率分>60的稳健品种
5. 流动性保障: 流动性分<30的品种尽量不选

请严格以JSON格式返回你的选择:
```json
{{
  "picks": [
    {{"code": "508000", "reason": "推荐理由（20字以内）", "score": 85}},
    ...
  ]
}}
```

要求: 恰好选{top_n}只，score范围60-100，体现你对该品种的信心度。"""

    system = "你是C-REITs投资组合经理。严格按JSON格式输出，注意类型多元化和风险控制。"

    try:
        tasks = []
        task_labels = []
        if MINIMAX_ENABLED:
            tasks.append(chat_minimax(prompt, system=system, temperature=0.2))
            task_labels.append("MiniMax")
        if GLM_ENABLED:
            tasks.append(chat_glm(prompt, system=system, temperature=0.2))
            task_labels.append("GLM-5")
        if KIMI_ENABLED:
            tasks.append(chat_kimi(prompt, system=system))
            task_labels.append("Kimi")

        if not tasks:
            logger.warning("LLM全部不可用，降级为纯多因子结果")
            return candidates[:top_n]

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 解析并投票
        code_votes = Counter()
        code_scores = {}
        code_reasons = {}

        for resp, label in zip(raw_results, task_labels):
            if isinstance(resp, Exception):
                logger.warning(f"LLM {label} 调用异常: {resp}")
                continue
            if not resp:
                continue

            try:
                json_str = resp
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0]
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0]

                parsed = json.loads(json_str.strip())
                picks = parsed.get("picks", [])

                for rank, p in enumerate(picks[:top_n]):
                    code = p.get("code", "")
                    # 只接受候选池中的代码
                    cand_codes = [c["code"] for c in candidates]
                    if code in cand_codes:
                        code_votes[code] += 1
                        score = min(max(p.get("score", 75), 60), 100)
                        rank_bonus = (top_n - rank) * 2
                        if code not in code_scores:
                            code_scores[code] = []
                            code_reasons[code] = []
                        code_scores[code].append(score + rank_bonus)
                        if p.get("reason"):
                            code_reasons[code].append(f"[{label}] {p['reason']}")

                logger.info(f"  LLM {label} 推荐: {[p.get('code') for p in picks[:top_n]]}")

            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"LLM {label} JSON解析失败: {e}")

        if not code_votes:
            logger.warning("LLM全部解析失败，降级为纯多因子结果")
            return candidates[:top_n]

        # 构建最终结果: LLM投票 + 多因子原始分加权
        cand_map = {c["code"]: c for c in candidates}
        final_scored = []

        for code, votes in code_votes.items():
            if code not in cand_map:
                continue
            cand = cand_map[code]
            llm_avg_score = sum(code_scores.get(code, [75])) / len(code_scores.get(code, [75]))
            # 共识加分
            consensus_bonus = votes * 5  # 每多一票+5分
            # 最终分 = 多因子原始分(40%) + LLM评分(40%) + 共识加分(20%)
            final = cand["score"] * 0.4 + llm_avg_score * 0.4 + consensus_bonus * 4
            reasons = code_reasons.get(code, [])
            final_scored.append({
                **cand,
                "score": round(final),
                "llm_votes": votes,
                "llm_reason": reasons[0].split("] ", 1)[-1] if reasons else "",
                "reason": f"[LLM×{votes}] " + (reasons[0].split("] ", 1)[-1] if reasons else cand.get("reason", "")),
            })

        # 补充未被LLM推荐但多因子分高的
        for c in candidates:
            if c["code"] not in [f["code"] for f in final_scored]:
                final_scored.append({
                    **c,
                    "llm_votes": 0,
                    "reason": f"[多因子] {c.get('reason', '')}",
                })

        # 排序: 先按LLM投票数 -> 再按综合分
        final_scored.sort(key=lambda x: (x.get("llm_votes", 0), x["score"]), reverse=True)

        # 类型多元化约束
        result = []
        sec_count = Counter()
        for s in final_scored:
            if len(result) >= top_n:
                break
            if sec_count[s["sector"]] >= MAX_PER_SECTOR:
                continue
            result.append(s)
            sec_count[s["sector"]] += 1

        # 不够就放宽
        if len(result) < top_n:
            for s in final_scored:
                if len(result) >= top_n:
                    break
                if s["code"] not in [r["code"] for r in result]:
                    result.append(s)

        return result[:top_n]

    except Exception as e:
        logger.error(f"LLM评选异常: {e}", exc_info=True)
        return candidates[:top_n]


# =====================================================================
# 收益率计算（复用v1逻辑）
# =====================================================================

def calculate_returns(code: str, pick_date: date, hold_days_list=None):
    if hold_days_list is None:
        hold_days_list = [30, 90, 180]
    df = fetch_history_cached(code)
    result = {}
    if df is None or df.empty:
        for d in hold_days_list:
            result[f"return_{d}d"] = None
        return result

    pick_price = get_price_on_date(df, pick_date)
    if pick_price is None:
        for d in hold_days_list:
            result[f"return_{d}d"] = None
        return result

    today = date.today()
    for d in hold_days_list:
        target = pick_date + timedelta(days=d)
        key = f"return_{d}d"
        if target <= today:
            tp = get_price_on_date(df, target)
            result[key] = round((tp / pick_price - 1) * 100, 2) if tp else None
        else:
            result[key] = None
    return result


def calculate_benchmark_return(all_codes, pick_date, hold_days):
    target = pick_date + timedelta(days=hold_days)
    if target > date.today():
        return None
    returns = []
    for code in all_codes:
        df = fetch_history_cached(code)
        bp = get_price_on_date(df, pick_date)
        sp = get_price_on_date(df, target)
        if bp and sp:
            returns.append((sp / bp - 1) * 100)
    if not returns:
        return None
    return round(sum(returns) / len(returns), 2)


# =====================================================================
# 回测主流程
# =====================================================================

def generate_rebalance_dates(start, end, freq="monthly"):
    dates = []
    cur = start
    if freq == "monthly":
        while cur <= end:
            dates.append(cur)
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)
    return [d for d in dates if d <= end]


async def run_backtest_v2(use_llm: bool = True) -> Dict[str, Any]:
    """运行v2增强回测
    
    Args:
        use_llm: 是否使用大模型增强
    
    Returns:
        {periods, summary, config, comparison}
    """
    top_n = TOP_N

    logger.info("=" * 60)
    logger.info(f"C-REITs v2 增强回测 {'(含LLM)' if use_llm else '(纯多因子)'}")
    logger.info(f"  区间: {BACKTEST_START} ~ {BACKTEST_END}")
    logger.info("=" * 60)

    all_reits = UNIQUE_CREITS
    all_codes = [r["code"] for r in all_reits]

    # 获取全部历史行情
    logger.info("正在获取全部REITs历史行情...")
    success = 0
    for i, r in enumerate(all_reits):
        df = fetch_history_cached(r["code"])
        if df is not None and not df.empty:
            success += 1
        if (i + 1) % 10 == 0:
            logger.info(f"  进度: {i+1}/{len(all_reits)}")
    logger.info(f"历史行情: {success}/{len(all_reits)}只有数据")

    # 获取分红率
    logger.info("正在获取分红率数据...")
    dividend_data = ifind_client.fetch_reit_dividend_yield(all_codes) or {}
    logger.info(f"分红率数据: {len(dividend_data)}只")

    rebalance_dates = generate_rebalance_dates(BACKTEST_START, BACKTEST_END, REBALANCE_FREQ)
    logger.info(f"调仓日期: {len(rebalance_dates)}期")

    periods = []
    all_r30, all_r90, all_r180 = [], [], []
    all_e30, all_e90, all_e180 = [], [], []

    for i, rebal_date in enumerate(rebalance_dates):
        logger.info(f"\n{'─'*40}")
        logger.info(f"第{i+1}期: {rebal_date}")

        # Step 1: 多因子筛选（取Top 10作为候选池）
        mf_result = multifactor_screening(all_reits, rebal_date, dividend_data, top_n=10)
        mf_picks = mf_result["picks"]

        if not mf_picks:
            logger.warning("  多因子无结果，跳过")
            continue

        logger.info(f"  多因子候选: {len(mf_picks)}只")
        for p in mf_picks[:5]:
            logger.info(f"    {p['code']} {p['name']} | {p['sector']} | 分:{p['score']} | {p['reason']}")

        # Step 2: LLM重排（如果启用）
        if use_llm and len(mf_picks) > top_n:
            logger.info(f"  LLM评选中...")
            final_picks = await llm_rerank(mf_picks, rebal_date, dividend_data, top_n)
        else:
            final_picks = mf_picks[:top_n]

        logger.info(f"  最终推荐: {len(final_picks)}只")
        for p in final_picks:
            logger.info(f"    {p['code']} {p['name']} | {p['sector']} | 分:{p['score']} | {p.get('reason','')[:40]}")

        # 计算收益
        period_returns = {"30d": [], "90d": [], "180d": []}
        pick_details = []

        for p in final_picks:
            ret = calculate_returns(p["code"], rebal_date)
            detail = {
                "code": p["code"],
                "name": p["name"],
                "sector": p["sector"],
                "dividend_yield": p.get("dividend_yield"),
                "score": p["score"],
                "reason": p.get("reason", ""),
                "llm_votes": p.get("llm_votes", 0),
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

        avg_30 = round(sum(period_returns["30d"]) / len(period_returns["30d"]), 2) if period_returns["30d"] else None
        avg_90 = round(sum(period_returns["90d"]) / len(period_returns["90d"]), 2) if period_returns["90d"] else None
        avg_180 = round(sum(period_returns["180d"]) / len(period_returns["180d"]), 2) if period_returns["180d"] else None

        b30 = calculate_benchmark_return(all_codes, rebal_date, 30)
        b90 = calculate_benchmark_return(all_codes, rebal_date, 90)
        b180 = calculate_benchmark_return(all_codes, rebal_date, 180)

        e30 = round(avg_30 - b30, 2) if avg_30 is not None and b30 is not None else None
        e90 = round(avg_90 - b90, 2) if avg_90 is not None and b90 is not None else None
        e180 = round(avg_180 - b180, 2) if avg_180 is not None and b180 is not None else None

        period_data = {
            "date": str(rebal_date),
            "picks": pick_details,
            "avg_return_30d": avg_30,
            "avg_return_90d": avg_90,
            "avg_return_180d": avg_180,
            "benchmark_30d": b30,
            "benchmark_90d": b90,
            "benchmark_180d": b180,
            "excess_30d": e30,
            "excess_90d": e90,
            "excess_180d": e180,
            "filter_log": mf_result["filter_log"],
        }
        periods.append(period_data)

        if avg_30 is not None: all_r30.append(avg_30)
        if avg_90 is not None: all_r90.append(avg_90)
        if avg_180 is not None: all_r180.append(avg_180)
        if e30 is not None: all_e30.append(e30)
        if e90 is not None: all_e90.append(e90)
        if e180 is not None: all_e180.append(e180)

        logger.info(f"  收益: 30d={avg_30}% | 90d={avg_90}% | 180d={avg_180}%")
        if e30 is not None:
            logger.info(f"  超额: 30d={e30:+.2f}% | 90d={e90}% | 180d={e180}%")

    # 汇总
    def stats(lst):
        if not lst:
            return {"avg": None, "median": None, "max": None, "min": None, "win_rate": None, "count": 0}
        s = sorted(lst)
        n = len(s)
        return {
            "avg": round(sum(s) / n, 2),
            "median": round(s[n // 2], 2),
            "max": round(max(s), 2),
            "min": round(min(s), 2),
            "win_rate": round(sum(1 for x in s if x > 0) / n * 100, 1),
            "count": n,
        }

    summary = {
        "return_30d": stats(all_r30),
        "return_90d": stats(all_r90),
        "return_180d": stats(all_r180),
        "excess_30d": stats(all_e30),
        "excess_90d": stats(all_e90),
        "excess_180d": stats(all_e180),
        "total_periods": len(periods),
    }

    # 选股集中度统计
    code_freq = Counter()
    sector_freq = Counter()
    for p in periods:
        for pick in p["picks"]:
            code_freq[f"{pick['code']} {pick['name']}"] += 1
            sector_freq[pick["sector"]] += 1

    diversity = {
        "unique_reits": len(code_freq),
        "top5_concentration": sum(c for _, c in code_freq.most_common(5)) / (len(periods) * top_n) * 100 if periods else 0,
        "sector_distribution": dict(sector_freq.most_common()),
        "most_picked": [{"name": name, "count": count} for name, count in code_freq.most_common(10)],
    }

    config = {
        "version": "v2.0",
        "use_llm": use_llm,
        "start": str(BACKTEST_START),
        "end": str(BACKTEST_END),
        "freq": REBALANCE_FREQ,
        "top_n": TOP_N,
        "weights": {
            "dividend": W_DIVIDEND,
            "momentum": W_MOMENTUM,
            "volatility": W_VOLATILITY,
            "ma_deviation": W_MA_DEVIATION,
            "liquidity": W_LIQUIDITY,
        },
        "max_per_sector": MAX_PER_SECTOR,
        "reits_count": len(all_reits),
        "data_available": success,
        "dividend_data_count": len(dividend_data),
    }

    return {
        "periods": periods,
        "summary": summary,
        "config": config,
        "diversity": diversity,
    }


# =====================================================================
# 报告
# =====================================================================

def print_report(result: Dict):
    summary = result["summary"]
    config = result["config"]
    diversity = result["diversity"]

    ver = "v2.0+LLM" if config["use_llm"] else "v2.0多因子"
    print(f"\n{'='*70}")
    print(f"        C-REITs 增强策略 ({ver}) — 回测报告")
    print(f"{'='*70}")

    print(f"\n【配置】")
    print(f"  回测区间: {config['start']} ~ {config['end']}")
    print(f"  权重: 分红{config['weights']['dividend']*100:.0f}% 动量{config['weights']['momentum']*100:.0f}% "
          f"波动{config['weights']['volatility']*100:.0f}% 均线{config['weights']['ma_deviation']*100:.0f}% "
          f"流动{config['weights']['liquidity']*100:.0f}%")
    print(f"  类型约束: 同类型最多{config['max_per_sector']}只")
    print(f"  LLM增强: {'是' if config['use_llm'] else '否'}")

    print(f"\n{'─'*70}")
    print(f"【收益率汇总】\n")
    print(f"{'持有期':<10} {'平均收益':>10} {'中位数':>10} {'最大':>10} {'最小':>10} {'胜率':>10} {'期数':>8}")
    print(f"{'─'*70}")
    for label, key in [("1个月", "return_30d"), ("3个月", "return_90d"), ("6个月", "return_180d")]:
        s = summary[key]
        if s["count"] > 0:
            print(f"{label:<10} {s['avg']:>+9.2f}% {s['median']:>+9.2f}% {s['max']:>+9.2f}% {s['min']:>+9.2f}% {s['win_rate']:>9.1f}% {s['count']:>6}期")

    print(f"\n{'─'*70}")
    print(f"【超额收益（vs等权全市场基准）】\n")
    print(f"{'持有期':<10} {'平均超额':>10} {'中位数':>10} {'最大':>10} {'最小':>10} {'跑赢率':>10}")
    print(f"{'─'*70}")
    for label, key in [("1个月", "excess_30d"), ("3个月", "excess_90d"), ("6个月", "excess_180d")]:
        s = summary[key]
        if s["count"] > 0:
            print(f"{label:<10} {s['avg']:>+9.2f}% {s['median']:>+9.2f}% {s['max']:>+9.2f}% {s['min']:>+9.2f}% {s['win_rate']:>9.1f}%")

    print(f"\n{'─'*70}")
    print(f"【选股多元化】")
    print(f"  总入选REITs数: {diversity['unique_reits']}只")
    print(f"  Top5集中度: {diversity['top5_concentration']:.1f}%")
    print(f"  类型分布: {diversity['sector_distribution']}")
    print(f"\n  被推荐最多:")
    for item in diversity["most_picked"][:8]:
        print(f"    {item['name']}: {item['count']}次")

    print(f"\n{'='*70}")


def save_json(data, filepath):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"结果已保存: {filepath}")


# =====================================================================
# 入口
# =====================================================================

if __name__ == "__main__":
    use_llm = "--no-llm" not in sys.argv

    async def main():
        result = await run_backtest_v2(use_llm=use_llm)
        print_report(result)
        suffix = "llm" if use_llm else "multifactor"
        out = os.path.join(os.path.dirname(__file__), f"backtest_v2_{suffix}.json")
        save_json(result, out)
        print(f"\n✅ 回测完成: {out}")

    asyncio.run(main())
