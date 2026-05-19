"""
连通性验证脚本：
  1. iFinD API: token刷新 + 实时行情 + REITs行情
  2. 三个 LLM: MiniMax M2.7 + DeepSeek V4 Pro + Kimi K2.6

使用方式:
  cd backend && python verify_connections.py
"""
import asyncio
import sys
import time
from pathlib import Path

# 确保能导入 app
sys.path.insert(0, str(Path(__file__).resolve().parent))

# 加载 .env（确保 IFIND_*、LKEAP_API_KEY 等环境变量可用）
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")


# ==================== 工具 ====================
def title(text: str):
    print(f"\n{'='*60}\n  {text}\n{'='*60}")


def ok(msg: str):
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str):
    print(f"  \033[31m✗\033[0m {msg}")


def info(msg: str):
    print(f"  · {msg}")


# ==================== 1. iFinD ====================
def test_ifind():
    title("1. iFinD 同花顺API 连通性验证")
    from app import ifind_client

    # 1.1 Token 刷新
    info("1.1 测试 access_token 刷新...")
    token = ifind_client.refresh_access_token(force_new=False)
    if not token:
        fail("access_token 刷新失败")
        return False
    ok(f"access_token 获取成功（前30字符）: {token[:30]}...")

    # 1.2 实时行情（地产A股测试）
    info("1.2 测试 A股实时行情（万科A 000002）...")
    rt = ifind_client.fetch_realtime(["000002"], market="A", rich=False)
    if rt and "000002" in rt:
        data = rt["000002"]
        ok(f"万科A 实时数据: 最新价={data.get('latest')} 涨跌={data.get('change_ratio')}%")
    else:
        fail(f"A股实时行情获取失败: {rt}")

    # 1.3 历史行情
    info("1.3 测试 A股历史K线（招商蛇口 001979 近5天）...")
    df = ifind_client.fetch_history("001979", market="A", days=5)
    if df is not None and len(df) > 0:
        ok(f"历史K线获取成功: {len(df)}条记录, 最新收盘价={df.iloc[-1]['close']}")
    else:
        fail(f"历史K线获取失败")

    # 1.4 REITs 实时行情
    info("1.4 测试 REITs 实时行情（博时蛇口产园 180101）...")
    reit_rt = ifind_client.fetch_reit_realtime(["180101"])
    if reit_rt and "180101" in reit_rt:
        data = reit_rt["180101"]
        ok(f"REIT 实时: 最新价={data.get('latest')} 涨跌={data.get('change_ratio')}%")
    else:
        fail(f"REITs 实时行情获取失败: {reit_rt}")

    # 1.5 REITs 分红率
    info("1.5 测试 REITs 分红率（180101）...")
    div = ifind_client.fetch_reit_dividend_yield(["180101"])
    if div and "180101" in div:
        ok(f"REIT 分红率: {div['180101']}%")
    else:
        info(f"REIT 分红率（可能数据源暂无）: {div}")

    # 1.6 估值数据
    info("1.6 测试 估值数据（万科A）...")
    val = ifind_client.fetch_valuation(["000002"], market="A")
    if val and "000002" in val:
        v = val["000002"]
        ok(f"万科A 估值: PE={v.get('pe_ttm')} PB={v.get('pb_mrq')} 市值={v.get('total_mv')}亿")
    else:
        fail(f"估值数据获取失败: {val}")

    return True


# ==================== 2. LLM ====================
async def test_llm():
    title("2. 三个 LLM 模型连通性验证 (腾讯云 TokenHub)")
    from app.llm_client import chat_minimax, chat_glm, chat_kimi
    from app.config import (
        MINIMAX_MODEL, GLM_MODEL, KIMI_MODEL,
        MINIMAX_ENABLED, GLM_ENABLED, KIMI_ENABLED,
        LKEAP_API_KEY,
    )

    info(f"API Key: {LKEAP_API_KEY[:20]}...{LKEAP_API_KEY[-6:]}")
    info(f"模型ID: MiniMax={MINIMAX_MODEL} | DeepSeek={GLM_MODEL} | Kimi={KIMI_MODEL}")
    info(f"启用状态: MiniMax={MINIMAX_ENABLED} | DeepSeek={GLM_ENABLED} | Kimi={KIMI_ENABLED}\n")

    test_prompt = "用一句话回答：中国一线城市有几个？"

    # 2.1 MiniMax M2.7
    info(f"2.1 测试 MiniMax M2.7 ({MINIMAX_MODEL})...")
    t0 = time.time()
    resp = await chat_minimax(test_prompt, temperature=0.3)
    dt = time.time() - t0
    if resp:
        ok(f"MiniMax 响应 ({dt:.1f}s): {resp[:120]}")
    else:
        fail(f"MiniMax 调用失败 ({dt:.1f}s)")

    # 2.2 DeepSeek V4 Pro
    info(f"2.2 测试 DeepSeek V4 Pro ({GLM_MODEL})...")
    t0 = time.time()
    resp = await chat_glm(test_prompt, temperature=0.3)
    dt = time.time() - t0
    if resp:
        ok(f"DeepSeek 响应 ({dt:.1f}s): {resp[:120]}")
    else:
        fail(f"DeepSeek 调用失败 ({dt:.1f}s)")

    # 2.3 Kimi K2.6
    info(f"2.3 测试 Kimi K2.6 ({KIMI_MODEL})...")
    t0 = time.time()
    resp = await chat_kimi(test_prompt)
    dt = time.time() - t0
    if resp:
        ok(f"Kimi 响应 ({dt:.1f}s): {resp[:120]}")
    else:
        fail(f"Kimi 调用失败 ({dt:.1f}s)")


# ==================== 主流程 ====================
async def main():
    print("\n🔍 开始连通性验证...")

    # 1. iFinD
    try:
        test_ifind()
    except Exception as e:
        fail(f"iFinD 测试异常: {e}")
        import traceback
        traceback.print_exc()

    # 2. LLM
    try:
        await test_llm()
    except Exception as e:
        fail(f"LLM 测试异常: {e}")
        import traceback
        traceback.print_exc()

    print(f"\n{'='*60}\n✅ 验证结束\n{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(main())
