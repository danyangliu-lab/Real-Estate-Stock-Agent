"""
同花顺 iFinD HTTP API 客户端
API文档: https://ftwc.51ifind.com/gwstatic/static/ds_web/quantapi-web/example.html

功能:
  - Token 自动管理（refresh_token → access_token，7天有效期自动刷新）
  - 历史行情 (cmd_history_quotation)
  - 实时行情 (real_time_quotation) — 含资金流、PE/PB/市值、多周期涨跌等80+指标
  - 基础数据 (basic_data_service) — PE/PB/市值/换手率等
  - 日期序列 (date_sequence) — 时间序列数据
  - 财务指标 (basic_data_service) — ROE/EPS等（需报告期日期）
  - 公告查询 (report_query) — 上市公司最新公告
  - 数据量查询 (get_data_volume) — 查询本月数据用量

注意:
  - A股代码格式: 001979.SZ / 600048.SH
  - 港股代码格式: 2007.HK (不带前导零)
  - 港股PE/PB等基础数据受限（FREEIAL账号），但历史行情和实时行情可用
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import requests
import pandas as pd

logger = logging.getLogger(__name__)

BASE_URL = "https://quantapi.51ifind.com/api/v1"
TOKEN_GET_URL = f"{BASE_URL}/get_access_token"
TOKEN_UPDATE_URL = f"{BASE_URL}/update_access_token"

# Token 缓存
_token_cache = {
    "access_token": None,
    "expires_at": 0,  # Unix timestamp
}

MAX_RETRIES = 3
RETRY_DELAY = 2


def _get_refresh_token() -> str:
    return os.getenv("IFIND_REFRESH_TOKEN", "")


def _get_access_token_from_env() -> str:
    return os.getenv("IFIND_ACCESS_TOKEN", "")


def refresh_access_token(force_new: bool = False) -> Optional[str]:
    """通过 refresh_token 获取 access_token（有效期7天）
    
    Args:
        force_new: True=调用 update_access_token 强制生成新token（旧token失效）
                   False=调用 get_access_token 获取当前有效的token
    """
    refresh_token = _get_refresh_token()
    if not refresh_token:
        logger.error("iFinD refresh_token 未配置")
        return None

    url = TOKEN_UPDATE_URL if force_new else TOKEN_GET_URL
    action = "更新" if force_new else "获取"

    try:
        resp = requests.post(
            url,
            headers={
                "Content-Type": "application/json",
                "refresh_token": refresh_token,
            },
            json={},
            timeout=15,
        )
        data = resp.json()
        if data.get("errorcode") == 0:
            token = data["data"]["access_token"]
            _token_cache["access_token"] = token
            # 提前1天过期，确保安全
            _token_cache["expires_at"] = time.time() + 6 * 86400
            logger.info(f"iFinD access_token {action}成功")
            return token
        else:
            logger.error(f"iFinD token{action}失败: {data}")
            # 如果 get 失败，尝试 update 强制生成新的
            if not force_new:
                logger.info("尝试强制更新 access_token...")
                return refresh_access_token(force_new=True)
            return None
    except Exception as e:
        logger.error(f"iFinD token{action}异常: {e}")
        return None


def get_access_token() -> Optional[str]:
    """获取有效的 access_token（自动刷新）
    
    策略:
      1. 缓存未过期 → 直接返回
      2. 缓存过期或为空 → 用 refresh_token 重新获取
      3. refresh 失败 → 尝试 .env 中的 IFIND_ACCESS_TOKEN 作为最后备选
    """
    # 如果缓存有效
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["access_token"]

    # 缓存过期或为空，通过 refresh_token 重新获取
    logger.info("iFinD access_token 缓存过期或为空，尝试刷新...")
    token = refresh_access_token()
    if token:
        return token

    # refresh 失败，最后尝试 .env 中的静态 token（可能已过期）
    env_token = _get_access_token_from_env()
    if env_token:
        logger.warning("iFinD refresh 失败，使用 .env 中的 IFIND_ACCESS_TOKEN（可能已过期）")
        _token_cache["access_token"] = env_token
        # 短有效期，1小时后再次尝试刷新
        _token_cache["expires_at"] = time.time() + 3600
        return env_token

    logger.error("iFinD 无法获取任何有效 access_token")
    return None


def _post(endpoint: str, payload: dict, label: str = "") -> Optional[dict]:
    """带重试和token管理的POST请求"""
    token = get_access_token()
    if not token:
        logger.warning(f"iFinD {label}: 无可用token")
        return None

    url = f"{BASE_URL}/{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "access_token": token,
    }

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=20)
            data = resp.json()
            ec = data.get("errorcode", -1)

            if ec == 0:
                return data
            elif ec == -4001:
                # Token过期，刷新后重试
                logger.info(f"iFinD {label}: token过期，刷新中...")
                _token_cache["access_token"] = None
                _token_cache["expires_at"] = 0
                token = refresh_access_token()
                if token:
                    headers["access_token"] = token
                    continue
                return None
            else:
                logger.warning(f"iFinD {label} 错误[{ec}]: {data.get('errmsg', '')}")
                return None
        except requests.exceptions.SSLError as e:
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY * attempt
                logger.debug(f"iFinD {label} SSL重试({attempt}): {e}")
                time.sleep(delay)
            else:
                logger.warning(f"iFinD {label} SSL失败: {e}")
                return None
        except Exception as e:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
            else:
                logger.warning(f"iFinD {label} 异常: {e}")
                return None
    return None


# =====================================================================
# 代码转换工具
# =====================================================================

def to_ifind_code(code: str, market: str) -> str:
    """将内部代码转换为iFinD代码格式
    A股: 000002 → 000002.SZ / 600048 → 600048.SH
    港股: 02007 → 2007.HK, 00688 → 0688.HK (数字部分去多余前导零，至少保留4位)
    美股: KE → KE.N (暂不支持，保留)
    REITs: 508000 → 508000.SH, 180101 → 180101.OF
    """
    if market == "A":
        if code.startswith(("6", "9")):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"
    elif market == "HK":
        # iFinD港股代码: 去掉多余前导零，但至少保留4位数字
        num = code.lstrip('0') or '0'
        if len(num) < 4:
            num = num.zfill(4)
        return f"{num}.HK"
    elif market == "US":
        return f"{code}.N"
    elif market == "REIT":
        # C-REITs代码: 508xxx → 508xxx.SH（场内交易），180xxx → 180xxx.OF（场外）
        if code.startswith("508"):
            return f"{code}.SH"
        else:
            return f"{code}.OF"
    return code


# =====================================================================
# 历史行情
# =====================================================================

def fetch_history(code: str, market: str, days: int = 120) -> Optional[pd.DataFrame]:
    """获取历史日K线数据
    返回DataFrame: date, open, high, low, close, volume, turnover, change_pct
    """
    ifind_code = to_ifind_code(code, market)
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = _post("cmd_history_quotation", {
        "codes": ifind_code,
        "indicators": "open,high,low,close,volume,amount,changeRatio",
        "startdate": start_date,
        "enddate": end_date,
    }, f"历史行情 {ifind_code}")

    if not data:
        return None

    tables = data.get("tables", [])
    if not tables:
        return None

    t = tables[0]
    times = t.get("time", [])
    tbl = t.get("table", {})

    if not times or "close" not in tbl:
        return None

    rows = []
    n = len(times)
    opens = tbl.get("open", [None] * n)
    highs = tbl.get("high", [None] * n)
    lows = tbl.get("low", [None] * n)
    closes = tbl.get("close", [None] * n)
    volumes = tbl.get("volume", [0] * n)
    amounts = tbl.get("amount", [0] * n)
    change_ratios = tbl.get("changeRatio", [0] * n)

    for i in range(n):
        rows.append({
            "date": times[i],
            "open": float(opens[i]) if opens[i] is not None else None,
            "high": float(highs[i]) if highs[i] is not None else None,
            "low": float(lows[i]) if lows[i] is not None else None,
            "close": float(closes[i]) if closes[i] is not None else None,
            "volume": float(volumes[i]) if volumes[i] is not None else 0,
            "turnover": float(amounts[i]) if amounts[i] is not None else 0,
            "change_pct": float(change_ratios[i]) if change_ratios[i] is not None else 0,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    # 过滤无效行
    df = df.dropna(subset=["close"])

    if df.empty or len(df) < 2:
        return None

    # 如果change_pct全为0，手动计算
    if (df["change_pct"] == 0).all():
        df["change_pct"] = df["close"].pct_change() * 100
        df["change_pct"] = df["change_pct"].fillna(0)

    return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]


# =====================================================================
# 实时行情（增强版 — 含资金流/估值/多周期涨跌）
# =====================================================================

# 实时行情可用的丰富指标（按用途分组）
_RT_BASIC = "open,high,low,latest,volume,amount,changeRatio,preClose,change"
_RT_VALUATION = "pe_ttm,pbr_lf,totalCapital,mv,turnoverRatio"
_RT_MONEY_FLOW = "mainNetInflow,retailNetInflow,largeNetInflow,bigNetInflow,middleNetInflow,smallNetInflow"
_RT_PERIOD_CHG = "chg_5d,chg_10d,chg_20d,chg_60d,chg_120d,chg_year"
_RT_EXTRA = "riseDayCount,vol_ratio,committee,commission_diff,swing"


def fetch_realtime(codes: List[str], market: str, rich: bool = False) -> Optional[Dict[str, dict]]:
    """获取实时行情
    codes: 内部代码列表, e.g. ["001979", "600048"]
    rich: True=获取全部指标（资金流/估值/多周期涨跌等），False=仅基础行情
    返回: {code: {latest, open, high, low, volume, amount, change_ratio, ...}}
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]

    indicators = _RT_BASIC
    if rich:
        indicators = f"{_RT_BASIC},{_RT_VALUATION},{_RT_MONEY_FLOW},{_RT_PERIOD_CHG},{_RT_EXTRA}"

    data = _post("real_time_quotation", {
        "codes": ",".join(ifind_codes),
        "indicators": indicators,
    }, f"实时行情 {market}")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        # 还原为内部代码
        internal_code = thscode.split(".")[0]
        if market == "HK":
            internal_code = internal_code.zfill(5)

        item = {
            "latest": tbl.get("latest", [None])[0],
            "open": tbl.get("open", [None])[0],
            "high": tbl.get("high", [None])[0],
            "low": tbl.get("low", [None])[0],
            "volume": tbl.get("volume", [None])[0],
            "amount": tbl.get("amount", [None])[0],
            "change_ratio": tbl.get("changeRatio", [None])[0],
            "pre_close": tbl.get("preClose", [None])[0],
            "change": tbl.get("change", [None])[0],
        }

        if rich:
            # 估值指标
            item["pe_ttm"] = tbl.get("pe_ttm", [None])[0]
            item["pb_lf"] = tbl.get("pbr_lf", [None])[0]
            item["total_capital"] = tbl.get("totalCapital", [None])[0]  # 总市值
            item["mv"] = tbl.get("mv", [None])[0]  # 流通市值
            item["turnover_ratio"] = tbl.get("turnoverRatio", [None])[0]

            # 资金流数据
            item["main_net_inflow"] = tbl.get("mainNetInflow", [None])[0]  # 主力净流入
            item["retail_net_inflow"] = tbl.get("retailNetInflow", [None])[0]  # 散户净流入
            item["large_net_inflow"] = tbl.get("largeNetInflow", [None])[0]  # 超大单净流入
            item["big_net_inflow"] = tbl.get("bigNetInflow", [None])[0]  # 大单净流入
            item["middle_net_inflow"] = tbl.get("middleNetInflow", [None])[0]  # 中单净流入
            item["small_net_inflow"] = tbl.get("smallNetInflow", [None])[0]  # 小单净流入

            # 多周期涨跌幅
            item["chg_5d"] = tbl.get("chg_5d", [None])[0]
            item["chg_10d"] = tbl.get("chg_10d", [None])[0]
            item["chg_20d"] = tbl.get("chg_20d", [None])[0]
            item["chg_60d"] = tbl.get("chg_60d", [None])[0]
            item["chg_120d"] = tbl.get("chg_120d", [None])[0]
            item["chg_year"] = tbl.get("chg_year", [None])[0]

            # 其他
            item["rise_day_count"] = tbl.get("riseDayCount", [None])[0]  # 连涨天数
            item["vol_ratio"] = tbl.get("vol_ratio", [None])[0]  # 量比
            item["committee"] = tbl.get("committee", [None])[0]  # 委比
            item["commission_diff"] = tbl.get("commission_diff", [None])[0]  # 委差
            item["swing"] = tbl.get("swing", [None])[0]  # 振幅

        result[internal_code] = item

    return result if result else None


# =====================================================================
# 基础数据（估值指标）
# =====================================================================

def fetch_valuation(codes: List[str], market: str) -> Optional[Dict[str, dict]]:
    """获取估值数据: PE_TTM, PB_MRQ, 总市值, 换手率
    仅A股有效，港股返回null
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]
    today = datetime.now().strftime("%Y%m%d")

    data = _post("basic_data_service", {
        "codes": ",".join(ifind_codes),
        "indipara": [
            {"indicator": "ths_pe_ttm_stock", "indiparams": [today]},
            {"indicator": "ths_pb_mrq_stock", "indiparams": [today]},
            {"indicator": "ths_market_value_stock", "indiparams": [today]},
            {"indicator": "ths_turnover_ratio_stock", "indiparams": [today]},
        ]
    }, f"估值数据 {market}")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        internal_code = thscode.split(".")[0]
        if market == "HK":
            internal_code = internal_code.zfill(5)

        pe = tbl.get("ths_pe_ttm_stock", [None])[0]
        pb = tbl.get("ths_pb_mrq_stock", [None])[0]
        market_value = tbl.get("ths_market_value_stock", [None])[0]
        turnover = tbl.get("ths_turnover_ratio_stock", [None])[0]

        # 跳过全null的数据（港股等）
        if pe is None and pb is None and market_value is None:
            continue

        result[internal_code] = {
            "pe_ttm": round(pe, 2) if pe is not None else None,
            "pb_mrq": round(pb, 4) if pb is not None else None,
            "market_value": round(market_value / 1e8, 2) if market_value is not None and market_value > 0 else None,  # 转为亿元，0视为无效
            "turnover_ratio": round(turnover, 2) if turnover is not None else None,
        }

    return result if result else None


# =====================================================================
# 财务指标
# =====================================================================

def _get_latest_report_date() -> str:
    """获取最近的财报报告期日期
    Q1: 03-31, Q2(中报): 06-30, Q3: 09-30, Q4(年报): 12-31
    """
    now = datetime.now()
    year = now.year
    month = now.month

    # 财报有滞后性：通常3个月后才出
    # 当前月份 -> 可用最新报告期
    if month >= 11:
        return f"{year}0930"   # Q3已出
    elif month >= 9:
        return f"{year}0630"   # 中报已出
    elif month >= 5:
        return f"{year - 1}1231"  # 年报已出
    elif month >= 4:
        return f"{year - 1}0930"  # 上年Q3
    else:
        return f"{year - 1}0630"  # 上年中报


def fetch_financials(codes: List[str], market: str) -> Optional[Dict[str, dict]]:
    """获取财务指标: ROE, EPS
    使用最近的报告期日期
    仅A股有效
    """
    if market != "A":
        return None

    ifind_codes = [to_ifind_code(c, market) for c in codes]
    report_date = _get_latest_report_date()

    data = _post("basic_data_service", {
        "codes": ",".join(ifind_codes),
        "indipara": [
            {"indicator": "ths_roe_stock", "indiparams": [report_date]},
            {"indicator": "ths_basic_eps_stock", "indiparams": [report_date]},
            {"indicator": "ths_asset_liability_ratio_stock", "indiparams": [report_date]},
        ]
    }, f"财务指标 {market}")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        internal_code = thscode.split(".")[0]

        roe = tbl.get("ths_roe_stock", [None])[0]
        eps = tbl.get("ths_basic_eps_stock", [None])[0]
        debt_ratio = tbl.get("ths_asset_liability_ratio_stock", [None])[0]

        if roe is None and eps is None and debt_ratio is None:
            continue

        result[internal_code] = {
            "roe": round(roe, 2) if roe is not None else None,
            "eps": round(eps, 4) if eps is not None else None,
            "debt_ratio": round(debt_ratio, 2) if debt_ratio is not None else None,
            "report_date": report_date,
        }

    return result if result else None


# =====================================================================
# 批量获取所有基本面数据（合并调用）
# =====================================================================

def _is_valid_turnover_ratio(val) -> bool:
    """校验换手率值是否合理（0~100%）"""
    if val is None:
        return False
    try:
        v = float(val)
        return 0 <= v <= 100
    except (ValueError, TypeError):
        return False


def _calc_rise_day_count(history_df) -> Optional[int]:
    """根据历史行情计算连涨/连跌天数
    返回正数=连涨天数，负数=连跌天数，0=平盘
    """
    if history_df is None or history_df.empty or len(history_df) < 2:
        return None
    try:
        changes = history_df["change_pct"].values
        # 从最后一天往前数
        count = 0
        last_dir = None  # True=涨, False=跌
        for i in range(len(changes) - 1, -1, -1):
            chg = changes[i]
            if chg > 0:
                direction = True
            elif chg < 0:
                direction = False
            else:
                break  # 平盘中断连续
            if last_dir is None:
                last_dir = direction
                count = 1
            elif direction == last_dir:
                count += 1
            else:
                break
        if last_dir is None:
            return 0
        return count if last_dir else -count
    except Exception:
        return None


def _calc_period_changes(history_df) -> dict:
    """根据历史行情计算多周期涨跌幅
    返回: {chg_5d, chg_10d, chg_20d, chg_60d, chg_120d, chg_year}
    """
    result = {}
    if history_df is None or history_df.empty or len(history_df) < 2:
        return result
    try:
        closes = history_df["close"].values
        dates = history_df["date"].values
        n = len(closes)
        latest = closes[-1]

        for label, days in [("chg_5d", 5), ("chg_10d", 10), ("chg_20d", 20),
                            ("chg_60d", 60), ("chg_120d", 120)]:
            idx = max(0, n - days - 1)
            if idx < n - 1 and closes[idx] and closes[idx] > 0:
                result[label] = round((latest / closes[idx] - 1) * 100, 2)

        # 年初至今涨跌幅
        try:
            current_year = datetime.now().year
            year_start_idx = None
            for i in range(n):
                d = dates[i]
                # 兼容 date 和 datetime 对象
                yr = d.year if hasattr(d, 'year') else int(str(d)[:4])
                if yr >= current_year:
                    year_start_idx = i
                    break
            if year_start_idx is not None and closes[year_start_idx] and closes[year_start_idx] > 0:
                result["chg_year"] = round((latest / closes[year_start_idx] - 1) * 100, 2)
        except Exception:
            pass

    except Exception:
        pass
    return result


def fetch_fundamentals(code: str, market: str, history_df=None) -> Optional[dict]:
    """获取单只股票的全部基本面数据
    合并估值+财务指标+实时资金流
    Args:
        code: 股票代码
        market: 市场 (A/HK/US)
        history_df: 可选的历史行情DataFrame，用于计算港股缺失的连涨天数和多周期涨跌幅
    """
    result = {}

    # 估值数据
    val = fetch_valuation([code], market)
    if val and code in val:
        result.update(val[code])

    # 财务数据（仅A股）
    if market == "A":
        fin = fetch_financials([code], market)
        if fin and code in fin:
            result.update(fin[code])

    # 实时资金流和估值补充（通过 real_time_quotation 获取）
    try:
        rt = fetch_realtime([code], market, rich=True)
        if rt and code in rt:
            rt_data = rt[code]
            # 资金流数据
            if rt_data.get("main_net_inflow") is not None:
                result["main_net_inflow"] = round(rt_data["main_net_inflow"] / 1e4, 2) if rt_data["main_net_inflow"] else None  # 转万元
                result["retail_net_inflow"] = round(rt_data["retail_net_inflow"] / 1e4, 2) if rt_data.get("retail_net_inflow") else None
                result["large_net_inflow"] = round(rt_data["large_net_inflow"] / 1e4, 2) if rt_data.get("large_net_inflow") else None
            # 连涨天数
            if rt_data.get("rise_day_count") is not None:
                result["rise_day_count"] = int(rt_data["rise_day_count"])
            # 量比
            if rt_data.get("vol_ratio") is not None:
                result["vol_ratio"] = round(rt_data["vol_ratio"], 2)
            # 振幅
            if rt_data.get("swing") is not None:
                result["swing"] = round(rt_data["swing"], 2)
            # 委比
            if rt_data.get("committee") is not None:
                result["committee"] = round(rt_data["committee"], 2)
            # 换手率（从realtime补充，带合理性校验）
            if not result.get("turnover_ratio"):
                raw_tr = rt_data.get("turnover_ratio")
                if _is_valid_turnover_ratio(raw_tr):
                    result["turnover_ratio"] = round(raw_tr, 2)
                elif raw_tr is not None:
                    logger.warning(f"换手率异常值已过滤: {code} turnover_ratio={raw_tr}")
            # 多周期涨跌幅（从实时接口获取比手动计算更准确）
            for key in ["chg_5d", "chg_10d", "chg_20d", "chg_60d", "chg_120d", "chg_year"]:
                if rt_data.get(key) is not None:
                    result[key] = round(rt_data[key], 2)
            # 用实时接口的PE/PB补充（如果 basic_data_service 没拿到）
            if result.get("pe_ttm") is None and rt_data.get("pe_ttm") is not None:
                result["pe_ttm"] = round(rt_data["pe_ttm"], 2)
            if result.get("pb_mrq") is None and rt_data.get("pb_lf") is not None:
                result["pb_mrq"] = round(rt_data["pb_lf"], 4)
            if not result.get("market_value") and rt_data.get("total_capital") is not None and rt_data["total_capital"] > 0:
                result["market_value"] = round(rt_data["total_capital"] / 1e8, 2)
    except Exception as e:
        logger.debug(f"实时增强数据获取失败（非关键）: {e}")

    # 对换手率做最终合理性校验（防止 basic_data_service 也返回异常值）
    if result.get("turnover_ratio") is not None and not _is_valid_turnover_ratio(result["turnover_ratio"]):
        logger.warning(f"最终换手率异常值已过滤: {code} turnover_ratio={result['turnover_ratio']}")
        result["turnover_ratio"] = None

    # 用历史行情补充缺失的数据（港股等iFinD返回null的指标）
    if history_df is not None and not history_df.empty:
        # 补充连涨天数
        if result.get("rise_day_count") is None:
            calc_rdc = _calc_rise_day_count(history_df)
            if calc_rdc is not None:
                result["rise_day_count"] = calc_rdc
        # 补充多周期涨跌幅
        calc_chg = _calc_period_changes(history_df)
        for key in ["chg_5d", "chg_10d", "chg_20d", "chg_60d", "chg_120d", "chg_year"]:
            if result.get(key) is None and key in calc_chg:
                result[key] = calc_chg[key]

    return result if result else None


# =====================================================================
# 公告查询
# =====================================================================

def fetch_reports(codes: List[str], market: str, days: int = 30,
                  report_type: str = "903", keyword: str = "") -> Optional[List[dict]]:
    """查询上市公司公告
    Args:
        codes: 内部代码列表
        market: 市场类型
        days: 回溯天数
        report_type: 903=全部, 901002004=上市公告书 等
        keyword: 标题关键词筛选（如"半年度报告"）
    Returns:
        [{thscode, secName, reportDate, reportTitle, pdfURL, ctime}, ...]
    """
    ifind_codes = [to_ifind_code(c, market) for c in codes]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    payload = {
        "codes": ",".join(ifind_codes),
        "functionpara": {
            "reportType": report_type,
        },
        "beginrDate": start_date,
        "endrDate": end_date,
        "outputpara": "reportDate:Y,thscode:Y,secName:Y,ctime:Y,reportTitle:Y,pdfURL:Y",
    }
    if keyword:
        payload["functionpara"]["keyWord"] = keyword

    data = _post("report_query", payload, f"公告查询 {market}")
    if not data:
        return None

    tables = data.get("tables", [])
    if not tables:
        return None

    results = []
    for t in tables:
        tbl = t.get("table", {})
        # report_query 返回结构是列表形式
        report_dates = tbl.get("reportDate", [])
        thscodes = tbl.get("thscode", [])
        sec_names = tbl.get("secName", [])
        ctimes = tbl.get("ctime", [])
        titles = tbl.get("reportTitle", [])
        urls = tbl.get("pdfURL", [])

        n = len(titles) if titles else 0
        for i in range(n):
            results.append({
                "thscode": thscodes[i] if i < len(thscodes) else "",
                "sec_name": sec_names[i] if i < len(sec_names) else "",
                "report_date": report_dates[i] if i < len(report_dates) else "",
                "report_title": titles[i] if i < len(titles) else "",
                "pdf_url": urls[i] if i < len(urls) else "",
                "ctime": ctimes[i] if i < len(ctimes) else "",
            })

    return results if results else None


def fetch_recent_announcements(code: str, market: str, days: int = 30) -> Optional[str]:
    """获取单只股票近期公告摘要（用于AI分析）
    返回格式化的公告标题列表字符串
    """
    reports = fetch_reports([code], market, days=days)
    if not reports:
        return None

    # 取最近10条公告
    recent = reports[:10]
    lines = []
    for r in recent:
        date_str = r.get("report_date", "")
        title = r.get("report_title", "")
        if title:
            lines.append(f"  [{date_str}] {title}")

    if not lines:
        return None

    return "【近期公告（同花顺iFinD）】\n" + "\n".join(lines)


# =====================================================================
# 数据量查询
# =====================================================================

def get_data_volume() -> Optional[dict]:
    """查询本月 iFinD API 数据用量"""
    today = datetime.now().strftime("%Y-%m-%d")
    first_of_month = datetime.now().replace(day=1).strftime("%Y-%m-%d")

    data = _post("get_data_volume", {
        "startdate": first_of_month,
        "enddate": today,
    }, "数据量查询")

    if data and data.get("errorcode") == 0:
        return data.get("data", {})
    return None


# =====================================================================
# REITs 专用数据获取
# =====================================================================

def fetch_reit_history(code: str, days: int = 180) -> Optional[pd.DataFrame]:
    """获取C-REITs历史日K线数据
    Args:
        code: REITs代码，如 "508000"
        days: 回溯天数
    Returns:
        DataFrame: date, open, high, low, close, volume, turnover, change_pct
    """
    ifind_code = to_ifind_code(code, "REIT")
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    data = _post("cmd_history_quotation", {
        "codes": ifind_code,
        "indicators": "open,high,low,close,volume,amount,changeRatio",
        "startdate": start_date,
        "enddate": end_date,
    }, f"REITs历史行情 {ifind_code}")

    if not data:
        return None

    tables = data.get("tables", [])
    if not tables:
        return None

    t = tables[0]
    times = t.get("time", [])
    tbl = t.get("table", {})

    if not times or "close" not in tbl:
        return None

    rows = []
    n = len(times)
    opens = tbl.get("open", [None] * n)
    highs = tbl.get("high", [None] * n)
    lows = tbl.get("low", [None] * n)
    closes = tbl.get("close", [None] * n)
    volumes = tbl.get("volume", [0] * n)
    amounts = tbl.get("amount", [0] * n)
    change_ratios = tbl.get("changeRatio", [0] * n)

    for i in range(n):
        rows.append({
            "date": times[i],
            "open": float(opens[i]) if opens[i] is not None else None,
            "high": float(highs[i]) if highs[i] is not None else None,
            "low": float(lows[i]) if lows[i] is not None else None,
            "close": float(closes[i]) if closes[i] is not None else None,
            "volume": float(volumes[i]) if volumes[i] is not None else 0,
            "turnover": float(amounts[i]) if amounts[i] is not None else 0,
            "change_pct": float(change_ratios[i]) if change_ratios[i] is not None else 0,
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.dropna(subset=["close"])

    if df.empty or len(df) < 2:
        return None

    if (df["change_pct"] == 0).all():
        df["change_pct"] = df["close"].pct_change() * 100
        df["change_pct"] = df["change_pct"].fillna(0)

    return df[["date", "open", "high", "low", "close", "volume", "turnover", "change_pct"]]


def fetch_reit_realtime(codes: List[str]) -> Optional[Dict[str, dict]]:
    """获取C-REITs实时行情
    Args:
        codes: REITs代码列表，如 ["508000", "508001"]
    Returns:
        {code: {latest, open, high, low, volume, change_ratio, turnover_ratio, ...}}
    """
    ifind_codes = [to_ifind_code(c, "REIT") for c in codes]

    indicators = "open,high,low,latest,volume,amount,changeRatio,preClose,change,turnoverRatio"

    data = _post("real_time_quotation", {
        "codes": ",".join(ifind_codes),
        "indicators": indicators,
    }, "REITs实时行情")

    if not data:
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        internal_code = thscode.split(".")[0]

        item = {
            "latest": tbl.get("latest", [None])[0],
            "open": tbl.get("open", [None])[0],
            "high": tbl.get("high", [None])[0],
            "low": tbl.get("low", [None])[0],
            "volume": tbl.get("volume", [None])[0],
            "amount": tbl.get("amount", [None])[0],
            "change_ratio": tbl.get("changeRatio", [None])[0],
            "pre_close": tbl.get("preClose", [None])[0],
            "change": tbl.get("change", [None])[0],
            "turnover_ratio": tbl.get("turnoverRatio", [None])[0],
        }

        result[internal_code] = item

    return result if result else None


def fetch_reit_dividend_yield(codes: List[str]) -> Optional[Dict[str, float]]:
    """获取C-REITs分红率（年化派息率）

    三级降级策略：
      1. basic_data_service (ths_dividend_rate_fund) — 最优
      2. date_sequence 日频序列 — 备选
      3. 历史行情除权缺口估算 — 最终降级

    Args:
        codes: REITs代码列表
    Returns:
        {code: dividend_yield_pct} 如 {"508000": 5.23}
    """
    ifind_codes = [to_ifind_code(c, "REIT") for c in codes]
    today = datetime.now().strftime("%Y%m%d")

    result = {}

    # ── 策略1: basic_data_service ──
    data = _post("basic_data_service", {
        "codes": ",".join(ifind_codes),
        "indipara": [
            {"indicator": "ths_dividend_rate_fund", "indiparams": [today]},
        ]
    }, "REITs分红率")

    if data and data.get("errorcode") == 0:
        for t in data.get("tables", []):
            thscode = t.get("thscode", "")
            tbl = t.get("table", {})
            internal_code = thscode.split(".")[0]
            div_rate = tbl.get("ths_dividend_rate_fund", [None])[0]
            if div_rate is not None:
                result[internal_code] = round(float(div_rate), 2)

    # ── 策略2: date_sequence 日频 ──
    if not result:
        logger.info("REITs分红率: basic_data_service 不可用，尝试 date_sequence")
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        for code in codes[:5]:  # 只探测前5只，避免大量无效请求
            ifind_code = to_ifind_code(code, "REIT")
            ds_data = _post("date_sequence", {
                "codes": ifind_code,
                "indicators": "ths_dividend_rate_fund",
                "startdate": start_date,
                "enddate": end_date,
                "functionpara": {"Period": "D"},
            }, f"REITs分红率序列 {ifind_code}")
            if ds_data and ds_data.get("errorcode") == 0:
                tables = ds_data.get("tables", [])
                if tables:
                    tbl = tables[0].get("table", {})
                    vals = tbl.get("ths_dividend_rate_fund", [])
                    for v in reversed(vals):
                        if v is not None:
                            result[code] = round(float(v), 2)
                            break
            elif ds_data and ds_data.get("errorcode") == -4210:
                # 参数错误 = 指标不可用，不再继续尝试
                logger.info("REITs分红率: date_sequence 指标不可用，切换历史行情估算")
                break

    # ── 策略3: 历史行情除权缺口估算 ──
    if not result:
        logger.info("REITs分红率: iFinD基金指标不可用，使用历史行情除权缺口估算")
        for code in codes:
            try:
                df = fetch_reit_history(code, days=400)
                if df is None or df.empty or len(df) < 30:
                    continue
                # 检测除权日: 前收盘价 - 开盘价 存在明显正向缺口（分红导致）
                # 分红日特征: 前一日收盘 > 当日开盘（且差值 > 日常波动）
                closes = df["close"].values
                opens = df["open"].values
                total_dividend = 0.0
                for i in range(1, len(df)):
                    gap = closes[i - 1] - opens[i]
                    # 缺口超过前一日收盘的0.5%且为正（排除正常波动）
                    if gap > closes[i - 1] * 0.005 and gap > 0.01:
                        total_dividend += gap
                if total_dividend > 0 and closes[-1] and closes[-1] > 0:
                    # 年化: 数据跨度占365天的比例
                    data_days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
                    if data_days > 0:
                        annualized = total_dividend * (365 / data_days)
                        yield_pct = round((annualized / closes[-1]) * 100, 2)
                        if 0 < yield_pct < 20:  # 合理范围校验
                            result[code] = yield_pct
            except Exception as e:
                logger.debug(f"REITs分红率估算失败 {code}: {e}")

    if result:
        logger.info(f"REITs分红率: 获取 {len(result)}/{len(codes)} 只")
    else:
        logger.warning("REITs分红率: 全部获取失败，筛选将跳过分红率维度")

    return result if result else None


def fetch_reit_income_trend(codes: List[str], years: int = 2) -> Optional[Dict[str, list]]:
    """获取C-REITs收入趋势（用于判断环比下降）
    通过查询基金的可供分配金额或净收益等

    注意: iFinD FREEIAL 账号可能不支持基金专用指标(ths_fund_income_fund)，
    此时返回 None，筛选引擎的第2层会自动跳过（全部保留）。

    Args:
        codes: REITs代码列表
        years: 回溯年数
    Returns:
        {code: [{period, income}, ...]} 按时间升序
    """
    ifind_codes = [to_ifind_code(c, "REIT") for c in codes]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")

    data = _post("date_sequence", {
        "codes": ",".join(ifind_codes),
        "indicators": "ths_fund_income_fund",
        "startdate": start_date,
        "enddate": end_date,
        "functionpara": {"Period": "Q"},  # 季度数据
    }, "REITs收入趋势")

    if not data:
        logger.warning("REITs收入趋势: iFinD基金收入指标不可用，第2层筛选将跳过")
        return None

    result = {}
    for t in data.get("tables", []):
        thscode = t.get("thscode", "")
        tbl = t.get("table", {})
        times = t.get("time", [])
        internal_code = thscode.split(".")[0]

        incomes = tbl.get("ths_fund_income_fund", [])
        records = []
        for i, tm in enumerate(times):
            val = incomes[i] if i < len(incomes) else None
            if val is not None:
                records.append({"period": tm, "income": float(val)})

        if records:
            result[internal_code] = records

    if result:
        logger.info(f"REITs收入趋势: 获取 {len(result)}/{len(codes)} 只")
    else:
        logger.warning("REITs收入趋势: 无有效数据，第2层筛选将跳过")

    return result if result else None


# =====================================================================
# 健康检查
# =====================================================================

def check_health() -> bool:
    """检查 iFinD API 是否可用"""
    token = get_access_token()
    if not token:
        return False

    data = _post("basic_data_service", {
        "codes": "001979.SZ",
        "indipara": [
            {"indicator": "ths_stock_short_name_stock", "indiparams": [""]},
        ]
    }, "健康检查")

    if data and data.get("errorcode") == 0:
        tables = data.get("tables", [])
        if tables:
            name = tables[0].get("table", {}).get("ths_stock_short_name_stock", [None])[0]
            logger.info(f"iFinD 健康检查通过: {name}")
            return True
    return False
