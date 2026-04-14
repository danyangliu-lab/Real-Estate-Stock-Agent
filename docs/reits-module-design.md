# C-REITs 跟踪模块 — 详细设计文档

> 本文档详细介绍 C-REITs 跟踪模块的设计理念、技术架构、筛选策略、新增代码文件及其逻辑解读。

---

## 1. 模块概述

### 1.1 背景

中国公募基础设施 REITs（C-REITs）自 2021 年首批产品上市以来，已发展至 80+ 只产品，涵盖产业园、交通基础设施、仓储物流、保障性住房、消费基础设施、能源、生态环保等多种资产类型。C-REITs 具有**强制分红（不低于可供分配金额的 90%）**、底层资产透明、波动率低于权益市场等特点，是房地产投资生态的重要组成部分。

### 1.2 模块定位

本模块作为房地产股票 AI 评级系统的**独立板块**，提供：
- **自选池管理**：82 只 C-REITs 完整清单，实时行情展示
- **智能筛选推荐**：5 层漏斗策略，每周自动推荐 5 只最优 REITs
- **回测评价**：1/3/6 个月收益率计算 + AI 专业评价
- **三模型联合决策**：MiniMax M2.5 + GLM-5 + Kimi K2.5 多模型投票

### 1.3 核心亮点

| 特性 | 说明 |
|------|------|
| **5 层漏斗筛选** | 分红率 → 收入趋势 → 流动性 → 舆情 → AI综合评选，层层过滤 |
| **三模型联合** | 舆情判断和综合评选均由三大模型投票决策，避免单模型偏见 |
| **自动化运行** | 每周日 01:05 自动执行，紧随地产股评级刷新之后 |
| **漏斗可视化** | 前端直观展示每层筛选人数变化，数据透明 |
| **82 只全覆盖** | 涵盖中国市场全部公募 REITs 产品 |

---

## 2. 技术架构

### 2.1 模块在系统中的位置

```
┌─────────────────────────────────────────────────────┐
│                    FastAPI 后端                       │
│                                                      │
│  ┌─────────────┐   ┌──────────────┐                 │
│  │ rating_     │   │ reits_       │ ◄── 新增模块    │
│  │ engine.py   │   │ engine.py    │                  │
│  │ (股票评级)  │   │ (REITs筛选)  │                  │
│  └──────┬──────┘   └──────┬───────┘                 │
│         │                  │                         │
│  ┌──────▼──────────────────▼───────┐                │
│  │       llm_client.py             │                │
│  │  MiniMax M2.5 / GLM-5 / Kimi   │                │
│  └──────┬──────────────────────────┘                │
│         │                                            │
│  ┌──────▼──────────────────────────┐                │
│  │       ifind_client.py           │                │
│  │  REITs行情/分红率/收入趋势      │                │
│  └─────────────────────────────────┘                │
│                                                      │
│  ┌─────────────┐   ┌──────────────┐                 │
│  │ reits_      │   │ models.py    │                  │
│  │ list.py     │   │ (4张新表)    │                  │
│  │ (82只清单)  │   │              │                  │
│  └─────────────┘   └──────────────┘                 │
└─────────────────────────────────────────────────────┘
         │
┌────────▼────────────────────────────────────────────┐
│                 React 前端                            │
│  ┌──────────────────────────────────────────────┐   │
│  │         REITsSection.jsx                      │   │
│  │  ┌──────────┐ ┌───────────┐ ┌─────────────┐ │   │
│  │  │ 自选池   │ │ 每周推荐  │ │ 回测评价    │ │   │
│  │  │ (列表)   │ │ (漏斗图)  │ │ (收益表)    │ │   │
│  │  └──────────┘ └───────────┘ └─────────────┘ │   │
│  └──────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────┘
```

### 2.2 数据流转

```
每周日 01:05 定时任务触发
    │
    ▼
reits_list.py (82只REITs清单)
    │
    ▼ 全量代码列表
iFinD API → fetch_reit_dividend_yield()
    │
    ▼ 分红率数据
第1层: filter_by_dividend_yield() → 剔除分红率不达标
    │
    ▼ 通过代码
iFinD API → fetch_reit_income_trend()
    │
    ▼ 收入趋势数据
第2层: filter_by_income_decline() → 剔除收入持续下降
    │
    ▼ 通过代码
iFinD API → fetch_reit_history() (逐只, 30日)
    │
    ▼ 历史行情
第3层: filter_by_zero_turnover() → 剔除零换手率
    │
    ▼ 通过代码
三模型并发 → MiniMax + GLM-5 + Kimi
    │
    ▼ 投票结果
第4层: filter_by_sentiment() → 多数投票剔除负面舆情
    │
    ▼ 候选代码
三模型并发 → MiniMax + GLM-5 + Kimi
    │
    ▼ 加权评分排序
第5层: ai_select_top_reits() → Top 5 推荐
    │
    ▼
写入数据库 (reit_weekly_picks 表)
    │
    ▼ 异步
回测计算 (1/3/6个月) + 三模型评价 → reit_backtests 表
```

---

## 3. 5 层筛选策略详解

### 3.1 第1层：分红率筛选

**核心逻辑**：C-REITs 的投资价值核心在于分红收益。本层通过分红率区间筛选，优选稳定分红且收益率合理的产品。

```
参数设定：
  - 硬性范围: 3% ~ 10%（超出范围直接剔除）
  - 优选范围: 5% ~ 8%（在此区间内的标记为"优选"）
```

**设计考量**：
- 分红率过低（<3%）意味着底层资产收益不佳
- 分红率过高（>10%）可能暗示价格已经大幅下跌（分红率=分红/价格）
- 5%-8% 是 C-REITs 市场中较为稳健的分红区间
- 新上市的 REITs（无分红数据）默认保留，避免错杀

**对应函数**：`filter_by_dividend_yield()`

```python
# 核心判断逻辑
for code in reit_codes:
    dy = dividend_data.get(code)
    if dy is None:
        passed.append(code)      # 无数据默认保留
    elif min_yield <= dy <= max_yield:
        passed.append(code)      # 在3%-10%范围内通过
        if preferred_min <= dy <= preferred_max:
            preferred.append(code) # 在5%-8%优选范围
    else:
        removed.append(code)      # 超出范围剔除
```

### 3.2 第2层：收入环比下降剔除

**核心逻辑**：底层资产的运营收入是 REITs 分红的来源。如果收入持续下降，说明底层资产运营恶化，未来分红可能缩水。

```
判定标准：
  - 取最近4个季度的收入数据
  - 计算环比变化次数
  - 如果 ≥75% 的季度出现环比下降 → 剔除
```

**设计考量**：
- 使用75%阈值而非100%，是为了容忍季节性波动
- 仅看最近4个季度（1年），因为更早的数据参考价值递减
- 数据不足（<2个季度）的默认保留

**对应函数**：`filter_by_income_decline()`

### 3.3 第3层：换手率为零剔除

**核心逻辑**：流动性是投资的基本前提。如果一只 REITs 连续多日无成交，投资者将面临无法退出的风险。

```
判定标准：
  - 检查最近10个交易日（2周）的成交量
  - 如果全部为0 → 剔除
```

**设计考量**：
- 2周=10个交易日是一个合理的流动性观察窗口
- 部分小规模 REITs 确实可能出现间歇性零成交
- 历史行情数据来自 iFinD，如果获取失败则默认保留

**并发获取优化**：本层需要逐只获取 30 日历史行情数据，为避免串行请求耗时过长，引入模块级线程池 `ThreadPoolExecutor(max_workers=8)` 并发获取：

```python
_HISTORY_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="reit_hist")

def _fetch_history_safe(code: str, days: int = 30):
    """线程安全的历史行情获取（供线程池调用）"""
    try:
        return code, ifind_client.fetch_reit_history(code, days=days)
    except Exception:
        return code, None

# run_full_screening() 中并发获取：
loop = asyncio.get_event_loop()
futures = [
    loop.run_in_executor(_HISTORY_EXECUTOR, _fetch_history_safe, code, 30)
    for code in codes
]
results = await asyncio.gather(*futures)
```

60 只 REITs 从串行 ~180 秒 → 并发 ~30 秒，性能提升约 **6 倍**。获取到的历史行情数据同时也为第5层 AI 评选提供量化指标输入。

**对应函数**：`filter_by_zero_turnover()`

### 3.4 第4层：负面舆情剔除（三模型投票）

**核心逻辑**：利用 AI 大模型的知识库，判断 REITs 是否存在重大负面消息。

**负面情况清单**：
1. 基础资产出现重大问题（停产、关闭、安全事故）
2. 管理人重大违规或处罚
3. 分配金额大幅下降或暂停分红
4. 底层资产被诉讼/查封
5. 其他重大利空

**三模型投票机制**：

```
MiniMax M2.5  ──┐
                 ├──→ 投票汇总 ──→ 多数判定
GLM-5        ──┤      (>50% 认为负面才剔除)
                 │
Kimi K2.5    ──┘
```

```python
# 投票决策核心逻辑
for code in reit_codes:
    votes = all_negatives.get(code, [])
    negative_count = sum(1 for v in votes if v)
    total_votes = len(votes)
    
    # 多数投票：超过半数模型认为负面才剔除
    if negative_count > total_votes / 2:
        removed.append(code)
    else:
        passed.append(code)
```

**设计考量**：
- 单一模型可能存在幻觉（hallucination），误判正常REITs为负面
- 三模型投票可以有效降低误判率
- 如果模型不确定，应标注为非负面（保守策略，避免错杀）
- JSON 格式输出确保结构化解析

### 3.5 第5层：AI 综合评选 Top 5（三模型加权投票）

**核心逻辑**：从通过全部筛选的候选池中，由三大模型各自独立推荐，然后通过加权评分排序选出最终 Top 5。

#### 量化数据输入

AI 评选不仅依赖基础信息，还会从第3层已获取的历史行情中提取 6 个量化指标（通过 `_extract_market_data()` 函数），使模型能感知实时市场状态：

| 指标 | 字段名 | 说明 |
|------|--------|------|
| 日均换手率 | `avg_turnover` | 近 10 日日均成交量（百万级） |
| 近5日涨跌幅 | `chg_5d` | 短期趋势（%） |
| 近20日涨跌幅 | `chg_20d` | 中期趋势（%） |
| 30日最高价 | `price_high` | 价格区间上沿 |
| 30日最低价 | `price_low` | 价格区间下沿 |
| 最新价 | `latest_price` | 当前价格 + 计算区间位置 |

传入 AI 的 prompt 示例：
```
- 508000 华安张江光大REIT | 类型: 产业园 | 分红率: 6.5% | 日均换手率0.12%, 5日涨跌+1.20%, 20日涨跌-0.50%, 30日区间位置62%
```

同时还会向 AI 展示候选池的**类型分布统计**（如"产业园(12只), 仓储物流(5只), ..."），引导模型注重多元化选择。

#### 评选标准（5维权重）

| 维度 | 权重 | 说明 |
|------|------|------|
| 分红率稳健性 | **30%** | 优选5-8%区间 |
| 类型多元化 | **25%** | 须覆盖≥3种不同类型 |
| 流动性 | **15%** | 优选日均换手率较高的品种 |
| 近期走势 | **15%** | 优选走势温和、非极端位置的品种 |
| 底层资产质量 | **15%** | 头部管理人、运营稳定 |

#### 三模型加权投票算法

```python
# 每个模型给出自己的Top 5推荐（含score和排名）
# score 被约束在 60-100 范围内，防止异常值
score = min(max(p.get("score", 75), 60), 100)

# 对每只被推荐的REITs计算加权得分：
weighted_score = (score * 0.75 + rank_bonus * 100 * 0.25) * model_weight

# 其中：
# - score: 模型给出的评分，限制在60-100范围
# - rank_bonus: 排名越靠前越高 (top_n - rank) / top_n
# - model_weight: 模型权重 (MiniMax 40%, GLM 30%, Kimi 30%)
# - 以模型评分为主导（75%），降低排名对最终结果的干扰（25%）
```

#### 共识加分机制

被多个模型同时推荐的 REITs 获得额外加分，体现"跨模型共识"的价值：

```python
# 仅在有≥2个模型参与时生效
active_models = len([w for w in task_weights if w > 0])
for code in code_scores:
    model_count = code_model_count.get(code, 0)
    if model_count >= 2 and active_models >= 2:
        consensus_bonus = 0.10 if model_count == 2 else 0.20  # 2票+10%，3票+20%
        code_scores[code] *= (1 + consensus_bonus)

# 全票推荐的 REITs 在 reason 前标注 [全票推荐]
```

多个独立模型从不同角度评估后同时推荐同一只 REITs，说明该品种的投资价值获得了跨模型验证。全票推荐（3/3 模型一致）获得最高 20% 的加分奖励。

最终按加权总分降序排列，取 Top 5。

#### 降级策略

如果所有模型调用失败，使用 `_fallback_select()` 进行两轮选择，确保类型多元化：

```
第一轮: 按分红率排序后，每种类型各选1只（确保类型覆盖≥3种）
第二轮: 剩余名额按分红率排序填充

评分规则: 分红率在5-8%优选区间的REITs获得+5分额外加分
         （即分红率6%的品种评分为6+5=11，优先于分红率9%的品种评分9）
```

降级场景下仍能保证类型多元化，且优选区间品种获得合理优先权。

---

## 4. 回测评价机制

### 4.1 收益率计算

对每只被推荐的 REITs，从推荐日期（pick_date）买入，计算不同持有期的收益率：

```python
# 1个月收益率
target_1m = pick_date + 30天
return_1m = (price_at_target / price_at_pick - 1) * 100%

# 3个月收益率
target_3m = pick_date + 90天
return_3m = (price_at_target / price_at_pick - 1) * 100%

# 6个月收益率
target_6m = pick_date + 180天
return_6m = (price_at_target / price_at_pick - 1) * 100%
```

**注意事项**：
- 如果目标日期是非交易日，取该日期之后最近一个交易日的收盘价
- 如果距今未满对应期限，该收益率返回 `null`
- 使用收盘价（close）计算

### 4.2 AI 回测评价

三模型联合给出回测表现的专业评价，评价维度：
1. 整体收益表现（是否跑赢同期中证REITs指数）
2. 收益稳定性（各品种表现分化程度）
3. 不同持有期的收益特征
4. 改进建议

每个模型的评价会带上模型标签（如 `【MiniMax评价】`、`【GLM-5评价】`），方便对比各模型观点。

---

## 5. 新增代码文件详解

### 5.1 `backend/app/reits_list.py` — REITs 清单

**职责**：维护中国公募 REITs 完整清单。

**数据结构**：
```python
CREITS_LIST = [
    {"code": "180101", "name": "博时蛇口产园REIT", "sector": "产业园"},
    {"code": "508000", "name": "华安张江光大REIT", "sector": "产业园"},
    # ... 共82只
]
```

**字段说明**：
| 字段 | 说明 |
|------|------|
| `code` | REITs代码（不含后缀，如 `180101`、`508000`） |
| `name` | 产品全称 |
| `sector` | 资产类型（产业园/交通/仓储物流/保障性住房/消费基础设施/能源/生态环保/水利） |

**资产类型分布**：
| 类型 | 数量 | 代表产品 |
|------|------|----------|
| 产业园 | 17只 | 博时蛇口产园、华安张江光大、东吴苏园产业 |
| 交通 | 15只 | 华夏中国交建、中金安徽交控、浙商沪杭甬 |
| 消费基础设施 | 15只 | 嘉实物美消费、华夏首创奥莱、华夏金茂购物中心 |
| 保障性住房 | 8只 | 华夏北京保障房、中金厦门安居、红土深圳安居 |
| 仓储物流 | 7只 | 中金普洛斯、红土盐田港、嘉实京东仓储 |
| 能源 | 6只 | 鹏华深圳能源、中航京能光伏、中信建投国电投新能源 |
| 生态环保 | 3只 | 中航首钢绿能、富国首创水务 |
| 水利 | 2只 | 中信建投国家电投新能源 |

**iFinD 代码转换**：
REITs 代码在 `ifind_client.py` 中通过 `to_ifind_code()` 函数转换：
- `180xxx` → `180xxx.OF`（场外基金）
- `508xxx` → `508xxx.SH`（场内基金，上交所）

### 5.2 `backend/app/reits_engine.py` — 筛选引擎

**职责**：实现5层筛选策略 + 回测计算 + AI评价。

**模块结构**：

```
reits_engine.py
├── filter_by_dividend_yield()    # 第1层：分红率筛选
├── filter_by_income_decline()    # 第2层：收入环比筛选
├── filter_by_zero_turnover()     # 第3层：换手率筛选
├── filter_by_sentiment()         # 第4层：负面舆情筛选（三模型投票）
├── ai_select_top_reits()         # 第5层：AI综合评选（三模型加权）
├── _fallback_select()            # 降级选择（按分红率排序）
├── run_full_screening()          # 完整筛选流水线（串联5层）
├── evaluate_backtest()           # AI回测评价（三模型联合）
└── calculate_returns()           # 单只REITs收益率计算
```

**关键设计决策**：

| 决策 | 原因 |
|------|------|
| 5层串行而非并行 | 每层的输入依赖上一层的输出（漏斗模式） |
| 舆情用投票而非加权 | 舆情是二元判断（有/无负面），投票比加权更合理 |
| 评选用加权排序 | 评选需要考虑排名和分数的综合权重 |
| 降级策略返回分红率排序 | 分红率是C-REITs最核心的指标 |

**输入输出**：

```python
# 输入
all_reits: List[Dict]  # [{code, name, sector}, ...]
top_n: int = 5          # 推荐数量

# 输出
{
    "picks": [           # 推荐列表
        {
            "code": "508000",
            "name": "华安张江光大REIT",
            "sector": "产业园",
            "dividend_yield": 6.5,
            "reason": "分红稳定，底层资产优质",
            "score": 85
        },
        ...
    ],
    "filter_log": {      # 每层筛选后剩余数量
        "total": 82,
        "after_dividend": 65,
        "after_income": 58,
        "after_turnover": 55,
        "after_sentiment": 52,
        "final": 5
    },
    "model_source": "MiniMax M2.5 + GLM-5 + Kimi K2.5"
}
```

### 5.3 `backend/app/models.py` — 新增4张表

**REITItem（reit_items 表）**：存储REITs基础信息
```python
class REITItem(Base):
    __tablename__ = "reit_items"
    id       = Column(Integer, primary_key=True)
    code     = Column(String(20), unique=True, index=True)  # REITs代码
    name     = Column(String(100))                           # 产品名称
    sector   = Column(String(50))                            # 资产类型
    is_active = Column(Integer, default=1)                   # 是否启用
    created_at = Column(DateTime, default=datetime.now)
```

**REITPrice（reit_prices 表）**：存储REITs历史行情
```python
class REITPrice(Base):
    __tablename__ = "reit_prices"
    id     = Column(Integer, primary_key=True)
    code   = Column(String(20), index=True)
    date   = Column(Date, index=True)
    open   = Column(Float)
    high   = Column(Float)
    low    = Column(Float)
    close  = Column(Float)
    volume = Column(Float)
```

**REITWeeklyPick（reit_weekly_picks 表）**：存储每周推荐结果
```python
class REITWeeklyPick(Base):
    __tablename__ = "reit_weekly_picks"
    id           = Column(Integer, primary_key=True)
    week_start   = Column(Date, index=True)      # 推荐周的周一日期
    week_end     = Column(Date)                    # 推荐周的周五日期
    picks_json   = Column(Text)                    # 推荐列表JSON
    filter_log   = Column(Text)                    # 筛选日志JSON
    model_source = Column(String(200))             # 使用的模型
    created_at   = Column(DateTime, default=datetime.now)
```

**REITBacktest（reit_backtests 表）**：存储回测结果
```python
class REITBacktest(Base):
    __tablename__ = "reit_backtests"
    id         = Column(Integer, primary_key=True)
    pick_id    = Column(Integer, index=True)       # 关联的weekly_pick ID
    code       = Column(String(20))                 # REITs代码
    name       = Column(String(100))                # 产品名称
    pick_date  = Column(Date)                       # 推荐日期
    return_1m  = Column(Float)                      # 1个月收益率(%)
    return_3m  = Column(Float)                      # 3个月收益率(%)
    return_6m  = Column(Float)                      # 6个月收益率(%)
    evaluation = Column(Text)                       # AI评价文本
    updated_at = Column(DateTime, default=datetime.now)
```

### 5.4 `backend/app/schemas.py` — 新增响应模型

```python
# REITs 基础信息
class REITItemOut(BaseModel):
    code: str
    name: str
    sector: str

# 筛选日志
class REITFilterLog(BaseModel):
    total: int
    after_dividend: Optional[int]
    after_income: Optional[int]
    after_turnover: Optional[int]
    after_sentiment: Optional[int]
    final: int

# 单只推荐项
class REITPickItem(BaseModel):
    code: str
    name: str
    sector: str
    dividend_yield: Optional[float]
    reason: str
    score: int

# 每周推荐响应
class REITWeeklyPickOut(BaseModel):
    week_start: str
    week_end: str
    picks: List[REITPickItem]
    filter_log: REITFilterLog
    model_source: str
    created_at: Optional[str]

# 回测响应
class REITBacktestItem(BaseModel):
    code: str
    name: str
    pick_date: str
    return_1m: Optional[float]
    return_3m: Optional[float]
    return_6m: Optional[float]

class REITBacktestOut(BaseModel):
    pick_id: int
    items: List[REITBacktestItem]
    evaluation: Optional[str]
```

### 5.5 `backend/app/ifind_client.py` — iFinD 扩展

新增4个 REITs 专用数据获取函数：

| 函数 | 说明 |
|------|------|
| `fetch_reit_history(code, days)` | 获取单只REITs历史行情（OHLCV） |
| `fetch_reit_realtime(codes)` | 批量获取REITs实时行情（价格、涨跌幅、成交量） |
| `fetch_reit_dividend_yield(codes)` | 批量获取REITs分红率（年化） |
| `fetch_reit_income_trend(codes)` | 获取REITs底层资产收入趋势（季度数据） |

**代码转换**：
`to_ifind_code()` 函数新增 `market="REIT"` 支持：

```python
def to_ifind_code(code: str, market: str = "") -> str:
    if market == "REIT" or code.startswith("18") or code.startswith("50"):
        if code.startswith("18"):
            return f"{code}.OF"   # 场外基金
        elif code.startswith("508"):
            return f"{code}.SH"   # 上交所场内
    # ... 其他市场逻辑
```

### 5.6 `backend/app/api.py` — 新增7个路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/reits/list` | GET | 返回82只REITs清单（含实时行情） |
| `/api/reits/sectors` | GET | 返回各类型REITs统计 |
| `/api/reits/weekly-picks` | GET | 返回最新一期每周推荐 |
| `/api/reits/generate-picks` | POST | 手动触发生成推荐（管理员） |
| `/api/reits/weekly-picks/history` | GET | 历史推荐列表 |
| `/api/reits/backtest` | GET | 回测结果 |
| `/api/reits/price-history/{code}` | GET | 单只REITs历史行情 |

**核心内部函数**：

```python
async def _generate_reit_weekly_picks():
    """生成本周REITs推荐（调用 reits_engine.run_full_screening）"""
    
async def _update_reit_backtests():
    """更新回测数据（计算收益率 + AI评价）"""
```

### 5.7 `backend/app/database.py` — 数据库迁移

新增 `_migrate_reits_tables()` 函数，在应用启动时自动创建4张REITs相关表：

```python
async def _migrate_reits_tables():
    """自动创建 reit_items, reit_prices, reit_weekly_picks, reit_backtests 表"""
    async with engine.begin() as conn:
        # 使用 CREATE TABLE IF NOT EXISTS 确保幂等
        for table in [REITItem, REITPrice, REITWeeklyPick, REITBacktest]:
            await conn.run_sync(table.__table__.create, checkfirst=True)
```

### 5.8 `backend/main.py` — 启动初始化 + 定时任务

```python
# 启动时初始化REITs清单到数据库
async def init_reits_list():
    """将 reits_list.py 中的82只REITs写入 reit_items 表"""
    
# 定时任务：每周日 01:05（紧随地产股评级刷新之后）
scheduler.add_job(
    generate_reit_weekly_picks,
    CronTrigger(day_of_week='sun', hour=1, minute=5),
    id='reits_weekly_picks',
)
```

### 5.9 `frontend/src/components/REITsSection.jsx` — 前端组件

**三个子Tab**：

1. **自选池 Tab**：
   - 82只REITs列表展示
   - 按类型分组筛选（产业园/交通/消费等）
   - 显示实时行情：最新价、涨跌幅、成交量
   - 支持代码/名称搜索

2. **每周推荐 Tab**：
   - 展示最新一期5只推荐
   - **漏斗可视化**：显示5层筛选每层剩余数量
   - 每只推荐展示：代码、名称、类型、分红率、推荐理由、评分
   - 模型来源标注
   - 支持查看历史推荐

3. **回测评价 Tab**：
   - 1/3/6个月收益率表格
   - 红色=盈利，绿色=亏损
   - AI三模型评价文本展示

### 5.10 `frontend/src/components/REITsMethodology.jsx` — 方法论组件

参考 `RatingMethodology.jsx` 的交互风格，为用户提供策略透明度。

**组件特性**：
- 标题："C-REITs 智能筛选模型说明"，副标题标注数据源（同花顺iFinD · 腾讯云三模型AI）
- 可折叠面板（默认收起，点击展开），不占用默认视觉空间
- 筛选流程总览：`分红率 → 收入趋势 → 流动性 → AI舆情 → AI综合评选` 可视化箭头
- 四列详解：基本面筛选 / 流动性筛选 / AI舆情分析 / AI综合评选
- 底部注明运行频率："每周日凌晨1点自动运行"
- 降级保障机制说明

**集成位置**：`REITsSection.jsx` 的 Tab 栏下方、所有子 Tab 内容上方，对所有子页面生效。

### 5.11 `frontend/src/api.js` — 新增7个API方法

```javascript
// REITs 相关API
export const fetchREITsList = () => api.get('/api/reits/list');
export const fetchREITsSectors = () => api.get('/api/reits/sectors');
export const fetchREITsWeeklyPicks = () => api.get('/api/reits/weekly-picks');
export const generateREITsPicks = () => api.post('/api/reits/generate-picks');
export const fetchREITsPicksHistory = (limit) => api.get(`/api/reits/weekly-picks/history?limit=${limit}`);
export const fetchREITsBacktest = () => api.get('/api/reits/backtest');
export const fetchREITsPriceHistory = (code) => api.get(`/api/reits/price-history/${code}`);
```

### 5.12 `frontend/src/App.jsx` — 主应用集成

在 `BASE_TABS` 中新增 REITs Tab：

```jsx
const BASE_TABS = [
    { key: 'rating', label: 'AI评级' },
    { key: 'watchlist', label: '自选股' },
    { key: 'reits', label: 'REITs' },     // 🆕
    { key: 'commentary', label: '市场点评' },
    { key: 'report', label: '研究报告' },
];
```

---

## 6. 三模型联合决策机制

### 6.1 模型配置

| 模型 | 权重 | 特点 |
|------|------|------|
| MiniMax M2.5 | 40% | 最新发布，综合能力强，支持联网搜索 |
| GLM-5 | 30% | 智谱AI旗舰模型，中文理解能力优秀 |
| Kimi K2.5 | 30% | Moonshot AI模型，长文本推理能力强 |

### 6.2 舆情判断：投票制

```
模型输出: {"code": "508000", "negative": true/false, "reason": "..."}

投票规则: 
  - 3个模型都参与 → 2票以上为负面才剔除
  - 2个模型参与 → 2票为负面才剔除（全票通过）
  - 1个模型参与 → 该模型判断为准
  
设计原则: 宁可错留，不可错杀（保守策略）
```

### 6.3 综合评选：加权排序制 + 共识加分

```
每个模型独立给出 Top N 推荐列表（含 code, reason, score）

对于每只被推荐的 REITs:
  score = min(max(score, 60), 100)  // 限制在60-100，防异常值
  weighted_score = Σ (score × 0.75 + rank_bonus × 100 × 0.25) × model_weight

其中:
  score = 模型给出的评分 (60-100)
  rank_bonus = (N - rank) / N，排名越靠前越高
  model_weight = MiniMax 0.4 / GLM 0.3 / Kimi 0.3

共识加分:
  被2个模型同时推荐 → 总分 +10%
  被3个模型同时推荐 → 总分 +20%（标注 [全票推荐]）

最终按 weighted_score 降序排列，取 Top 5
```

### 6.4 回测评价：并行展示

回测评价不做分数融合（文本不适合加权），而是将三个模型的评价并行展示：

```
【MiniMax评价】
整体来看，本期推荐组合1个月收益率表现...

【GLM-5评价】
从回测数据分析，推荐的5只REITs中...

【Kimi评价】
综合评价本期推荐组合表现...
```

---

## 7. 定时任务

| 任务 | 时间 | 说明 |
|------|------|------|
| `generate_reit_weekly_picks` | 每周日 01:05 | 执行5层筛选 + 生成Top 5推荐（紧随地产股评级刷新之后） |
| `update_reit_backtests` | 推荐生成后异步触发 | 计算1/3/6月收益率 + AI评价 |

任务执行逻辑：
1. 从 `reits_list.py` 加载 82 只 REITs
2. 调用 `run_full_screening()` 执行 5 层筛选
3. 将结果写入 `reit_weekly_picks` 表
4. 异步触发 `_update_reit_backtests()` 计算历史推荐的回测

---

## 8. 与现有系统的集成方式

### 8.1 数据层集成
- 共享 SQLite 数据库（`data/realestate.db`），通过 `database.py` 统一管理连接
- 使用相同的 `ifind_client.py`，通过 `to_ifind_code()` 的 `market="REIT"` 参数区分

### 8.2 AI 模型层集成
- 共享 `llm_client.py` 的三模型客户端（`chat_minimax` / `chat_glm` / `chat_kimi`）
- 共享 `config.py` 的模型配置和权重

### 8.3 前端层集成
- 在 `App.jsx` 的 Tab 导航中新增 REITs 入口
- `REITsSection.jsx` 作为独立组件，不影响其他页面
- 共享全局样式和组件风格

### 8.4 调度层集成
- 在 `main.py` 的 APScheduler 中新增定时任务
- 与现有的评级刷新、日报生成、周报生成任务共存
- 错开执行时间避免资源竞争

---

## 9. 未来扩展方向

1. **REITs 专属评级模型**：参考股票评级引擎，为 REITs 设计专属的量化+AI评级体系
2. **REITs 指数对比**：引入中证REITs指数作为回测基准
3. **REITs 日报/周报**：定期生成 C-REITs 市场分析报告
4. **分红日历**：追踪各 REITs 的分红日期和金额
5. **底层资产分析**：深入分析 REITs 底层资产的运营数据（出租率、单位租金等）
6. **组合优化**：基于现代投资组合理论，优化 REITs 组合配置

---

## 10. 策略有效性验证

> 本章说明筛选策略的设计逻辑为何有效，以及策略的适用场景与局限性。

### 10.1 策略有效性的理论基础

本策略的 5 层漏斗筛选设计，每一层都有明确的金融逻辑支撑：

| 层级 | 筛选维度 | 有效性依据 |
|------|----------|-----------|
| **第1层** 分红率 | 优选 5-8%，允许 3-10% | C-REITs 强制分红≥90%，分红率是衡量底层资产收益能力的核心指标。过低说明资产收益不佳，过高可能是价格已大幅下跌的反映 |
| **第2层** 收入趋势 | 剔除连续环比下降 | 底层运营收入是分红的来源，收入持续下滑意味着未来分红可能缩水，属于前瞻性风险指标 |
| **第3层** 流动性 | 剔除零换手率 | 流动性是投资的基本前提，无法成交的品种面临严重的退出风险 |
| **第4层** 舆情 | 三模型投票剔除负面 | 重大负面事件（资产问题、管理人违规、诉讼等）可能导致价值大幅缩水，AI 多模型投票降低误判率 |
| **第5层** 综合评选 | 三模型加权排序 + 共识加分 | 融合量化数据与 AI 判断，多模型共识机制提高选股可靠性 |

### 10.2 策略适用场景

本策略核心思想是**"高分红 + 低风险 + AI 增强"**，适用于以下场景：

1. **中长期持有**：C-REITs 是分红导向资产，短期价格波动不改变其内在分红价值，策略更适合以月度/季度为持有周期
2. **稳健配置需求**：策略选出的品种集中于分红率稳定、流动性充足、运营良好的优质 REITs，适合作为固收+组合的底仓配置
3. **分散化投资**：类型多元化约束（至少覆盖 3 种资产类型）降低了单一行业风险

### 10.3 策略核心优势

1. **基本面驱动**：以分红率为核心锚点，不追逐短期价格波动，符合 REITs 的"类固收"投资属性
2. **多层风控**：5 层串行筛选逐步过滤风险品种，负面舆情层通过三模型投票进一步降低"踩雷"概率
3. **AI 增强选股**：在量化筛选基础上，引入三大模型（MiniMax M2.5 + GLM-5 + Kimi K2.5）联合评选，利用 AI 的知识广度弥补纯量化模型的不足
4. **共识机制可靠**：被多个独立模型同时推荐的品种获得共识加分，跨模型一致看好意味着更高的投资确定性
5. **降级保障**：当 AI 模型不可用时，自动降级为分红率+类型多元化的量化选择，确保系统可用性

### 10.4 已知局限性

| 局限 | 说明 | 缓解措施 |
|------|------|----------|
| **分红率时效性** | 使用最新分红率数据，历史时点可能存在差异 | 未来可引入分红率快照机制 |
| **AI 模型知识时效** | 大模型的训练数据有截止日期，对最新事件响应有延迟 | 舆情层仅做负面排除，不依赖 AI 做精确预测 |
| **REITs 品种有限** | 当前市场仅 82 只 C-REITs，候选池较小 | 类型多元化约束避免过度集中 |
| **低波动资产特性** | REITs 日波动率较低，短期超额收益空间有限 | 策略定位为中长期配置工具，非短线交易 |

### 10.5 未来优化方向

| 方向 | 描述 | 预期效果 |
|------|------|----------|
| **动态分红率快照** | 定期记录各 REITs 分红率历史数据 | 提升筛选的时效准确性 |
| **扩大类型覆盖权重** | 对保障性住房、消费基础设施等新兴类型适当倾斜 | 降低类型集中度 |
| **引入动量因子** | 在综合评分中加入近 60 日涨幅因子 | 捕捉中期趋势，提升选股时效性 |
| **风控止损机制** | 持有期内单只跌幅超 -5% 触发预警 | 控制极端行情下的最大回撤 |
| **调仓频率优化** | 改为双周调仓，提高对市场变化的响应速度 | 提升策略灵活性 |

---

*文档版本: v1.3 | 最后更新: 2026-04-05*
