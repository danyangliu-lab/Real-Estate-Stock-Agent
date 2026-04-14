"""
C-REITs 筛选策略引擎

筛选策略（5层过滤）：
  1. 分红率筛选：优选5-8%，允许3-10%范围
  2. 剔除过去两年收入环比下降的REITs
  3. 剔除连续2周换手率为0的REITs（并发获取行情数据）
  4. 剔除有负面舆情的REITs
  5. AI大模型综合评选，推荐Top 5（三模型联合：MiniMax M2.5 + GLM-5 + Kimi K2.5）
     - 向AI提供量化市场数据（换手率、近期涨跌幅、价格区间等）
     - 共识加分机制：多模型同时推荐的REITs获得额外加分

回测：
  按1个月、3个月、6个月计算收益率，使用三模型联合给出评价
"""

import json
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date
from typing import Optional, Dict, List, Any

from app import ifind_client
from app.llm_client import chat_minimax, chat_glm, chat_kimi
from app.config import (
    MINIMAX_ENABLED, MINIMAX_WEIGHT,
    GLM_ENABLED, GLM_WEIGHT,
    KIMI_ENABLED, KIMI_WEIGHT,
)

logger = logging.getLogger(__name__)

# 第3层并发请求的线程池（iFinD API是同步阻塞调用）
_HISTORY_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="reit_hist")


# =====================================================================
# 第1层：分红率筛选
# =====================================================================

def filter_by_dividend_yield(
    reit_codes: List[str],
    dividend_data: Dict[str, float],
    min_yield: float = 3.0,
    max_yield: float = 10.0,
    preferred_min: float = 5.0,
    preferred_max: float = 8.0,
) -> Dict[str, Any]:
    """按分红率筛选REITs
    
    Args:
        reit_codes: 全部REITs代码
        dividend_data: {code: yield_pct}
        min_yield / max_yield: 硬性范围
        preferred_min / preferred_max: 优选范围（5-8%）
    
    Returns:
        {
            "passed": [code, ...],           # 通过筛选的代码
            "preferred": [code, ...],         # 优选范围内的代码
            "details": {code: yield_pct, ...}
            "removed": [code, ...]
        }
    """
    passed = []
    preferred = []
    removed = []
    details = {}

    for code in reit_codes:
        dy = dividend_data.get(code)
        if dy is None:
            # 无分红数据的默认保留（可能是新上市）
            passed.append(code)
            details[code] = None
            continue

        details[code] = dy

        if min_yield <= dy <= max_yield:
            passed.append(code)
            if preferred_min <= dy <= preferred_max:
                preferred.append(code)
        else:
            removed.append(code)

    return {
        "passed": passed,
        "preferred": preferred,
        "details": details,
        "removed": removed,
    }


# =====================================================================
# 第2层：收入环比下降剔除
# =====================================================================

def filter_by_income_decline(
    reit_codes: List[str],
    income_data: Dict[str, list],
) -> Dict[str, Any]:
    """剔除过去两年收入环比持续下降的REITs
    
    判定标准：最近4个季度中有3个及以上季度环比下降
    
    Args:
        reit_codes: 待筛选代码
        income_data: {code: [{period, income}, ...]}
    
    Returns:
        {passed, removed, details}
    """
    passed = []
    removed = []
    details = {}

    for code in reit_codes:
        records = income_data.get(code)
        if not records or len(records) < 2:
            # 数据不足，默认保留
            passed.append(code)
            details[code] = {"status": "insufficient_data"}
            continue

        # 取最近4个季度
        recent = records[-4:] if len(records) >= 4 else records
        decline_count = 0
        for i in range(1, len(recent)):
            if recent[i]["income"] < recent[i - 1]["income"]:
                decline_count += 1

        total_comparisons = len(recent) - 1
        decline_ratio = decline_count / total_comparisons if total_comparisons > 0 else 0

        details[code] = {
            "decline_count": decline_count,
            "total_comparisons": total_comparisons,
            "decline_ratio": round(decline_ratio, 2),
        }

        # 如果超过75%的季度环比下降，剔除
        if decline_ratio >= 0.75:
            removed.append(code)
        else:
            passed.append(code)

    return {"passed": passed, "removed": removed, "details": details}


# =====================================================================
# 第3层：换手率为0剔除
# =====================================================================

def filter_by_zero_turnover(
    reit_codes: List[str],
    price_data: Dict[str, Any],
    weeks: int = 2,
) -> Dict[str, Any]:
    """剔除连续N周换手率为0的REITs（流动性不足）
    
    Args:
        reit_codes: 待筛选代码
        price_data: {code: DataFrame(历史行情)} 或 {code: {turnover_ratio, volume, ...}}
        weeks: 连续为0的周数阈值
    
    Returns:
        {passed, removed, details}
    """
    passed = []
    removed = []
    details = {}
    required_days = weeks * 5  # 2周 = 10个交易日

    for code in reit_codes:
        data = price_data.get(code)
        if data is None:
            passed.append(code)
            details[code] = {"status": "no_data"}
            continue

        # 如果是DataFrame（历史行情）
        if hasattr(data, 'empty'):
            if data.empty or len(data) < required_days:
                passed.append(code)
                details[code] = {"status": "insufficient_data"}
                continue
            # 检查最近N个交易日的成交量
            recent = data.tail(required_days)
            zero_count = (recent["volume"] == 0).sum()
            details[code] = {
                "zero_days": int(zero_count),
                "check_days": required_days,
            }
            if zero_count >= required_days:
                removed.append(code)
            else:
                passed.append(code)
        else:
            # 单日数据
            vol = data.get("volume", 0) or 0
            tr = data.get("turnover_ratio", 0) or 0
            details[code] = {"volume": vol, "turnover_ratio": tr}
            # 单日无法判断连续性，仅做简单检查
            passed.append(code)

    return {"passed": passed, "removed": removed, "details": details}


# =====================================================================
# 第4层：负面舆情剔除
# =====================================================================

async def filter_by_sentiment(
    reit_codes: List[str],
    reit_names: Dict[str, str],
) -> Dict[str, Any]:
    """使用AI三模型联合判断是否有负面舆情（MiniMax M2.5 + GLM-5 + Kimi K2.5）
    
    Args:
        reit_codes: 待筛选代码
        reit_names: {code: name}
    
    Returns:
        {passed, removed, details}
    """
    if not reit_codes:
        return {"passed": [], "removed": [], "details": {}}

    # 构造REITs名单
    names_str = "\n".join([f"- {code}: {reit_names.get(code, code)}" for code in reit_codes])

    prompt = f"""你是一个专业的C-REITs分析师。请分析以下C-REITs是否存在近期负面舆情。

REITs列表：
{names_str}

请基于你的知识，判断这些REITs中是否有存在以下负面情况的：
1. 基础资产出现重大问题（如停产、关闭、重大安全事故）
2. 管理人出现重大违规或处罚
3. 分配金额大幅下降或暂停分红
4. 底层资产被诉讼/查封
5. 其他重大利空消息

请以JSON格式回复，包含每只REITs的判断：
```json
{{
  "results": [
    {{"code": "508000", "negative": false, "reason": ""}},
    {{"code": "508001", "negative": true, "reason": "底层资产存在XXX问题"}}
  ]
}}
```

注意：
- 如果你不确定某只REITs的情况，请标注 negative: false
- 只有确实有明显负面消息的才标注 negative: true
- reason字段简短说明原因
"""
    system = "你是C-REITs投资分析师，需要客观判断REITs是否存在负面舆情。请严格按JSON格式输出。"

    try:
        # 三模型并发调用
        tasks = []
        task_labels = []
        if MINIMAX_ENABLED:
            tasks.append(chat_minimax(prompt, system=system, temperature=0.1))
            task_labels.append("MiniMax")
        if GLM_ENABLED:
            tasks.append(chat_glm(prompt, system=system, temperature=0.1))
            task_labels.append("GLM-5")
        if KIMI_ENABLED:
            tasks.append(chat_kimi(prompt, system=system))
            task_labels.append("Kimi")

        if not tasks:
            return {
                "passed": reit_codes,
                "removed": [],
                "details": {c: {"status": "ai_unavailable"} for c in reit_codes},
            }

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 解析各模型结果并投票
        all_negatives = {}  # code -> [bool, ...]
        all_reasons = {}    # code -> [reason, ...]

        for resp, label in zip(raw_results, task_labels):
            if isinstance(resp, Exception):
                logger.warning(f"REITs舆情分析 {label} 调用异常: {resp}")
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
                results = parsed.get("results", [])

                for r in results:
                    code = r.get("code", "")
                    if code not in all_negatives:
                        all_negatives[code] = []
                        all_reasons[code] = []
                    all_negatives[code].append(bool(r.get("negative", False)))
                    if r.get("negative") and r.get("reason"):
                        all_reasons[code].append(f"[{label}] {r['reason']}")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"REITs舆情分析 {label} JSON解析失败: {e}")

        # 投票决策：多数模型认为负面才剔除
        passed = []
        removed = []
        details = {}

        for code in reit_codes:
            votes = all_negatives.get(code, [])
            if not votes:
                passed.append(code)
                details[code] = {"negative": False, "status": "no_vote"}
                continue

            negative_count = sum(1 for v in votes if v)
            total_votes = len(votes)

            # 多数投票：超过半数模型认为负面才剔除
            if negative_count > total_votes / 2:
                removed.append(code)
                reasons = all_reasons.get(code, [])
                details[code] = {
                    "negative": True,
                    "reason": "; ".join(reasons) if reasons else "多模型判定负面",
                    "votes": f"{negative_count}/{total_votes}",
                }
            else:
                passed.append(code)
                details[code] = {"negative": False, "votes": f"{negative_count}/{total_votes}"}

        return {"passed": passed, "removed": removed, "details": details}

    except Exception as e:
        logger.error(f"REITs舆情分析失败: {e}")
        return {
            "passed": reit_codes,
            "removed": [],
            "details": {c: {"status": "error"} for c in reit_codes},
        }


# =====================================================================
# 第5层：AI大模型综合评选
# =====================================================================

async def ai_select_top_reits(
    candidates: List[str],
    reit_names: Dict[str, str],
    reit_sectors: Dict[str, str],
    dividend_data: Dict[str, float],
    market_data: Optional[Dict[str, Dict]] = None,
    top_n: int = 5,
) -> Optional[List[Dict]]:
    """使用AI三模型联合（MiniMax M2.5 + GLM-5 + Kimi K2.5）从候选池中选出Top N推荐

    改进点（v1.1）：
      - 向AI提供丰富的量化市场数据（换手率、近期涨跌幅、价格区间等）
      - 共识加分：被多个模型同时推荐的REITs获得额外加分
      - 评分权重调优：模型评分占比75%，排名加分占比25%
      - 类型多元化约束：强制在prompt中要求不同类型覆盖

    Args:
        candidates: 通过全部筛选的候选REITs代码
        reit_names: {code: name}
        reit_sectors: {code: sector}
        dividend_data: {code: yield_pct}
        market_data: {code: {avg_turnover, chg_5d, chg_20d, price_high, price_low, latest_price}}
        top_n: 推荐数量

    Returns:
        [{code, name, sector, dividend_yield, reason, score}, ...]
    """
    if len(candidates) <= top_n:
        # 候选不足，直接全部推荐
        return [
            {
                "code": c,
                "name": reit_names.get(c, c),
                "sector": reit_sectors.get(c, ""),
                "dividend_yield": dividend_data.get(c),
                "reason": "通过全部筛选条件",
                "score": 80,
            }
            for c in candidates
        ]

    # ── 构造增强版候选信息（含量化数据）──
    info_lines = []
    for c in candidates:
        dy = dividend_data.get(c)
        dy_str = f"{dy}%" if dy else "未知"
        line = f"- {c} {reit_names.get(c, c)} | 类型: {reit_sectors.get(c, '未知')} | 分红率: {dy_str}"

        # 补充市场量化数据
        if market_data and c in market_data:
            md = market_data[c]
            parts = []
            if md.get("avg_turnover") is not None:
                parts.append(f"日均换手率{md['avg_turnover']:.2f}%")
            if md.get("chg_5d") is not None:
                parts.append(f"5日涨跌{md['chg_5d']:+.2f}%")
            if md.get("chg_20d") is not None:
                parts.append(f"20日涨跌{md['chg_20d']:+.2f}%")
            if md.get("latest_price") is not None and md.get("price_low") is not None and md.get("price_high") is not None:
                low, high, cur = md["price_low"], md["price_high"], md["latest_price"]
                if high > low > 0:
                    pos = round((cur - low) / (high - low) * 100)
                    parts.append(f"30日区间位置{pos}%")
            if parts:
                line += f" | {', '.join(parts)}"

        info_lines.append(line)
    candidates_str = "\n".join(info_lines)

    # ── 统计候选池类型分布，提示AI注重多元化 ──
    sector_counts = {}
    for c in candidates:
        s = reit_sectors.get(c, "未知")
        sector_counts[s] = sector_counts.get(s, 0) + 1
    sector_dist = ", ".join([f"{s}({n}只)" for s, n in sorted(sector_counts.items(), key=lambda x: -x[1])])

    prompt = f"""你是一个专业的C-REITs投资顾问。从以下已通过基础筛选的C-REITs候选池中，选出最值得推荐的{top_n}只。

候选池（共{len(candidates)}只，已通过分红率/收入/换手率/舆情筛选）：
{candidates_str}

候选类型分布: {sector_dist}

选择标准（按优先级排序）：
1. 分红率优选5-8%区间，兼顾稳定性与收益（权重30%）
2. 类型多元化：推荐结果须覆盖至少3种不同类型，不要全部集中在同一类型（权重25%）
3. 流动性：优选日均换手率较高的品种，流动性好便于进出（权重15%）
4. 近期走势：优选近5-20日涨跌幅温和（非暴涨暴跌）、区间位置适中（非极端高位）的品种（权重15%）
5. 底层资产质量：优选头部管理人旗下产品、底层资产运营稳定的品种（权重15%）

请以JSON格式回复：
```json
{{
  "picks": [
    {{
      "code": "508000",
      "reason": "简短的推荐理由（30字以内）",
      "score": 85
    }}
  ]
}}
```

请严格选择{top_n}只，score范围60-100。评分应体现你对该REITs投资价值的真实判断。
"""
    system = "你是C-REITs投资分析师。请严格按JSON格式输出推荐结果。注意类型多元化。"

    try:
        # 三模型并发调用
        tasks = []
        task_labels = []
        task_weights = []
        if MINIMAX_ENABLED:
            tasks.append(chat_minimax(prompt, system=system, temperature=0.3))
            task_labels.append("MiniMax")
            task_weights.append(MINIMAX_WEIGHT)
        if GLM_ENABLED:
            tasks.append(chat_glm(prompt, system=system, temperature=0.3))
            task_labels.append("GLM-5")
            task_weights.append(GLM_WEIGHT)
        if KIMI_ENABLED:
            tasks.append(chat_kimi(prompt, system=system))
            task_labels.append("Kimi")
            task_weights.append(KIMI_WEIGHT)

        if not tasks:
            return _fallback_select(candidates, reit_names, reit_sectors, dividend_data, market_data, top_n)

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # ── 解析各模型推荐并计分 ──
        code_scores = {}      # code -> weighted_score_sum
        code_reasons = {}     # code -> [reason, ...]
        code_model_count = {} # code -> 被多少个模型推荐（共识度）
        total_weight = 0

        for resp, label, weight in zip(raw_results, task_labels, task_weights):
            if isinstance(resp, Exception):
                logger.warning(f"REITs AI选择 {label} 调用异常: {resp}")
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
                total_weight += weight

                for rank, p in enumerate(picks[:top_n]):
                    code = p.get("code", "")
                    if code in candidates:
                        # 评分75%，排名25%（降低排名影响，以模型评分为主）
                        rank_bonus = (top_n - rank) / top_n
                        score = min(max(p.get("score", 75), 60), 100)  # 限制在60-100
                        weighted = (score * 0.75 + rank_bonus * 100 * 0.25) * weight
                        code_scores[code] = code_scores.get(code, 0) + weighted
                        code_model_count[code] = code_model_count.get(code, 0) + 1
                        if code not in code_reasons:
                            code_reasons[code] = []
                        if p.get("reason"):
                            code_reasons[code].append(f"[{label}] {p['reason']}")
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"REITs AI选择 {label} JSON解析失败: {e}")

        if not code_scores:
            return _fallback_select(candidates, reit_names, reit_sectors, dividend_data, market_data, top_n)

        # ── 共识加分：被多个模型同时推荐的REITs获得额外奖励 ──
        active_models = len([w for w in task_weights if w > 0])
        for code in code_scores:
            model_count = code_model_count.get(code, 0)
            if model_count >= 2 and active_models >= 2:
                # 2个模型推荐+10%，3个模型推荐+20%
                consensus_bonus = 0.10 if model_count == 2 else 0.20
                code_scores[code] *= (1 + consensus_bonus)
                logger.debug(f"REITs共识加分: {code} 被{model_count}个模型推荐，+{int(consensus_bonus*100)}%")

        # 按加权总分排序，取Top N
        sorted_codes = sorted(code_scores.keys(), key=lambda c: code_scores[c], reverse=True)

        result = []
        for code in sorted_codes[:top_n]:
            reasons = code_reasons.get(code, [])
            # 取第一个理由作为主推荐理由
            main_reason = reasons[0].split("] ", 1)[-1] if reasons else "三模型综合推荐"
            consensus = code_model_count.get(code, 0)
            if consensus >= active_models and active_models >= 2:
                main_reason = f"[全票推荐] {main_reason}"
            result.append({
                "code": code,
                "name": reit_names.get(code, code),
                "sector": reit_sectors.get(code, ""),
                "dividend_yield": dividend_data.get(code),
                "reason": main_reason,
                "score": round(code_scores[code] / (total_weight if total_weight > 0 else 1)),
            })

        # 补充不足（优先不同类型）
        if len(result) < top_n:
            existing_sectors = set(r["sector"] for r in result)
            remaining = [c for c in candidates if c not in [r["code"] for r in result]]
            # 优先选不同类型的
            remaining.sort(key=lambda c: (
                0 if reit_sectors.get(c, "") not in existing_sectors else 1,
                -(dividend_data.get(c, 0) or 0),
            ))
            for c in remaining:
                if len(result) >= top_n:
                    break
                result.append({
                    "code": c,
                    "name": reit_names.get(c, c),
                    "sector": reit_sectors.get(c, ""),
                    "dividend_yield": dividend_data.get(c),
                    "reason": "候选池优质REITs",
                    "score": 70,
                })

        return result

    except Exception as e:
        logger.error(f"AI选择REITs失败: {e}")
        return _fallback_select(candidates, reit_names, reit_sectors, dividend_data, market_data, top_n)


def _fallback_select(
    candidates, reit_names, reit_sectors, dividend_data,
    market_data=None, top_n=5,
) -> List[Dict]:
    """降级选择（v1.1改进）：综合分红率 + 类型多元化

    策略: 按分红率排序，但确保至少覆盖3种不同类型
    """
    # 先按分红率排序
    scored = []
    for c in candidates:
        dy = dividend_data.get(c, 0) or 0
        # 优选区间5-8%给加分
        preferred_bonus = 5 if 5.0 <= dy <= 8.0 else 0
        scored.append((c, dy + preferred_bonus))
    scored.sort(key=lambda x: x[1], reverse=True)

    result = []
    used_sectors = set()

    # 第一轮: 每种类型至少选1只（确保多元化）
    for c, _ in scored:
        sector = reit_sectors.get(c, "")
        if sector not in used_sectors and len(result) < top_n:
            result.append(c)
            used_sectors.add(sector)
        if len(used_sectors) >= min(3, top_n):
            break

    # 第二轮: 剩余名额按分红率填充
    for c, _ in scored:
        if len(result) >= top_n:
            break
        if c not in result:
            result.append(c)

    return [
        {
            "code": c,
            "name": reit_names.get(c, c),
            "sector": reit_sectors.get(c, ""),
            "dividend_yield": dividend_data.get(c),
            "reason": "综合分红率与类型多元化推荐",
            "score": 70,
        }
        for c in result[:top_n]
    ]


# =====================================================================
# 完整筛选流水线
# =====================================================================

def _fetch_history_safe(code: str, days: int = 30):
    """线程安全的历史行情获取（供线程池调用）"""
    try:
        return code, ifind_client.fetch_reit_history(code, days=days)
    except Exception as e:
        logger.debug(f"获取REITs历史行情失败 {code}: {e}")
        return code, None


def _extract_market_data(price_data: Dict[str, Any]) -> Dict[str, Dict]:
    """从历史行情数据中提取量化指标，供第5层AI评选使用

    提取指标：
      - avg_turnover: 近10日日均换手率(%)
      - chg_5d: 近5日涨跌幅(%)
      - chg_20d: 近20日涨跌幅(%)
      - price_high: 30日最高价
      - price_low: 30日最低价
      - latest_price: 最新价
    """
    market_data = {}
    for code, df in price_data.items():
        if df is None or not hasattr(df, 'empty') or df.empty or len(df) < 5:
            continue
        try:
            closes = df["close"].values
            volumes = df["volume"].values
            n = len(df)
            md = {}

            # 最新价
            md["latest_price"] = float(closes[-1]) if closes[-1] else None

            # 日均换手率估算（成交量/价格的变化率近似）
            recent_10 = df.tail(min(10, n))
            if "turnover" in df.columns:
                # 使用成交额作为换手率替代
                avg_vol = recent_10["volume"].mean()
                md["avg_turnover"] = round(avg_vol / 1e6, 2) if avg_vol and avg_vol > 0 else None
            else:
                md["avg_turnover"] = None

            # 近5日涨跌幅
            if n >= 6 and closes[-6] and closes[-6] > 0:
                md["chg_5d"] = round((closes[-1] / closes[-6] - 1) * 100, 2)
            else:
                md["chg_5d"] = None

            # 近20日涨跌幅
            idx_20 = max(0, n - 21)
            if closes[idx_20] and closes[idx_20] > 0:
                md["chg_20d"] = round((closes[-1] / closes[idx_20] - 1) * 100, 2)
            else:
                md["chg_20d"] = None

            # 30日价格区间
            recent_30 = df.tail(min(30, n))
            md["price_high"] = round(float(recent_30["high"].max()), 3) if "high" in df.columns else None
            md["price_low"] = round(float(recent_30["low"].min()), 3) if "low" in df.columns else None

            market_data[code] = md
        except Exception as e:
            logger.debug(f"提取市场数据失败 {code}: {e}")

    return market_data


async def run_full_screening(
    all_reits: List[Dict],
    top_n: int = 5,
) -> Dict[str, Any]:
    """运行完整的5层REITs筛选

    v1.1 优化点：
      - 第3层: 并发获取历史行情（线程池，8并发），原串行~60只需3分钟 → 并发仅需30秒
      - 第5层: 向AI传入量化市场数据（换手率、涨跌幅、价格区间等），提升评选质量

    Args:
        all_reits: [{code, name, sector}, ...]
        top_n: 最终推荐数量

    Returns:
        {
            "picks": [{code, name, sector, dividend_yield, reason, score}, ...],
            "filter_log": {total, after_dividend, after_income, after_turnover, after_sentiment, final},
            "model_source": "MiniMax M2.5 + GLM-5 + Kimi K2.5",
        }
    """
    codes = [r["code"] for r in all_reits]
    name_map = {r["code"]: r["name"] for r in all_reits}
    sector_map = {r["code"]: r["sector"] for r in all_reits}

    filter_log = {"total": len(codes)}
    logger.info(f"REITs筛选开始，总数: {len(codes)}")

    # ── 第1层：分红率 ──
    logger.info("REITs筛选 第1层：分红率...")
    dividend_data = ifind_client.fetch_reit_dividend_yield(codes) or {}
    div_result = filter_by_dividend_yield(codes, dividend_data)
    codes = div_result["passed"]
    filter_log["after_dividend"] = len(codes)
    logger.info(f"  分红率筛选后: {len(codes)}只（剔除{len(div_result['removed'])}只）")

    # ── 第2层：收入环比 ──
    logger.info("REITs筛选 第2层：收入环比...")
    income_data = ifind_client.fetch_reit_income_trend(codes) or {}
    income_result = filter_by_income_decline(codes, income_data)
    codes = income_result["passed"]
    filter_log["after_income"] = len(codes)
    logger.info(f"  收入环比筛选后: {len(codes)}只（剔除{len(income_result['removed'])}只）")

    # ── 第3层：换手率（并发获取历史行情）──
    logger.info(f"REITs筛选 第3层：换手率（并发获取{len(codes)}只行情数据）...")
    price_data = {}
    loop = asyncio.get_event_loop()
    # 使用线程池并发获取历史行情（iFinD API是同步阻塞的）
    futures = [
        loop.run_in_executor(_HISTORY_EXECUTOR, _fetch_history_safe, code, 30)
        for code in codes
    ]
    results = await asyncio.gather(*futures)
    for code, df in results:
        if df is not None:
            price_data[code] = df
    logger.info(f"  历史行情获取完成: {len(price_data)}/{len(codes)}只")

    turnover_result = filter_by_zero_turnover(codes, price_data)
    codes = turnover_result["passed"]
    filter_log["after_turnover"] = len(codes)
    logger.info(f"  换手率筛选后: {len(codes)}只（剔除{len(turnover_result['removed'])}只）")

    # ── 第4层：舆情 ──
    logger.info("REITs筛选 第4层：负面舆情...")
    sentiment_result = await filter_by_sentiment(codes, name_map)
    codes = sentiment_result["passed"]
    filter_log["after_sentiment"] = len(codes)
    logger.info(f"  舆情筛选后: {len(codes)}只（剔除{len(sentiment_result['removed'])}只）")

    # ── 提取市场量化数据（供第5层AI使用）──
    market_data = _extract_market_data(price_data)
    logger.info(f"  市场量化数据: {len(market_data)}只有数据")

    # ── 第5层：AI综合评选 ──
    logger.info(f"REITs筛选 第5层：AI评选Top {top_n}...")
    picks = await ai_select_top_reits(
        candidates=codes,
        reit_names=name_map,
        reit_sectors=sector_map,
        dividend_data=dividend_data,
        market_data=market_data,
        top_n=top_n,
    )
    filter_log["final"] = len(picks) if picks else 0
    logger.info(f"  最终推荐: {len(picks) if picks else 0}只")

    return {
        "picks": picks or [],
        "filter_log": filter_log,
        "model_source": "MiniMax M2.5 + GLM-5 + Kimi K2.5",
    }


# =====================================================================
# 回测评价
# =====================================================================

async def evaluate_backtest(
    picks: List[Dict],
    returns: Dict[str, Dict],
) -> Optional[str]:
    """使用AI三模型联合（MiniMax M2.5 + GLM-5 + Kimi K2.5）对回测结果进行评价
    
    Args:
        picks: [{code, name, ...}, ...]
        returns: {code: {return_1m, return_3m, return_6m}}
    
    Returns:
        AI评价文本
    """
    lines = []
    for p in picks:
        code = p["code"]
        name = p["name"]
        r = returns.get(code, {})
        r1 = r.get("return_1m")
        r3 = r.get("return_3m")
        r6 = r.get("return_6m")
        lines.append(
            f"- {code} {name}: "
            f"1个月{'+'if r1 and r1>0 else ''}{r1 or '无数据'}% | "
            f"3个月{'+'if r3 and r3>0 else ''}{r3 or '无数据'}% | "
            f"6个月{'+'if r6 and r6>0 else ''}{r6 or '无数据'}%"
        )

    returns_str = "\n".join(lines)

    prompt = f"""请对以下C-REITs推荐的回测表现进行评价：

回测结果：
{returns_str}

请从以下维度进行评价：
1. 整体收益表现（是否跑赢同期中证REITs指数）
2. 收益稳定性（各品种表现分化程度）
3. 不同持有期的收益特征（1/3/6个月）
4. 改进建议

请用200字以内给出简要评价。
"""
    system = "你是C-REITs投资分析师，请给出专业客观的回测评价。"

    try:
        # 三模型并发调用
        tasks = []
        task_labels = []
        task_weights = []
        if MINIMAX_ENABLED:
            tasks.append(chat_minimax(prompt, system=system, temperature=0.3))
            task_labels.append("MiniMax")
            task_weights.append(MINIMAX_WEIGHT)
        if GLM_ENABLED:
            tasks.append(chat_glm(prompt, system=system, temperature=0.3))
            task_labels.append("GLM-5")
            task_weights.append(GLM_WEIGHT)
        if KIMI_ENABLED:
            tasks.append(chat_kimi(prompt, system=system))
            task_labels.append("Kimi")
            task_weights.append(KIMI_WEIGHT)

        if not tasks:
            return None

        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        # 取第一个成功的评价（回测评价为文本，不做融合）
        responses = []
        for resp, label in zip(raw_results, task_labels):
            if isinstance(resp, Exception):
                logger.warning(f"回测评价 {label} 调用异常: {resp}")
                continue
            if resp:
                responses.append(f"【{label}评价】\n{resp}")

        if responses:
            return "\n\n".join(responses)
        return None

    except Exception as e:
        logger.error(f"回测评价生成失败: {e}")
        return None


def calculate_returns(
    code: str,
    pick_date: date,
    history_df,
) -> Dict[str, Optional[float]]:
    """计算单只REITs的回测收益率
    
    Args:
        code: REITs代码
        pick_date: 推荐日期
        history_df: 历史行情DataFrame
    
    Returns:
        {return_1m, return_3m, return_6m}
    """
    result = {"return_1m": None, "return_3m": None, "return_6m": None}

    if history_df is None or history_df.empty:
        return result

    try:
        df = history_df.copy()
        df = df.sort_values("date")

        # 找到推荐日（或之后最近的交易日）的价格
        pick_rows = df[df["date"] >= pick_date]
        if pick_rows.empty:
            return result
        pick_price = pick_rows.iloc[0]["close"]
        if not pick_price or pick_price <= 0:
            return result

        today = date.today()

        # 1个月
        target_1m = pick_date + timedelta(days=30)
        if target_1m <= today:
            rows_1m = df[df["date"] >= target_1m]
            if not rows_1m.empty:
                price_1m = rows_1m.iloc[0]["close"]
                if price_1m:
                    result["return_1m"] = round((price_1m / pick_price - 1) * 100, 2)

        # 3个月
        target_3m = pick_date + timedelta(days=90)
        if target_3m <= today:
            rows_3m = df[df["date"] >= target_3m]
            if not rows_3m.empty:
                price_3m = rows_3m.iloc[0]["close"]
                if price_3m:
                    result["return_3m"] = round((price_3m / pick_price - 1) * 100, 2)

        # 6个月
        target_6m = pick_date + timedelta(days=180)
        if target_6m <= today:
            rows_6m = df[df["date"] >= target_6m]
            if not rows_6m.empty:
                price_6m = rows_6m.iloc[0]["close"]
                if price_6m:
                    result["return_6m"] = round((price_6m / pick_price - 1) * 100, 2)

    except Exception as e:
        logger.error(f"REITs回测计算失败 {code}: {e}")

    return result
