"""
房地产股票AI评级引擎（量化 + 大模型混合评级）

评级架构:
  量化技术评分 (50%) + AI大模型评分 (50%)

一、量化技术评分（5个维度，各0-100分）:
  1. 趋势评分 (Trend) - 权重25%: 均线排列、价格vs均线、趋势斜率
  2. 动量评分 (Momentum) - 权重20%: RSI、MACD、近期涨跌幅
  3. 波动率评分 (Volatility) - 权重15%: 历史波动率、布林带宽度
  4. 成交量评分 (Volume) - 权重20%: 量比、量价配合、成交趋势
  5. 价值评分 (Value) - 权重20%: 距高低点位置、支撑强度

二、AI大模型评分 (0-100分):
  腾讯混元分析基本面、行业政策、市场情绪，给出AI综合评分和专业分析

综合评分 = 量化评分 × 50% + AI评分 × 50%
（若AI不可用，则100%使用量化评分）

评级映射:
  >= 80: 强烈推荐
  >= 65: 推荐
  >= 50: 中性
  >= 35: 谨慎
  <  35: 回避
"""

import json
import logging
import re

import numpy as np
import pandas as pd
from typing import Optional, Dict

from app.llm_client import chat_hunyuan

logger = logging.getLogger(__name__)

QUANT_WEIGHTS = {
    "trend": 0.25,
    "momentum": 0.20,
    "volatility": 0.15,
    "volume": 0.20,
    "value": 0.20,
}

QUANT_RATIO = 0.50  # 量化评分占比
AI_RATIO = 0.50     # AI评分占比

RATING_MAP = [
    (80, "强烈推荐"),
    (65, "推荐"),
    (50, "中性"),
    (35, "谨慎"),
    (0, "回避"),
]

AI_SYSTEM_PROMPT = """你是一位资深的中国房地产行业股票分析师，精通A股、港股和美股市场。
你需要基于提供的股票行情数据，从以下维度进行专业分析：
1. 基本面判断：根据股价走势推断公司经营状况
2. 行业环境：当前中国房地产行业政策和市场环境
3. 资金面：成交量变化反映的市场资金态度
4. 风险评估：潜在风险因素

请严格按照要求的JSON格式输出。"""


def _clamp(v: float, lo: float = 0, hi: float = 100) -> float:
    return max(lo, min(hi, v))


# ========== 量化评分函数 ==========

def calc_trend_score(df: pd.DataFrame) -> float:
    if len(df) < 60:
        return 50.0
    close = df["close"].values
    ma5 = pd.Series(close).rolling(5).mean().iloc[-1]
    ma20 = pd.Series(close).rolling(20).mean().iloc[-1]
    ma60 = pd.Series(close).rolling(60).mean().iloc[-1]
    price = close[-1]
    score = 50.0
    if ma5 > ma20 > ma60:
        score += 25
    elif ma5 > ma20:
        score += 12
    elif ma5 < ma20 < ma60:
        score -= 20
    if price > ma20:
        score += 10
    if price > ma60:
        score += 5
    if price < ma20:
        score -= 10
    if price < ma60:
        score -= 5
    ma20_series = pd.Series(close).rolling(20).mean().dropna()
    if len(ma20_series) >= 10:
        slope = (ma20_series.iloc[-1] - ma20_series.iloc[-10]) / ma20_series.iloc[-10] * 100
        score += _clamp(slope * 3, -10, 10)
    return _clamp(score)


def calc_momentum_score(df: pd.DataFrame) -> float:
    if len(df) < 30:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    score = 50.0
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain.iloc[-1] / (loss.iloc[-1] + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    if rsi > 70:
        score += 15
    elif rsi > 55:
        score += 10
    elif rsi < 30:
        score -= 15
    elif rsi < 45:
        score -= 5
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9).mean()
    macd = (dif - dea).iloc[-1]
    if dif.iloc[-1] > 0 and macd > 0:
        score += 15
    elif dif.iloc[-1] > 0:
        score += 5
    elif dif.iloc[-1] < 0 and macd < 0:
        score -= 15
    else:
        score -= 5
    ret_5d = (close.iloc[-1] / close.iloc[-6] - 1) * 100 if len(close) > 5 else 0
    score += _clamp(ret_5d * 2, -10, 10)
    return _clamp(score)


def calc_volatility_score(df: pd.DataFrame) -> float:
    if len(df) < 20:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    returns = close.pct_change().dropna()
    score = 50.0
    vol_20 = returns.tail(20).std() * np.sqrt(252) * 100
    if vol_20 < 20:
        score += 25
    elif vol_20 < 35:
        score += 10
    elif vol_20 > 60:
        score -= 20
    elif vol_20 > 45:
        score -= 10
    ma20 = close.rolling(20).mean().iloc[-1]
    std20 = close.rolling(20).std().iloc[-1]
    bb_width = (std20 * 2) / (ma20 + 1e-10) * 100
    if bb_width < 5:
        score += 10
    elif bb_width < 10:
        score += 5
    elif bb_width > 20:
        score -= 10
    return _clamp(score)


def calc_volume_score(df: pd.DataFrame) -> float:
    if len(df) < 20:
        return 50.0
    volume = pd.Series(df["volume"].values, dtype=float)
    close = pd.Series(df["close"].values, dtype=float)
    score = 50.0
    vol_ma5 = volume.rolling(5).mean().iloc[-1]
    vol_ma20 = volume.rolling(20).mean().iloc[-1]
    vol_ratio = vol_ma5 / (vol_ma20 + 1e-10)
    if 1.0 < vol_ratio < 1.5:
        score += 15
    elif vol_ratio >= 1.5:
        score += 8
    elif vol_ratio < 0.7:
        score -= 10
    last_5_close_change = close.diff().tail(5)
    last_5_vol_change = volume.diff().tail(5)
    concordance = (last_5_close_change * last_5_vol_change > 0).sum()
    score += (concordance - 2.5) * 4
    if vol_ma5 > vol_ma20:
        score += 5
    else:
        score -= 3
    return _clamp(score)


def calc_value_score(df: pd.DataFrame) -> float:
    if len(df) < 20:
        return 50.0
    close = pd.Series(df["close"].values, dtype=float)
    score = 50.0
    current = close.iloc[-1]
    high_52w = close.max()
    low_52w = close.min()
    drawdown = (high_52w - current) / (high_52w + 1e-10) * 100
    if drawdown < 10:
        score += 10
    elif 10 <= drawdown < 25:
        score += 15
    elif 25 <= drawdown < 40:
        score += 5
    else:
        score -= 10
    up_from_low = (current - low_52w) / (low_52w + 1e-10) * 100
    if up_from_low > 30:
        score += 10
    elif up_from_low < 5:
        score -= 10
    recent_low = close.tail(10).min()
    support_strength = (current - recent_low) / (recent_low + 1e-10) * 100
    if support_strength < 3:
        score += 5
    elif support_strength > 10:
        score += 8
    return _clamp(score)


def calc_quant_score(df: pd.DataFrame) -> Dict[str, float]:
    """计算所有量化评分维度"""
    scores = {
        "trend": round(calc_trend_score(df), 1),
        "momentum": round(calc_momentum_score(df), 1),
        "volatility": round(calc_volatility_score(df), 1),
        "volume": round(calc_volume_score(df), 1),
        "value": round(calc_value_score(df), 1),
    }
    total = sum(scores[k] * QUANT_WEIGHTS[k] for k in QUANT_WEIGHTS)
    scores["quant_total"] = round(total, 1)
    return scores


# ========== AI大模型评分 ==========

def _build_ai_prompt(name: str, code: str, market: str, df: pd.DataFrame, quant_scores: Dict) -> str:
    """构建发送给大模型的分析提示"""
    close = df["close"].values
    volume = df["volume"].values
    change_pct = df["change_pct"].values if "change_pct" in df.columns else []

    current_price = close[-1]
    high_price = max(close)
    low_price = min(close)
    avg_volume = np.mean(volume[-20:]) if len(volume) >= 20 else np.mean(volume)

    # 近期走势摘要
    ret_5d = (close[-1] / close[-6] - 1) * 100 if len(close) > 5 else 0
    ret_20d = (close[-1] / close[-21] - 1) * 100 if len(close) > 20 else 0
    ret_60d = (close[-1] / close[-61] - 1) * 100 if len(close) > 60 else 0

    market_name = {"A": "A股", "HK": "港股", "US": "美股"}.get(market, market)

    prompt = f"""请分析以下中国房地产相关股票，给出AI评分和专业分析。

【股票信息】
- 名称: {name}
- 代码: {code}
- 市场: {market_name}

【行情数据摘要】
- 最新价格: {current_price:.2f}
- 近5日涨跌幅: {ret_5d:+.2f}%
- 近20日涨跌幅: {ret_20d:+.2f}%
- 近60日涨跌幅: {ret_60d:+.2f}%
- 区间最高价: {high_price:.2f}
- 区间最低价: {low_price:.2f}
- 距最高点回撤: {(high_price - current_price) / high_price * 100:.1f}%
- 近20日均成交量: {avg_volume:,.0f}

【量化技术评分】
- 趋势评分: {quant_scores['trend']}/100
- 动量评分: {quant_scores['momentum']}/100
- 波动评分: {quant_scores['volatility']}/100
- 成交评分: {quant_scores['volume']}/100
- 价值评分: {quant_scores['value']}/100
- 量化综合: {quant_scores['quant_total']}/100

请你综合以上数据，结合你对中国房地产行业的理解，输出以下JSON格式（不要输出其他内容）:
{{
  "ai_score": <0-100的整数，你给出的AI综合评分>,
  "analysis": "<200字以内的专业分析，包含：1.技术面解读 2.行业/基本面判断 3.风险提示 4.操作建议>"
}}"""
    return prompt


def _parse_ai_response(response: str) -> Optional[Dict]:
    """解析AI返回的JSON"""
    if not response:
        return None
    try:
        # 尝试直接解析
        data = json.loads(response)
        if "ai_score" in data and "analysis" in data:
            score = int(data["ai_score"])
            return {
                "ai_score": _clamp(score),
                "analysis": str(data["analysis"]).strip(),
            }
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取JSON块
    try:
        match = re.search(r'\{[^{}]*"ai_score"[^{}]*\}', response, re.DOTALL)
        if match:
            data = json.loads(match.group())
            score = int(data["ai_score"])
            return {
                "ai_score": _clamp(score),
                "analysis": str(data.get("analysis", "")).strip(),
            }
    except Exception:
        pass

    # 尝试提取数字作为分数
    try:
        score_match = re.search(r'"ai_score"\s*:\s*(\d+)', response)
        analysis_match = re.search(r'"analysis"\s*:\s*"([^"]*)"', response)
        if score_match:
            return {
                "ai_score": _clamp(int(score_match.group(1))),
                "analysis": analysis_match.group(1) if analysis_match else "AI分析结果解析异常",
            }
    except Exception:
        pass

    logger.warning(f"无法解析AI响应: {response[:200]}")
    return None


async def get_ai_rating(name: str, code: str, market: str, df: pd.DataFrame, quant_scores: Dict) -> Optional[Dict]:
    """获取AI大模型评分"""
    prompt = _build_ai_prompt(name, code, market, df, quant_scores)
    response = await chat_hunyuan(prompt, system=AI_SYSTEM_PROMPT, temperature=0.3)
    if not response:
        return None
    result = _parse_ai_response(response)
    if result:
        logger.info(f"  AI评分: {result['ai_score']}")
    return result


# ========== 综合评级 ==========

def _generate_fallback_reason(name: str, scores: Dict[str, float], total: float, rating: str) -> str:
    """量化模式下的评级理由（AI不可用时的降级方案）"""
    reasons = []
    if scores["trend"] >= 70:
        reasons.append("均线多头排列，趋势向好")
    elif scores["trend"] <= 35:
        reasons.append("均线空头排列，趋势偏弱")
    if scores["momentum"] >= 70:
        reasons.append("技术动量强劲，MACD/RSI信号积极")
    elif scores["momentum"] <= 35:
        reasons.append("动量不足，技术指标偏空")
    if scores["volatility"] >= 70:
        reasons.append("波动率低，走势稳健")
    elif scores["volatility"] <= 35:
        reasons.append("波动较大，风险偏高")
    if scores["volume"] >= 70:
        reasons.append("量价配合良好，资金关注度高")
    elif scores["volume"] <= 35:
        reasons.append("成交低迷，市场关注度不足")
    if scores["value"] >= 70:
        reasons.append("估值处于合理区间，具备配置价值")
    elif scores["value"] <= 35:
        reasons.append("价格偏离较大，需警惕风险")
    if not reasons:
        reasons.append("各项指标表现平稳，暂无明显方向信号")
    return f"{name}当前评级【{rating}】(综合{total:.0f}分): {'；'.join(reasons)}。"


async def rate_stock(df: pd.DataFrame, name: str = "", code: str = "", market: str = "") -> Optional[Dict]:
    """对单只股票进行混合评级（量化+AI）"""
    if df is None or len(df) < 20:
        return None

    # 1. 量化评分
    quant_scores = calc_quant_score(df)
    quant_total = quant_scores["quant_total"]

    # 2. AI大模型评分
    ai_result = await get_ai_rating(name, code, market, df, quant_scores)

    # 3. 综合计算
    if ai_result:
        ai_score = ai_result["ai_score"]
        total = round(quant_total * QUANT_RATIO + ai_score * AI_RATIO, 1)
        reason = ai_result["analysis"]
    else:
        ai_score = 0.0
        total = round(quant_total, 1)  # AI不可用，100%量化
        reason = ""

    # 4. 映射评级
    rating = "回避"
    for threshold, label in RATING_MAP:
        if total >= threshold:
            rating = label
            break

    # 5. 如果AI没有给出理由，使用量化降级理由
    if not reason:
        reason = _generate_fallback_reason(name, quant_scores, total, rating)

    return {
        "trend_score": quant_scores["trend"],
        "momentum_score": quant_scores["momentum"],
        "volatility_score": quant_scores["volatility"],
        "volume_score": quant_scores["volume"],
        "value_score": quant_scores["value"],
        "ai_score": round(ai_score, 1),
        "total_score": total,
        "rating": rating,
        "reason": reason,
    }
