import React, { useState } from 'react'

export default function RatingMethodology({ modelType }) {
  const [expanded, setExpanded] = useState(false)
  const isSoochow = modelType === 'soochow'

  return (
    <div className="methodology-card">
      <div
        className="methodology-header"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="methodology-title-row">
          <span className="methodology-icon">&#x1f4d0;</span>
          <span className="methodology-title">{isSoochow ? '东吴地产选股逻辑说明' : '评级逻辑说明'}</span>
          <span className="methodology-powered">Powered by 同花顺iFinD · 腾讯云三模型AI</span>
        </div>
        <span className={`methodology-arrow ${expanded ? 'expanded' : ''}`}>&#x25B6;</span>
      </div>

      {expanded && (
        <div className="methodology-body">
          {isSoochow ? <SoochowMethodology /> : <QuantAIMethodology />}
        </div>
      )}
    </div>
  )
}

function QuantAIMethodology() {
  return (
    <>
      {/* 总公式 */}
      <div className="methodology-formula">
        <span className="formula-label">综合评分</span>
        <span className="formula-eq">=</span>
        <span className="formula-part quant">量化技术 × 25%</span>
        <span className="formula-plus">+</span>
        <span className="formula-part" style={{color:'#e67e22'}}>情绪因子 × 10%</span>
        <span className="formula-plus">+</span>
        <span className="formula-part" style={{color:'var(--green)'}}>基本面 × 15%</span>
        <span className="formula-plus">+</span>
        <span className="formula-part ai">AI大模型 × 50%</span>
      </div>
      <div className="methodology-fallback">AI采用MiniMax M2.5+GLM-5+Kimi K2.5三模型融合；情绪因子基于关键词+双速衰减+AI反馈；若基本面不可用则量化30%+情绪12%+AI58%</div>

      <div className="methodology-columns">
        {/* 列1: 量化 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot quant-dot" />
            量化技术评分 (25%)
          </div>
          <div className="methodology-col-desc">
            基于iFinD实时行情数据，6个量化维度综合评估，AI动态调整各维度权重
          </div>
          <div className="dimension-list">
            <DimensionItem name="趋势评分" weight="22%" desc="四级均线排列(MA5/10/20/60)、价格偏离度、MA20斜率、均线黏合度、ADX趋势强度" />
            <DimensionItem name="动量评分" weight="18%" desc="RSI双周期(6+14)、MACD信号+柱状体变化、KDJ随机指标、Williams %R、多周期涨跌幅" />
            <DimensionItem name="波动率评分" weight="12%" desc="年化波动率、布林带宽度+价格位置、ATR(14)相对波动、波动率收敛/发散趋势" />
            <DimensionItem name="成交量评分" weight="18%" desc="多级量比(5/10/20日)、OBV能量潮、VWAP偏离度、量价配合度、成交量趋势" />
            <DimensionItem name="价值评分" weight="18%" desc="区间位置连续评分、筹码集中度、多级支撑压力(10/20/60日)、价格动态区间" />
            <DimensionItem name="情绪评分" weight="12%" desc="量化维度内的情绪子分，基于关键词命中与衰减模型，详见情绪因子列" />
          </div>
        </div>

        {/* 列2: 情绪因子 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot" style={{background:'#e67e22'}} />
            情绪因子评分 (10%)
          </div>
          <div className="methodology-col-desc">
            基于房地产行业新闻与公告的舆情分析，量化市场情绪对股价的影响
          </div>
          <div className="dimension-list">
            <DimensionItem name="关键词匹配" weight="基础" desc="30个正面关键词(政策利好、销售回暖等) + 25个负面关键词(债务违约、暴雷等)加权匹配" />
            <DimensionItem name="双速衰减模型" weight="时效" desc="新闻类信息半衰期3天快速衰减、公告类信息半衰期7天缓慢衰减，越新影响越大" />
            <DimensionItem name="AI情绪反馈" weight="融合" desc="三模型AI分析结果反馈融入情绪评分，形成量化↔AI双向修正闭环" />
            <DimensionItem name="情绪评分范围" weight="0~100" desc="综合正负面关键词命中数、时间衰减权重、AI反馈，归一化到0-100分" />
          </div>
        </div>

        {/* 列3: 基本面 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot" style={{background:'var(--green)'}} />
            基本面评分 (15%)
            <span className="ifind-badge-sm">iFinD</span>
          </div>
          <div className="methodology-col-desc">
            基于同花顺iFinD实时数据，涵盖估值、资金面、市场情绪、盈利能力、交易活跃度五个维度
          </div>
          <div className="dimension-list">
            <DimensionItem name="核心估值" weight="50分" desc="PE(TTM)·PB(MRQ)·ROE·资产负债率(三道红线)" />
            <DimensionItem name="资金面" weight="20分" desc="主力净流入·量比·委比" />
            <DimensionItem name="市场情绪" weight="10分" desc="连涨/跌天数·振幅" />
            <DimensionItem name="盈利能力" weight="10分" desc="EPS每股收益" />
            <DimensionItem name="交易活跃度" weight="10分" desc="换手率·20日涨跌幅" />
          </div>
        </div>

        {/* 列4: AI */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot ai-dot" />
            AI大模型评分 (50%)
          </div>
          <div className="methodology-col-desc">
            由MiniMax M2.5+GLM-5+Kimi K2.5三模型融合，结合iFinD数据+实时联网搜索进行专业分析
          </div>
          <div className="dimension-list">
            <DimensionItem name="政策资讯影响" weight="35%" desc="最新房地产政策、调控文件、行业新闻、iFinD公告，实时联网获取" />
            <DimensionItem name="公司基本面" weight="30%" desc="经营质量、财务健康(三道红线)、土储质量、销售回款、管理层能力" />
            <DimensionItem name="技术面与资金面" weight="25%" desc="价格趋势、iFinD资金流向(主力/散户)、北向资金、筹码结构分析" />
            <DimensionItem name="风险评估" weight="10%" desc="债务违约风险、项目交付风险、系统性行业风险" />
          </div>
        </div>
      </div>

      {/* 评级映射 */}
      <div className="methodology-ratings">
        <div className="methodology-ratings-title">评级映射标准</div>
        <div className="rating-map-row">
          <RatingBadge label="优选" range="≥ 65分" cls="badge-strong-buy" />
          <RatingBadge label="关注" range="50-64分" cls="badge-buy" />
          <RatingBadge label="中性" range="35-49分" cls="badge-neutral" />
          <RatingBadge label="谨慎" range="< 35分" cls="badge-caution" />
        </div>
      </div>
    </>
  )
}

function SoochowMethodology() {
  return (
    <>
      {/* 总公式 */}
      <div className="methodology-formula">
        <span className="formula-label">综合评分</span>
        <span className="formula-eq">=</span>
        <span className="formula-part" style={{color:'var(--green)'}}>基本面 × 50%</span>
        <span className="formula-plus">+</span>
        <span className="formula-part ai">AI大模型 × 50%</span>
      </div>
      <div className="methodology-fallback">聚焦房地产行业基本面研究，重点关注宏观LPR利率、行业政策信号、个股财务三道红线、PB&lt;1估值安全边际</div>

      <div className="methodology-columns">
        {/* 左列: 基本面 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot" style={{background:'var(--green)'}} />
            基本面评分 (50%)
            <span className="ifind-badge-sm">iFinD</span>
          </div>
          <div className="methodology-col-desc">
            基于同花顺iFinD数据，聚焦房地产行业财务安全性与估值合理性
          </div>
          <div className="dimension-list">
            <DimensionItem name="三道红线" weight="30分" desc="资产负债率(<70%优秀)·净负债率·现金短债比，监管合规底线" />
            <DimensionItem name="估值安全边际" weight="30分" desc="PB(MRQ)破净加分·PE(TTM)合理区间·市值适中偏好" />
            <DimensionItem name="盈利质量" weight="20分" desc="ROE>8%优秀·EPS正值且增长·经营现金流健康" />
            <DimensionItem name="资金面" weight="20分" desc="主力净流入方向·量比活跃度·委比市场情绪" />
          </div>
        </div>

        {/* 右列: AI */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot ai-dot" />
            AI大模型评分 (50%)
          </div>
          <div className="methodology-col-desc">
            由DeepSeek V3.2+GLM-5+Kimi K2.5三模型融合，结合iFinD数据+实时联网搜索，聚焦地产行业深度分析
          </div>
          <div className="dimension-list">
            <DimensionItem name="宏观政策" weight="30%" desc="LPR利率走势·房地产调控政策·货币/财政政策方向·城镇化/户籍改革" />
            <DimensionItem name="行业信号" weight="25%" desc="百强房企销售排名·土地市场热度·竣工/新开工数据·二手房成交量" />
            <DimensionItem name="公司财务" weight="25%" desc="三道红线合规·销售回款率·土储质量·融资成本·债务到期" />
            <DimensionItem name="估值与风险" weight="20%" desc="PB破净安全边际·股息率·信用评级·交付风险·系统性风险" />
          </div>
        </div>
      </div>

      {/* 评级映射 */}
      <div className="methodology-ratings">
        <div className="methodology-ratings-title">评级映射标准</div>
        <div className="rating-map-row">
          <RatingBadge label="优选" range="≥ 65分" cls="badge-strong-buy" />
          <RatingBadge label="关注" range="50-64分" cls="badge-buy" />
          <RatingBadge label="中性" range="35-49分" cls="badge-neutral" />
          <RatingBadge label="谨慎" range="< 35分" cls="badge-caution" />
        </div>
      </div>
    </>
  )
}

function DimensionItem({ name, weight, desc }) {
  return (
    <div className="dimension-item">
      <div className="dimension-name">
        {name}
        {weight && <span className="dimension-weight">{weight}</span>}
      </div>
      <div className="dimension-desc">{desc}</div>
    </div>
  )
}

function RatingBadge({ label, range, cls }) {
  return (
    <div className="rating-map-item">
      <span className={`badge ${cls}`}>{label}</span>
      <span className="rating-map-range">{range}</span>
    </div>
  )
}
