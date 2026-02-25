"""
房地产行业新闻资讯获取模块
数据源：新浪财经、东方财富
用于为AI评级提供最新政策和行业动态
"""

import json
import logging
import random
import re
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
]

# 新闻缓存（避免每只股票评级时都重复请求）
_news_cache: Dict[str, dict] = {}
_CACHE_TTL = 3600  # 缓存1小时


def _get_headers():
    return {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def _get_cached(key: str) -> Optional[List[Dict]]:
    """获取缓存的新闻"""
    if key in _news_cache:
        entry = _news_cache[key]
        if time.time() - entry["ts"] < _CACHE_TTL:
            return entry["data"]
    return None


def _set_cache(key: str, data: List[Dict]):
    """设置缓存"""
    _news_cache[key] = {"ts": time.time(), "data": data}


def fetch_sina_industry_news(count: int = 15) -> List[Dict]:
    """
    从新浪财经获取房地产行业新闻
    使用新浪财经搜索API
    """
    cache_key = "sina_industry"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    news_list = []
    keywords = ["房地产政策", "楼市调控", "房地产"]

    for keyword in keywords:
        try:
            url = (
                f"https://search.sina.com.cn/news?"
                f"q={keyword}&c=news&sort=time&range=all&num=10&page=1"
            )
            # 新浪搜索页面解析较复杂，改用新浪财经滚动新闻API
            break
        except Exception:
            continue

    # 使用新浪财经滚动新闻接口（房产频道）
    try:
        url = (
            "https://feed.mix.sina.com.cn/api/roll/get?"
            "pageid=155&lid=1686&k=&num=20&page=1&r=0.1"
        )
        resp = requests.get(url, headers=_get_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("result", {}).get("data", [])
            for item in items[:count]:
                title = item.get("title", "").strip()
                if not title:
                    continue
                # 过滤非房地产相关
                news_list.append({
                    "title": title,
                    "source": "新浪财经",
                    "time": item.get("ctime", ""),
                    "url": item.get("url", ""),
                })
    except Exception as e:
        logger.warning(f"获取新浪房产新闻失败: {e}")

    # 备选：新浪财经要闻（可能包含房地产政策）
    if len(news_list) < 5:
        try:
            url = (
                "https://feed.mix.sina.com.cn/api/roll/get?"
                "pageid=153&lid=2509&k=&num=30&page=1&r=0.1"
            )
            resp = requests.get(url, headers=_get_headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("result", {}).get("data", [])
                re_keywords = re.compile(
                    r"房地产|楼市|房企|地产|住房|限购|限贷|公积金|"
                    r"土地|保交楼|房贷|首付|棚改|旧改|城中村|"
                    r"住建|不动产|物业|房价|二手房|新房"
                )
                for item in items:
                    title = item.get("title", "").strip()
                    if title and re_keywords.search(title):
                        news_list.append({
                            "title": title,
                            "source": "新浪财经",
                            "time": item.get("ctime", ""),
                            "url": item.get("url", ""),
                        })
        except Exception as e:
            logger.warning(f"获取新浪财经要闻失败: {e}")

    _set_cache(cache_key, news_list)
    return news_list


def fetch_eastmoney_news(count: int = 15) -> List[Dict]:
    """
    从东方财富获取房地产板块新闻
    使用东方财富资讯接口
    """
    cache_key = "eastmoney_industry"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    news_list = []
    try:
        # 东方财富房地产板块资讯
        url = (
            "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?"
            "client=web&biz=web_news_col&column=351&order=1"
            f"&needInteractData=0&page_index=1&page_size={count}"
        )
        resp = requests.get(url, headers=_get_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            items = data.get("data", {}).get("list", [])
            for item in items:
                title = item.get("title", "").strip()
                if not title:
                    continue
                news_list.append({
                    "title": title,
                    "source": "东方财富",
                    "time": item.get("showTime", ""),
                    "url": item.get("url", ""),
                })
    except Exception as e:
        logger.warning(f"获取东方财富新闻失败: {e}")

    # 备选：东方财富财经要闻
    if len(news_list) < 5:
        try:
            url = (
                "https://np-listapi.eastmoney.com/comm/web/getNewsByColumns?"
                "client=web&biz=web_news_col&column=350&order=1"
                f"&needInteractData=0&page_index=1&page_size=30"
            )
            resp = requests.get(url, headers=_get_headers(), timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("list", [])
                re_keywords = re.compile(
                    r"房地产|楼市|房企|地产|住房|限购|限贷|公积金|"
                    r"土地|保交楼|房贷|首付|棚改|旧改|城中村|"
                    r"住建|不动产|物业|房价|二手房|新房"
                )
                for item in items:
                    title = item.get("title", "").strip()
                    if title and re_keywords.search(title):
                        news_list.append({
                            "title": title,
                            "source": "东方财富",
                            "time": item.get("showTime", ""),
                            "url": item.get("url", ""),
                        })
        except Exception as e:
            logger.warning(f"获取东方财富要闻失败: {e}")

    _set_cache(cache_key, news_list)
    return news_list


def fetch_stock_news(code: str, name: str, count: int = 5) -> List[Dict]:
    """
    获取个股相关新闻
    """
    cache_key = f"stock_{code}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    news_list = []

    # 东方财富个股新闻
    try:
        url = (
            f"https://search-api-web.eastmoney.com/search/jsonp?"
            f"cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{name}%22"
            f"%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D"
            f"%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22"
            f"%2C%22clientVersion%22%3A%22curr%22"
            f"%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22"
            f"%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A{count}"
            f"%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"
        )
        resp = requests.get(url, headers=_get_headers(), timeout=10)
        if resp.status_code == 200:
            text = resp.text
            # 解析 JSONP: jQuery({...})
            match = re.search(r'jQuery\((\{.*\})\)', text, re.DOTALL)
            if match:
                data = json.loads(match.group(1))
                items = (
                    data.get("result", {})
                    .get("cmsArticleWebOld", {})
                    .get("list", [])
                )
                for item in items[:count]:
                    title = item.get("title", "").strip()
                    # 去除HTML标签
                    title = re.sub(r'<[^>]+>', '', title)
                    if title:
                        news_list.append({
                            "title": title,
                            "source": "东方财富",
                            "time": item.get("date", ""),
                            "url": item.get("url", ""),
                        })
    except Exception as e:
        logger.debug(f"获取{name}个股新闻失败: {e}")

    _set_cache(cache_key, news_list)
    return news_list


def get_real_estate_news_summary(code: str = "", name: str = "") -> str:
    """
    获取房地产行业新闻摘要，用于注入AI评级prompt
    返回格式化的新闻文本
    """
    all_news = []

    # 1. 行业新闻（多数据源）
    industry_news = fetch_sina_industry_news(10)
    all_news.extend(industry_news)

    eastmoney_news = fetch_eastmoney_news(10)
    # 去重
    existing_titles = {n["title"] for n in all_news}
    for n in eastmoney_news:
        if n["title"] not in existing_titles:
            all_news.append(n)
            existing_titles.add(n["title"])

    # 2. 个股新闻
    stock_news = []
    if code and name:
        stock_news = fetch_stock_news(code, name, 5)

    # 格式化输出
    lines = []
    today = datetime.now().strftime("%Y-%m-%d")

    if all_news:
        lines.append(f"【房地产行业最新资讯（{today}）】")
        for i, n in enumerate(all_news[:12], 1):
            time_str = f" ({n['time']})" if n.get("time") else ""
            lines.append(f"{i}. {n['title']}{time_str}")

    if stock_news:
        lines.append(f"\n【{name}({code})相关资讯】")
        for i, n in enumerate(stock_news[:5], 1):
            time_str = f" ({n['time']})" if n.get("time") else ""
            lines.append(f"{i}. {n['title']}{time_str}")

    if not lines:
        return ""

    return "\n".join(lines)
