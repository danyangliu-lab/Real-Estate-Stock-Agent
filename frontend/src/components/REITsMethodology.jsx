import React, { useState } from 'react'

export default function REITsMethodology() {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="methodology-card">
      <div
        className="methodology-header"
        onClick={() => setExpanded(e => !e)}
      >
        <div className="methodology-title-row">
          <span className="methodology-icon">&#x1f3e2;</span>
          <span className="methodology-title">C-REITs 智能筛选模型说明</span>
          <span className="methodology-powered">Powered by 同花顺iFinD · 腾讯云三模型AI</span>
        </div>
        <span className={`methodology-arrow ${expanded ? 'expanded' : ''}`}>&#x25B6;</span>
      </div>

      {expanded && (
        <div className="methodology-body">
          <REITsScreeningMethodology />
        </div>
      )}
    </div>
  )
}

function REITsScreeningMethodology() {
  return (
    <>
      {/* 筛选流程总览 */}
      <div className="methodology-formula">
        <span className="formula-label">5层漏斗筛选</span>
        <span className="formula-eq">:</span>
        <span className="formula-part" style={{ color: '#059669' }}>分红率</span>
        <span className="formula-plus">→</span>
        <span className="formula-part" style={{ color: '#0284c7' }}>收入趋势</span>
        <span className="formula-plus">→</span>
        <span className="formula-part" style={{ color: '#7c3aed' }}>流动性</span>
        <span className="formula-plus">→</span>
        <span className="formula-part" style={{ color: '#db2777' }}>AI舆情</span>
        <span className="formula-plus">→</span>
        <span className="formula-part ai">AI综合评选</span>
      </div>
      <div className="methodology-fallback">
        82只C-REITs全覆盖 → 5层逐步过滤 → 最终关注Top 5；三模型(MiniMax M2.5+GLM-5+Kimi K2.5)投票决策；每周日凌晨1点自动运行
      </div>

      <div className="methodology-columns">
        {/* 列1: 第1-2层 量化筛选 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot" style={{ background: '#059669' }} />
            第1-2层: 基本面筛选
            <span className="ifind-badge-sm">iFinD</span>
          </div>
          <div className="methodology-col-desc">
            基于iFinD数据，从分红率和收入趋势两个维度进行硬性筛选
          </div>
          <div className="dimension-list">
            <DimensionItem
              name="分红率筛选"
              weight="第1层"
              desc="硬性范围3-10%，优选5-8%区间。分红率过低说明底层资产收益不佳，过高可能暗示价格暴跌"
            />
            <DimensionItem
              name="三级降级策略"
              weight="数据源"
              desc="① iFinD基金指标 → ② 日频序列 → ③ 历史行情除权缺口估算，确保数据可用性"
            />
            <DimensionItem
              name="收入环比剔除"
              weight="第2层"
              desc="取最近4个季度收入数据，若≥75%季度环比下降则剔除（底层资产运营恶化信号）"
            />
          </div>
        </div>

        {/* 列2: 第3层 流动性 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot" style={{ background: '#7c3aed' }} />
            第3层: 流动性筛选
            <span className="ifind-badge-sm">iFinD</span>
          </div>
          <div className="methodology-col-desc">
            基于iFinD历史行情数据，8线程并发获取，筛除流动性不足的品种
          </div>
          <div className="dimension-list">
            <DimensionItem
              name="零换手率剔除"
              weight="核心"
              desc="检查最近10个交易日（2周）的成交量，全部为0则剔除——无法退出的品种不纳入关注"
            />
            <DimensionItem
              name="市场数据提取"
              weight="增强"
              desc="同时提取日均换手率、5/20日涨跌幅、30日价格区间等指标，传递给第5层AI评选"
            />
          </div>
        </div>

        {/* 列3: 第4层 舆情 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot" style={{ background: '#db2777' }} />
            第4层: AI舆情分析
          </div>
          <div className="methodology-col-desc">
            三大模型并发分析REITs负面舆情，投票决策
          </div>
          <div className="dimension-list">
            <DimensionItem
              name="负面事件检测"
              weight="5类"
              desc="底层资产问题 · 管理人违规 · 分配下降/暂停 · 诉讼查封 · 其他重大利空"
            />
            <DimensionItem
              name="三模型投票"
              weight="机制"
              desc="MiniMax M2.5 + GLM-5 + Kimi K2.5各自独立判断，超过半数认为负面才剔除"
            />
            <DimensionItem
              name="保守策略"
              weight="原则"
              desc="宁可错留、不可错杀。不确定时标注为非负面，单一模型幻觉不会导致误判"
            />
          </div>
        </div>

        {/* 列4: 第5层 AI评选 */}
        <div className="methodology-col">
          <div className="methodology-col-title">
            <span className="col-dot ai-dot" />
            第5层: AI综合评选
          </div>
          <div className="methodology-col-desc">
            三模型独立评选+加权融合+共识加分，输出最终Top 5
          </div>
          <div className="dimension-list">
            <DimensionItem
              name="量化数据输入"
              weight="增强"
              desc="向AI提供分红率、日均换手率、5/20日涨跌幅、30日价格区间位置等量化指标"
            />
            <DimensionItem
              name="5维选择标准"
              weight="权重"
              desc="分红率稳健30% · 类型多元化25% · 流动性15% · 近期走势15% · 底层资产质量15%"
            />
            <DimensionItem
              name="加权融合评分"
              weight="算法"
              desc="模型评分×75% + 排名加分×25%，按MiniMax(40%)/GLM(30%)/Kimi(30%)加权"
            />
            <DimensionItem
              name="共识加分"
              weight="机制"
              desc="被2个模型同时选中+10%，3个模型全票选中+20%，多模型共识更可靠"
            />
          </div>
        </div>
      </div>

      {/* 回测评价说明 */}
      <div style={{
        marginTop: 16,
        padding: '12px 16px',
        background: 'var(--bg-secondary, #f9fafb)',
        borderRadius: 8,
        border: '1px solid var(--border, #e5e7eb)',
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: 'var(--text-primary)' }}>
          📈 回测评价机制
        </div>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
          每期关注列表自动计算1/3/6个月收益率（关注日买入收盘价，目标日最近交易日收盘价）。
          三模型联合生成回测评价，从收益表现、稳定性、持有期特征和改进建议四个维度进行分析。
        </div>
      </div>

      {/* 降级策略说明 */}
      <div style={{
        marginTop: 12,
        padding: '12px 16px',
        background: '#fffbeb',
        borderRadius: 8,
        border: '1px solid #fde68a',
      }}>
        <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, color: '#92400e' }}>
          🛡️ 降级保障机制
        </div>
        <div style={{ fontSize: 12, color: '#a16207', lineHeight: 1.6 }}>
          <strong>数据降级</strong>：分红率获取支持三级降级（iFinD指标→日频序列→历史行情估算），确保数据可用性。
          <br />
          <strong>AI降级</strong>：若所有模型调用失败，自动切换为分红率+类型多元化的量化排序选择，保证关注列表输出。
          <br />
          <strong>筛选降级</strong>：各层数据不可用时自动跳过（全部保留），不会因数据缺失导致误杀。
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
