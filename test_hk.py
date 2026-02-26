"""测试港股 iFinD 数据获取"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), 'backend', '.env'))

from app.ifind_client import (
    get_access_token, to_ifind_code,
    fetch_history, fetch_realtime, fetch_valuation, fetch_fundamentals,
    fetch_recent_announcements
)

# 测试用港股
HK_STOCKS = [
    ("01109", "华润置地"),
    ("00688", "中国海外发展"),
    ("00016", "新鸿基地产"),
    ("02007", "碧桂园"),
]

print("=" * 60)
print("1. Token 获取测试")
print("=" * 60)
token = get_access_token()
print(f"  Token: {token[:20]}..." if token else "  Token: 获取失败!")

print("\n" + "=" * 60)
print("2. 港股代码转换测试")
print("=" * 60)
for code, name in HK_STOCKS:
    ifind_code = to_ifind_code(code, "HK")
    print(f"  {code} ({name}) → {ifind_code}")

print("\n" + "=" * 60)
print("3. 港股历史行情测试")
print("=" * 60)
for code, name in HK_STOCKS[:2]:
    df = fetch_history(code, "HK", days=30)
    if df is not None:
        print(f"  {name}({code}): {len(df)}条数据, 最新={df.iloc[-1]['close']:.2f}, 日期={df.iloc[-1]['date']}")
    else:
        print(f"  {name}({code}): 获取失败")

print("\n" + "=" * 60)
print("4. 港股实时行情测试 (基础)")
print("=" * 60)
codes = [c for c, _ in HK_STOCKS]
rt = fetch_realtime(codes, "HK", rich=False)
if rt:
    for code, name in HK_STOCKS:
        d = rt.get(code)
        if d:
            print(f"  {name}({code}): 最新={d['latest']}, 涨跌={d['change_ratio']}%")
        else:
            print(f"  {name}({code}): 无数据")
else:
    print("  实时行情获取失败")

print("\n" + "=" * 60)
print("5. 港股实时行情测试 (增强/资金流)")
print("=" * 60)
rt_rich = fetch_realtime(codes[:2], "HK", rich=True)
if rt_rich:
    for code, name in HK_STOCKS[:2]:
        d = rt_rich.get(code)
        if d:
            print(f"  {name}({code}):")
            print(f"    最新={d['latest']}, 涨跌={d['change_ratio']}%")
            print(f"    PE_TTM={d.get('pe_ttm')}, PB_LF={d.get('pb_lf')}, 总市值={d.get('total_capital')}")
            print(f"    主力净流入={d.get('main_net_inflow')}, 散户净流入={d.get('retail_net_inflow')}")
            print(f"    连涨天数={d.get('rise_day_count')}, 量比={d.get('vol_ratio')}")
            print(f"    5日涨跌={d.get('chg_5d')}, 20日涨跌={d.get('chg_20d')}, 年初至今={d.get('chg_year')}")
        else:
            print(f"  {name}({code}): 无数据")
else:
    print("  增强实时行情获取失败")

print("\n" + "=" * 60)
print("6. 港股估值数据测试 (basic_data_service)")
print("=" * 60)
val = fetch_valuation(codes[:2], "HK")
if val:
    for code, name in HK_STOCKS[:2]:
        d = val.get(code)
        if d:
            print(f"  {name}({code}): PE={d.get('pe_ttm')}, PB={d.get('pb_mrq')}, 市值={d.get('market_value')}亿")
        else:
            print(f"  {name}({code}): 无数据 (FREEIAL账号限制)")
else:
    print("  估值数据获取失败或全部为空")

print("\n" + "=" * 60)
print("7. 港股基本面综合测试 (fetch_fundamentals)")
print("=" * 60)
for code, name in HK_STOCKS[:2]:
    fund = fetch_fundamentals(code, "HK")
    if fund:
        print(f"  {name}({code}):")
        for k, v in fund.items():
            print(f"    {k} = {v}")
    else:
        print(f"  {name}({code}): 无基本面数据")

print("\n" + "=" * 60)
print("8. 港股公告查询测试")
print("=" * 60)
for code, name in HK_STOCKS[:2]:
    ann = fetch_recent_announcements(code, "HK", days=60)
    if ann:
        lines = ann.split("\n")
        print(f"  {name}({code}):")
        for line in lines[:5]:  # 只显示前5条
            print(f"    {line}")
    else:
        print(f"  {name}({code}): 无公告数据")

print("\n" + "=" * 60)
print("测试完成!")
print("=" * 60)
