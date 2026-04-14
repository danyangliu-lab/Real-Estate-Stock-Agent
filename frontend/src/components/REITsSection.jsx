import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api'
import REITsMethodology from './REITsMethodology'

// 类型颜色映射
const SECTOR_COLORS = {
  '产业园': { bg: '#dbeafe', color: '#1e40af', border: '#93c5fd' },
  '仓储物流': { bg: '#dcfce7', color: '#166534', border: '#86efac' },
  '保障性住房': { bg: '#fef3c7', color: '#92400e', border: '#fcd34d' },
  '消费基础设施': { bg: '#fce7f3', color: '#9d174d', border: '#f9a8d4' },
  '能源': { bg: '#ffedd5', color: '#9a3412', border: '#fdba74' },
  '交通': { bg: '#e0e7ff', color: '#3730a3', border: '#a5b4fc' },
  '生态环保': { bg: '#d1fae5', color: '#065f46', border: '#6ee7b7' },
  '数据中心': { bg: '#ede9fe', color: '#5b21b6', border: '#c4b5fd' },
}

const DEFAULT_SECTOR = { bg: '#f3f4f6', color: '#4b5563', border: '#d1d5db' }

function SectorTag({ sector }) {
  const c = SECTOR_COLORS[sector] || DEFAULT_SECTOR
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 12,
      fontSize: 11,
      fontWeight: 500,
      background: c.bg,
      color: c.color,
      border: `1px solid ${c.border}`,
    }}>
      {sector}
    </span>
  )
}

function ChangeTag({ value }) {
  if (value == null) return <span style={{ color: '#9ca3af' }}>--</span>
  const isUp = value > 0
  const isFlat = value === 0
  return (
    <span style={{
      color: isFlat ? '#6b7280' : isUp ? '#dc2626' : '#16a34a',
      fontWeight: 500,
      fontFamily: 'monospace',
    }}>
      {isUp ? '+' : ''}{value.toFixed(2)}%
    </span>
  )
}

export default function REITsSection({ user }) {
  const [subTab, setSubTab] = useState('pool') // pool | picks | backtest
  const [reitsList, setReitsList] = useState([])
  const [sectors, setSectors] = useState({})
  const [loading, setLoading] = useState(true)
  const [sectorFilter, setSectorFilter] = useState('')

  // 每周推荐
  const [weeklyPicks, setWeeklyPicks] = useState(null)
  const [picksLoading, setPicksLoading] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [picksHistory, setPicksHistory] = useState([])
  const [historyExpanded, setHistoryExpanded] = useState(false)

  // 回测
  const [backtest, setBacktest] = useState(null)
  const [backtestLoading, setBacktestLoading] = useState(false)

  // 排序
  const [sortBy, setSortBy] = useState('code')
  const [sortDir, setSortDir] = useState('asc')

  // 加载REITs列表
  const loadList = useCallback(async () => {
    setLoading(true)
    try {
      const [list, sec] = await Promise.all([
        api.getREITsList(sectorFilter || undefined),
        api.getREITsSectors(),
      ])
      setReitsList(list || [])
      setSectors(sec || {})
    } catch (e) {
      console.error('加载REITs列表失败:', e)
    }
    setLoading(false)
  }, [sectorFilter])

  // 加载每周推荐
  const loadPicks = useCallback(async () => {
    setPicksLoading(true)
    try {
      const [picks, history] = await Promise.all([
        api.getREITsWeeklyPicks(),
        api.getREITsPicksHistory(8),
      ])
      setWeeklyPicks(picks)
      setPicksHistory(history || [])
    } catch (e) {
      console.error('加载REITs推荐失败:', e)
    }
    setPicksLoading(false)
  }, [])

  // 加载回测
  const loadBacktest = useCallback(async () => {
    setBacktestLoading(true)
    try {
      const data = await api.getREITsBacktest()
      setBacktest(data)
    } catch (e) {
      console.error('加载回测失败:', e)
    }
    setBacktestLoading(false)
  }, [])

  useEffect(() => {
    if (subTab === 'pool') loadList()
    else if (subTab === 'picks') loadPicks()
    else if (subTab === 'backtest') loadBacktest()
  }, [subTab, loadList, loadPicks, loadBacktest])

  // 手动生成推荐
  const handleGenerate = async () => {
    if (!window.confirm('确认生成本周REITs推荐？\n将运行5层筛选流程，需要1-2分钟。')) return
    setGenerating(true)
    try {
      const result = await api.generateREITsPicks()
      setWeeklyPicks(result)
      alert('REITs推荐生成成功！')
    } catch (e) {
      alert('生成失败: ' + (e.message || '未知错误'))
    }
    setGenerating(false)
  }

  // 排序处理
  const handleSort = (col) => {
    if (sortBy === col) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(col)
      setSortDir(col === 'code' || col === 'name' ? 'asc' : 'desc')
    }
  }

  const sortedList = [...reitsList].sort((a, b) => {
    const dir = sortDir === 'asc' ? 1 : -1
    const av = a[sortBy], bv = b[sortBy]
    if (av == null && bv == null) return 0
    if (av == null) return 1
    if (bv == null) return -1
    if (typeof av === 'string') return av.localeCompare(bv) * dir
    return (av - bv) * dir
  })

  const totalReits = reitsList.length
  const withPrice = reitsList.filter(r => r.latest_price != null).length

  return (
    <div>
      {/* 子Tab切换 */}
      <div style={{
        display: 'flex',
        gap: 0,
        borderRadius: 8,
        overflow: 'hidden',
        border: '1px solid var(--border)',
        marginBottom: 20,
        width: 'fit-content',
      }}>
        {[
          { key: 'pool', label: `REITs自选池 (${totalReits})` },
          { key: 'picks', label: '每周推荐' },
          { key: 'backtest', label: '回测评价' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setSubTab(t.key)}
            style={{
              padding: '8px 20px',
              border: 'none',
              background: subTab === t.key ? 'var(--primary)' : 'transparent',
              color: subTab === t.key ? '#fff' : 'var(--text-secondary)',
              fontWeight: subTab === t.key ? 600 : 400,
              cursor: 'pointer',
              fontSize: 13,
              transition: 'all 0.2s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 评分模型方法论说明 */}
      <REITsMethodology />

      {/* ========== 自选池 ========== */}
      {subTab === 'pool' && (
        <>
          {/* 统计卡片 */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
            gap: 12,
            marginBottom: 16,
          }}>
            <div className="card" style={{ padding: '12px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--primary)' }}>{totalReits}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>总只数</div>
            </div>
            <div className="card" style={{ padding: '12px 16px', textAlign: 'center' }}>
              <div style={{ fontSize: 24, fontWeight: 700, color: '#10b981' }}>{withPrice}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>有行情</div>
            </div>
            {Object.entries(sectors).slice(0, 4).map(([s, c]) => (
              <div className="card" key={s} style={{ padding: '12px 16px', textAlign: 'center' }}>
                <div style={{ fontSize: 24, fontWeight: 700 }}>{c}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{s}</div>
              </div>
            ))}
          </div>

          {/* 类型筛选 */}
          <div className="filters" style={{ marginBottom: 12 }}>
            <button
              className={`filter-chip ${!sectorFilter ? 'active' : ''}`}
              onClick={() => setSectorFilter('')}
            >
              全部类型
            </button>
            {Object.keys(SECTOR_COLORS).map(s => (
              <button
                key={s}
                className={`filter-chip ${sectorFilter === s ? 'active' : ''}`}
                onClick={() => setSectorFilter(sectorFilter === s ? '' : s)}
              >
                {s}
              </button>
            ))}
          </div>

          {/* 列表 */}
          {loading ? (
            <div className="loading">
              <div className="loading-dot" />
              <div className="loading-dot" />
              <div className="loading-dot" />
            </div>
          ) : sortedList.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📋</div>
              <div className="empty-state-title">暂无REITs数据</div>
            </div>
          ) : (
            <div className="card" style={{ overflowX: 'auto' }}>
              <table className="rating-table">
                <thead>
                  <tr>
                    {[
                      { key: 'code', label: '代码' },
                      { key: 'name', label: '名称' },
                      { key: 'sector', label: '类型' },
                      { key: 'latest_price', label: '最新价' },
                      { key: 'change_pct', label: '涨跌幅' },
                      { key: 'dividend_yield', label: '分红率%' },
                      { key: 'turnover_ratio', label: '换手率%' },
                      { key: 'volume', label: '成交量' },
                    ].map(col => (
                      <th
                        key={col.key}
                        onClick={() => handleSort(col.key)}
                        style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}
                      >
                        {col.label}
                        {sortBy === col.key && (
                          <span style={{ fontSize: 10, marginLeft: 2 }}>
                            {sortDir === 'asc' ? '▲' : '▼'}
                          </span>
                        )}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sortedList.map(r => (
                    <tr key={r.code}>
                      <td style={{ fontFamily: 'monospace', fontWeight: 500 }}>{r.code}</td>
                      <td style={{ fontWeight: 500, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {r.name}
                      </td>
                      <td><SectorTag sector={r.sector} /></td>
                      <td style={{ fontFamily: 'monospace' }}>
                        {r.latest_price != null ? r.latest_price.toFixed(3) : '--'}
                      </td>
                      <td><ChangeTag value={r.change_pct} /></td>
                      <td style={{ fontFamily: 'monospace', color: r.dividend_yield >= 5 && r.dividend_yield <= 8 ? '#16a34a' : undefined, fontWeight: r.dividend_yield >= 5 && r.dividend_yield <= 8 ? 600 : 400 }}>
                        {r.dividend_yield != null ? r.dividend_yield.toFixed(2) : '--'}
                      </td>
                      <td style={{ fontFamily: 'monospace' }}>
                        {r.turnover_ratio != null ? r.turnover_ratio.toFixed(2) : '--'}
                      </td>
                      <td style={{ fontFamily: 'monospace', fontSize: 12 }}>
                        {r.volume != null ? (r.volume > 1e8 ? (r.volume / 1e8).toFixed(1) + '亿' : r.volume > 1e4 ? (r.volume / 1e4).toFixed(0) + '万' : r.volume.toFixed(0)) : '--'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}

      {/* ========== 每周推荐 ========== */}
      {subTab === 'picks' && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
            <h3 style={{ margin: 0, fontSize: 16 }}>
              📊 C-REITs 每周精选 · 5只推荐
            </h3>
            {user?.is_admin && (
              <button
                className="btn btn-sm"
                onClick={handleGenerate}
                disabled={generating}
                style={{
                  background: generating ? '#f3f4f6' : '#eff6ff',
                  color: generating ? '#9ca3af' : '#1d4ed8',
                  border: '1px solid',
                  borderColor: generating ? '#d1d5db' : '#93c5fd',
                }}
              >
                {generating ? '生成中...' : '重新生成推荐'}
              </button>
            )}
          </div>

          {/* 筛选策略说明 */}
          <div className="card" style={{ padding: 16, marginBottom: 16, background: '#f0fdf4', borderColor: '#bbf7d0' }}>
            <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8, color: '#166534' }}>🔍 5层智能筛选策略</div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', fontSize: 12, color: '#15803d' }}>
              <span>① 分红率 5-8% 优选</span>
              <span>② 剔除收入环比下降</span>
              <span>③ 剔除零换手率</span>
              <span>④ 剔除负面舆情</span>
              <span>⑤ AI综合评选Top 5</span>
            </div>
          </div>

          {picksLoading ? (
            <div className="loading">
              <div className="loading-dot" />
              <div className="loading-dot" />
              <div className="loading-dot" />
            </div>
          ) : weeklyPicks && weeklyPicks.picks && weeklyPicks.picks.length > 0 ? (
            <>
              {/* 本周推荐 */}
              <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                  <span style={{ fontSize: 14, fontWeight: 600 }}>
                    本周推荐 ({weeklyPicks.week_start} ~ {weeklyPicks.week_end})
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    模型: {weeklyPicks.model_source || 'MiniMax M2.5 + GLM-5 + Kimi K2.5'}
                  </span>
                </div>

                {/* 筛选漏斗 */}
                {weeklyPicks.filter_log && (
                  <div style={{
                    display: 'flex',
                    gap: 8,
                    marginBottom: 16,
                    flexWrap: 'wrap',
                    fontSize: 12,
                  }}>
                    {[
                      { label: '总池', val: weeklyPicks.filter_log.total, color: '#6b7280' },
                      { label: '分红率', val: weeklyPicks.filter_log.after_dividend, color: '#059669' },
                      { label: '收入', val: weeklyPicks.filter_log.after_income, color: '#0284c7' },
                      { label: '换手率', val: weeklyPicks.filter_log.after_turnover, color: '#7c3aed' },
                      { label: '舆情', val: weeklyPicks.filter_log.after_sentiment, color: '#db2777' },
                      { label: '推荐', val: weeklyPicks.filter_log.final, color: '#dc2626' },
                    ].map((s, i) => (
                      <React.Fragment key={s.label}>
                        <div style={{
                          display: 'flex', flexDirection: 'column', alignItems: 'center',
                          padding: '4px 8px', background: `${s.color}10`, borderRadius: 6,
                        }}>
                          <span style={{ fontSize: 16, fontWeight: 700, color: s.color }}>{s.val ?? '--'}</span>
                          <span style={{ color: s.color, fontSize: 11 }}>{s.label}</span>
                        </div>
                        {i < 5 && <span style={{ alignSelf: 'center', color: '#d1d5db' }}>→</span>}
                      </React.Fragment>
                    ))}
                  </div>
                )}

                {/* 推荐列表 */}
                <div style={{ display: 'grid', gap: 10 }}>
                  {weeklyPicks.picks.map((p, i) => (
                    <div key={p.code} style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '12px 16px',
                      background: i === 0 ? '#fef3c7' : '#fafafa',
                      borderRadius: 8,
                      border: `1px solid ${i === 0 ? '#fbbf24' : '#e5e7eb'}`,
                    }}>
                      <div style={{
                        width: 28, height: 28, borderRadius: '50%',
                        background: i === 0 ? '#f59e0b' : i < 3 ? '#3b82f6' : '#6b7280',
                        color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center',
                        fontWeight: 700, fontSize: 13,
                      }}>
                        {i + 1}
                      </div>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>
                          {p.name}
                          <span style={{ color: '#9ca3af', fontSize: 12, marginLeft: 8, fontFamily: 'monospace' }}>
                            {p.code}
                          </span>
                        </div>
                        <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
                          {p.reason || '通过5层筛选'}
                        </div>
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        <SectorTag sector={p.sector} />
                        {p.dividend_yield != null && (
                          <div style={{ fontSize: 12, color: '#16a34a', marginTop: 4, fontWeight: 500 }}>
                            分红率 {p.dividend_yield}%
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* 历史推荐 */}
              {picksHistory.length > 1 && (
                <div className="card" style={{ padding: 16 }}>
                  <div
                    style={{ fontSize: 14, fontWeight: 600, cursor: 'pointer', display: 'flex', justifyContent: 'space-between' }}
                    onClick={() => setHistoryExpanded(!historyExpanded)}
                  >
                    <span>📅 历史推荐记录 ({picksHistory.length}期)</span>
                    <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                      {historyExpanded ? '收起 ▲' : '展开 ▼'}
                    </span>
                  </div>
                  {historyExpanded && (
                    <div style={{ marginTop: 12 }}>
                      {picksHistory.slice(1).map(h => (
                        <div key={h.id} style={{
                          padding: '8px 12px',
                          borderBottom: '1px solid #f3f4f6',
                          display: 'flex',
                          justifyContent: 'space-between',
                          alignItems: 'center',
                        }}>
                          <span style={{ fontSize: 13, fontWeight: 500 }}>
                            {h.week_start} ~ {h.week_end}
                          </span>
                          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                            {(h.picks || []).map(p => (
                              <span key={p.code} style={{
                                fontSize: 11, padding: '1px 6px', borderRadius: 4,
                                background: '#f3f4f6', color: '#374151',
                              }}>
                                {p.name}
                              </span>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">📊</div>
              <div className="empty-state-title">暂无推荐数据</div>
              <div className="empty-state-desc">
                {user?.is_admin ? '点击"重新生成推荐"按钮生成本周REITs推荐' : '系统将在每周一自动生成推荐'}
              </div>
            </div>
          )}
        </>
      )}

      {/* ========== 回测评价 ========== */}
      {subTab === 'backtest' && (
        <>
          <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
            📈 REITs推荐回测评价
          </h3>

          {backtestLoading ? (
            <div className="loading">
              <div className="loading-dot" />
              <div className="loading-dot" />
              <div className="loading-dot" />
            </div>
          ) : backtest && backtest.items && backtest.items.length > 0 ? (
            <>
              {/* 综合表现 */}
              <div style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(3, 1fr)',
                gap: 12,
                marginBottom: 16,
              }}>
                {[
                  { label: '1个月', val: backtest.avg_return_1m, period: '30天' },
                  { label: '3个月', val: backtest.avg_return_3m, period: '90天' },
                  { label: '6个月', val: backtest.avg_return_6m, period: '180天' },
                ].map(p => (
                  <div className="card" key={p.label} style={{ padding: '16px', textAlign: 'center' }}>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>
                      平均收益 · {p.label}
                    </div>
                    <div style={{
                      fontSize: 24, fontWeight: 700, fontFamily: 'monospace',
                      color: p.val == null ? '#9ca3af' : p.val > 0 ? '#dc2626' : '#16a34a',
                    }}>
                      {p.val != null ? `${p.val > 0 ? '+' : ''}${p.val.toFixed(2)}%` : '暂无'}
                    </div>
                  </div>
                ))}
              </div>

              {/* 明细 */}
              <div className="card" style={{ padding: 16 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
                  推荐期: {backtest.week_start}
                </div>
                <table className="rating-table">
                  <thead>
                    <tr>
                      <th>代码</th>
                      <th>名称</th>
                      <th>推荐价</th>
                      <th>1个月</th>
                      <th>3个月</th>
                      <th>6个月</th>
                    </tr>
                  </thead>
                  <tbody>
                    {backtest.items.map(bt => (
                      <tr key={bt.code}>
                        <td style={{ fontFamily: 'monospace' }}>{bt.code}</td>
                        <td style={{ fontWeight: 500 }}>{bt.name}</td>
                        <td style={{ fontFamily: 'monospace' }}>
                          {bt.pick_price != null ? bt.pick_price.toFixed(3) : '--'}
                        </td>
                        <td><ChangeTag value={bt.return_1m} /></td>
                        <td><ChangeTag value={bt.return_3m} /></td>
                        <td><ChangeTag value={bt.return_6m} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <div className="empty-state">
              <div className="empty-state-icon">📈</div>
              <div className="empty-state-title">暂无回测数据</div>
              <div className="empty-state-desc">
                回测数据需要在推荐生成后一段时间才会有结果（至少1个月）
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
