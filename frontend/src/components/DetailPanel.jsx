import React, { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid
} from 'recharts'
import { api } from '../api'

function getScoreColor(score) {
  if (score >= 70) return 'var(--green)'
  if (score >= 50) return 'var(--accent)'
  if (score >= 35) return 'var(--orange)'
  return 'var(--red)'
}

function getBadgeClass(rating) {
  switch (rating) {
    case '优选': return 'badge-strong-buy'
    case '关注': return 'badge-buy'
    case '中性': return 'badge-neutral'
    case '谨慎': return 'badge-caution'
    default: return 'badge-neutral'
  }
}

function getMarketLabel(market) {
  switch (market) {
    case 'A': return 'A股'
    case 'HK': return '港股'
    case 'US': return '美股'
    default: return market
  }
}

function ChgBadge({ value, label }) {
  if (value == null) return null
  const color = value > 0 ? 'var(--red)' : value < 0 ? 'var(--green)' : 'var(--text-muted)'
  return (
    <div className="chg-badge">
      <span className="chg-badge-label">{label}</span>
      <span className="chg-badge-value" style={{ color }}>
        {value > 0 ? '+' : ''}{value.toFixed(2)}%
      </span>
    </div>
  )
}

function formatMoney(val) {
  if (val == null) return '--'
  const absVal = Math.abs(val)
  if (absVal >= 10000) return `${(val / 10000).toFixed(1)}亿`
  if (absVal >= 1) return `${val.toFixed(0)}万`
  return `${val.toFixed(2)}万`
}

export default function DetailPanel({ rating, modelType, cachedAnnouncements, onClose }) {
  const [prices, setPrices] = useState([])
  const [ratingTrend, setRatingTrend] = useState([])
  const [history, setHistory] = useState([])
  const [announcements, setAnnouncements] = useState([])
  const [annLoading, setAnnLoading] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!rating) return
    setLoading(true)
    const mt = modelType || rating.model_type || 'quant_ai'
    Promise.all([
      api.getPrices(rating.code, 60).catch(() => []),
      api.getRatingTrend(rating.code, 60, mt).catch(() => []),
      api.getRatingHistory(rating.code, 60, mt).catch(() => []),
    ]).then(([p, t, h]) => {
      setPrices(p)
      setRatingTrend(t)
      setHistory(h)
      setLoading(false)
    })
    // 优先使用父组件预加载的缓存数据
    if (cachedAnnouncements != null) {
      setAnnouncements(cachedAnnouncements)
      setAnnLoading(false)
    } else {
      setAnnLoading(true)
      api.getAnnouncements(rating.code, 90, 10)
        .then(data => setAnnouncements(data || []))
        .catch(() => setAnnouncements([]))
        .finally(() => setAnnLoading(false))
    }
  }, [rating, cachedAnnouncements, modelType])

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  if (!rating) return null

  const isSoochow = modelType === 'soochow' || rating.model_type === 'soochow'

  const quantScore = (
    rating.trend_score * 0.25 +
    rating.momentum_score * 0.20 +
    rating.volatility_score * 0.15 +
    rating.volume_score * 0.20 +
    rating.value_score * 0.20
  ).toFixed(2)

  const scores = [
    { label: '趋势评分', value: rating.trend_score, key: 'trend' },
    { label: '动量评分', value: rating.momentum_score, key: 'momentum' },
    { label: '波动评分', value: rating.volatility_score, key: 'volatility' },
    { label: '成交评分', value: rating.volume_score, key: 'volume' },
    { label: '价值评分', value: rating.value_score, key: 'value' },
    { label: 'AI评分', value: rating.ai_score, key: 'ai' },
  ]

  const hasValuation = rating.pe_ttm != null || rating.pb_mrq != null
  const hasMoneyFlow = rating.main_net_inflow != null
  const hasChgData = rating.chg_5d != null || rating.chg_20d != null || rating.chg_year != null
  const hasMicroData = rating.vol_ratio != null || rating.swing != null || rating.committee != null

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={e => e.stopPropagation()}>
        <div className="detail-header">
          <div>
            <div className="detail-title">{rating.name}</div>
            <div className="detail-subtitle">
              {rating.code} · {getMarketLabel(rating.market)} · {rating.date}
            </div>
          </div>
          <button className="detail-close" onClick={onClose}>×</button>
        </div>

        <div className="detail-body">
          {/* 总评分 */}
          <div className="total-score-card">
            <div className="total-score-number">{typeof rating.total_score === 'number' ? rating.total_score.toFixed(2) : rating.total_score}</div>
            <div className="total-score-label">
              <span className={`badge ${getBadgeClass(rating.rating)}`} style={{ color: '#fff', background: 'rgba(255,255,255,0.2)' }}>
                {rating.rating}
              </span>
            </div>
            {rating.ai_score > 0 && (
              <div style={{ marginTop: 10, fontSize: 12, opacity: 0.75 }}>
                {isSoochow
                  ? (rating.fundamental_score != null
                      ? `基本面 ${rating.fundamental_score.toFixed(1)}×70% + AI ${typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}×30%`
                      : `AI ${typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}×100%`)
                  : (rating.fundamental_score != null
                      ? `量化 ${quantScore}×30% + 基本面 ${rating.fundamental_score.toFixed(1)}×20% + AI ${typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}×50%`
                      : `量化 ${quantScore}×38% + AI ${typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}×62%`)
                }
              </div>
            )}
          </div>

          {/* ═══ iFinD 核心估值 ═══ */}
          {(hasValuation || rating.roe != null) && (
            <div className="detail-section">
              <div className="detail-section-title">
                核心估值
                <span className="ifind-badge">iFinD</span>
              </div>
              <div className="scores-grid">
                {rating.pe_ttm != null && (
                  <div className="score-item">
                    <div className="score-item-label">PE(TTM)</div>
                    <div className="score-item-value" style={{ color: rating.pe_ttm < 0 ? 'var(--red)' : rating.pe_ttm < 30 ? 'var(--green)' : 'var(--orange)' }}>
                      {rating.pe_ttm.toFixed(2)}
                    </div>
                  </div>
                )}
                {rating.pb_mrq != null && (
                  <div className="score-item">
                    <div className="score-item-label">PB(MRQ)</div>
                    <div className="score-item-value" style={{ color: rating.pb_mrq < 1 ? 'var(--accent)' : 'var(--text-primary)' }}>
                      {rating.pb_mrq.toFixed(4)}{rating.pb_mrq < 1 && rating.pb_mrq > 0 ? ' 破净' : ''}
                    </div>
                  </div>
                )}
                {rating.market_value != null && (
                  <div className="score-item">
                    <div className="score-item-label">总市值</div>
                    <div className="score-item-value">{rating.market_value.toFixed(0)}亿</div>
                  </div>
                )}
                {rating.roe != null && (
                  <div className="score-item">
                    <div className="score-item-label">ROE</div>
                    <div className="score-item-value" style={{ color: rating.roe > 8 ? 'var(--green)' : rating.roe < 0 ? 'var(--red)' : 'var(--text-primary)' }}>
                      {rating.roe.toFixed(2)}%
                    </div>
                  </div>
                )}
                {rating.eps != null && (
                  <div className="score-item">
                    <div className="score-item-label">EPS</div>
                    <div className="score-item-value">{rating.eps.toFixed(4)}</div>
                  </div>
                )}
                {rating.debt_ratio != null && (
                  <div className="score-item">
                    <div className="score-item-label">资产负债率</div>
                    <div className="score-item-value" style={{ color: rating.debt_ratio > 85 ? 'var(--red)' : rating.debt_ratio > 80 ? 'var(--orange)' : 'var(--green)' }}>
                      {rating.debt_ratio.toFixed(1)}%
                    </div>
                  </div>
                )}
                {rating.fundamental_score != null && (
                  <div className="score-item">
                    <div className="score-item-label">基本面评分</div>
                    <div className="score-item-value" style={{ color: getScoreColor(rating.fundamental_score) }}>
                      {rating.fundamental_score.toFixed(2)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ═══ iFinD 多周期涨跌幅 ═══ */}
          {hasChgData && (
            <div className="detail-section">
              <div className="detail-section-title">
                多周期涨跌幅
                <span className="ifind-badge">iFinD</span>
              </div>
              <div className="chg-grid">
                <ChgBadge value={rating.chg_5d} label="5日" />
                <ChgBadge value={rating.chg_10d} label="10日" />
                <ChgBadge value={rating.chg_20d} label="20日" />
                <ChgBadge value={rating.chg_60d} label="60日" />
                <ChgBadge value={rating.chg_120d} label="120日" />
                <ChgBadge value={rating.chg_year} label="年初至今" />
              </div>
            </div>
          )}

          {/* ═══ iFinD 资金流向 ═══ */}
          {hasMoneyFlow && (
            <div className="detail-section">
              <div className="detail-section-title">
                资金流向
                <span className="ifind-badge">iFinD</span>
              </div>
              <div className="money-flow-grid">
                <div className="money-flow-item money-flow-main">
                  <div className="money-flow-label">主力净流入</div>
                  <div className="money-flow-value" style={{ color: rating.main_net_inflow > 0 ? 'var(--red)' : 'var(--green)' }}>
                    {rating.main_net_inflow > 0 ? '+' : ''}{formatMoney(rating.main_net_inflow)}
                  </div>
                  <div className="money-flow-bar">
                    <div
                      className="money-flow-bar-fill"
                      style={{
                        width: `${Math.min(Math.abs(rating.main_net_inflow || 0) / 50000 * 100, 100)}%`,
                        background: rating.main_net_inflow > 0 ? 'var(--red)' : 'var(--green)',
                      }}
                    />
                  </div>
                </div>
                {rating.retail_net_inflow != null && (
                  <div className="money-flow-item">
                    <div className="money-flow-label">散户净流入</div>
                    <div className="money-flow-value" style={{ color: rating.retail_net_inflow > 0 ? 'var(--red)' : 'var(--green)', fontSize: 14 }}>
                      {rating.retail_net_inflow > 0 ? '+' : ''}{formatMoney(rating.retail_net_inflow)}
                    </div>
                  </div>
                )}
                {rating.large_net_inflow != null && (
                  <div className="money-flow-item">
                    <div className="money-flow-label">超大单净流入</div>
                    <div className="money-flow-value" style={{ color: rating.large_net_inflow > 0 ? 'var(--red)' : 'var(--green)', fontSize: 14 }}>
                      {rating.large_net_inflow > 0 ? '+' : ''}{formatMoney(rating.large_net_inflow)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ═══ iFinD 市场微观 ═══ */}
          {(hasMicroData || rating.rise_day_count != null || rating.turnover_ratio != null) && (
            <div className="detail-section">
              <div className="detail-section-title">
                市场微观数据
                <span className="ifind-badge">iFinD</span>
              </div>
              <div className="scores-grid">
                {rating.vol_ratio != null && (
                  <div className="score-item">
                    <div className="score-item-label">量比</div>
                    <div className="score-item-value" style={{ color: rating.vol_ratio > 2 ? 'var(--red)' : rating.vol_ratio > 1 ? 'var(--orange)' : 'var(--text-primary)' }}>
                      {rating.vol_ratio.toFixed(2)}
                    </div>
                  </div>
                )}
                {rating.turnover_ratio != null && (
                  <div className="score-item">
                    <div className="score-item-label">换手率</div>
                    <div className="score-item-value">{rating.turnover_ratio.toFixed(2)}%</div>
                  </div>
                )}
                {rating.committee != null && (
                  <div className="score-item">
                    <div className="score-item-label">委比</div>
                    <div className="score-item-value" style={{ color: rating.committee > 0 ? 'var(--red)' : 'var(--green)' }}>
                      {rating.committee > 0 ? '+' : ''}{rating.committee.toFixed(2)}%
                    </div>
                  </div>
                )}
                {rating.swing != null && (
                  <div className="score-item">
                    <div className="score-item-label">振幅</div>
                    <div className="score-item-value">{rating.swing.toFixed(2)}%</div>
                  </div>
                )}
                {rating.rise_day_count != null && (
                  <div className="score-item">
                    <div className="score-item-label">{rating.rise_day_count >= 0 ? '连涨' : '连跌'}</div>
                    <div className="score-item-value" style={{ color: rating.rise_day_count > 0 ? 'var(--red)' : rating.rise_day_count < 0 ? 'var(--green)' : 'var(--text-muted)' }}>
                      {Math.abs(rating.rise_day_count)}天
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 维度评分 - 量化AI模型专属 */}
          {!isSoochow && (
            <div className="detail-section">
              <div className="detail-section-title">量化维度评分</div>
              <div className="scores-grid">
                {scores.map(s => (
                  <div className="score-item" key={s.key}>
                    <div className="score-item-label">{s.label}</div>
                    <div className="score-item-value" style={{ color: getScoreColor(s.value) }}>
                      {typeof s.value === 'number' ? s.value.toFixed(2) : s.value}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 评级理由 / AI分析 */}
          <div className="detail-section">
            <div className="detail-section-title">
              {rating.ai_score > 0 ? 'AI 专业分析' : '评级理由'}
            </div>

            {rating.ai_score > 0 ? (
              <div className="ai-analysis-card">
                <div className="ai-analysis-header">
                  <span className="ai-analysis-badge">
                    <span>&#x1F916;</span> 腾讯混元2.0
                  </span>
                  <span className="ai-analysis-model">AI评分: {typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}分</span>
                </div>
                <div className="ai-analysis-content">{rating.reason}</div>
                <div className="score-composition">
                  {isSoochow ? (
                    <>
                      {rating.fundamental_score != null && (
                        <>
                          <span className="score-comp-part">
                            <span className="score-comp-dot" style={{ background: 'var(--green)' }} />
                            基本面({rating.fundamental_score.toFixed(1)}) ×70%
                          </span>
                          <span style={{ color: 'var(--text-muted)' }}>+</span>
                        </>
                      )}
                      <span className="score-comp-part">
                        <span className="score-comp-dot" style={{ background: 'var(--purple)' }} />
                        AI({typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}) ×{rating.fundamental_score != null ? '30%' : '100%'}
                      </span>
                      <span style={{ color: 'var(--text-muted)' }}>=</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                        综合 {typeof rating.total_score === 'number' ? rating.total_score.toFixed(2) : rating.total_score}
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="score-comp-part">
                        <span className="score-comp-dot" style={{ background: 'var(--accent)' }} />
                        量化({quantScore}) ×{rating.fundamental_score != null ? '30%' : '38%'}
                      </span>
                      {rating.fundamental_score != null && (
                        <>
                          <span style={{ color: 'var(--text-muted)' }}>+</span>
                          <span className="score-comp-part">
                            <span className="score-comp-dot" style={{ background: 'var(--green)' }} />
                            基本面({rating.fundamental_score.toFixed(1)}) ×20%
                          </span>
                        </>
                      )}
                      <span style={{ color: 'var(--text-muted)' }}>+</span>
                      <span className="score-comp-part">
                        <span className="score-comp-dot" style={{ background: 'var(--purple)' }} />
                        AI({typeof rating.ai_score === 'number' ? rating.ai_score.toFixed(2) : rating.ai_score}) ×{rating.fundamental_score != null ? '50%' : '62%'}
                      </span>
                      <span style={{ color: 'var(--text-muted)' }}>=</span>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                        综合 {typeof rating.total_score === 'number' ? rating.total_score.toFixed(2) : rating.total_score}
                      </span>
                    </>
                  )}
                </div>
              </div>
            ) : (
              <div className="reason-text">{rating.reason}</div>
            )}
          </div>

          {/* ═══ iFinD 公告与财报 ═══ */}
          <div className="detail-section">
            <div className="detail-section-title">
              公告与财报
              <span className="ifind-badge">iFinD</span>
            </div>
            {annLoading ? (
              <div className="ann-loading">加载公告中...</div>
            ) : announcements.length > 0 ? (
              <div className="ann-list">
                {announcements.map((ann, idx) => (
                  <div key={idx} className={`ann-item${ann.is_financial ? ' ann-financial' : ann.is_key ? ' ann-key' : ''}`}>
                    <div className="ann-item-header">
                      {ann.is_financial && <span className="ann-tag ann-tag-fin">财报</span>}
                      {!ann.is_financial && ann.is_key && <span className="ann-tag ann-tag-key">重点</span>}
                      <span className="ann-date">{ann.date}</span>
                    </div>
                    <div className="ann-title">
                      {ann.pdf_url ? (
                        <a href={ann.pdf_url} target="_blank" rel="noopener noreferrer">{ann.title}</a>
                      ) : (
                        ann.title
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="ann-empty">暂无近期公告数据</div>
            )}
          </div>

          {/* 价格走势 */}
          {!loading && prices.length > 0 && (
            <div className="detail-section">
              <div className="detail-section-title">近期价格走势</div>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={prices}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={v => v.slice(5)}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                    />
                    <YAxis
                      domain={['dataMin', 'dataMax']}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                      width={50}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="close"
                      stroke="#2563eb"
                      strokeWidth={2}
                      dot={false}
                      name="收盘价"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* 评分趋势 */}
          {!loading && ratingTrend.length > 1 && (
            <div className="detail-section">
              <div className="detail-section-title">评分趋势</div>
              <div className="chart-container">
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={ratingTrend}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis
                      dataKey="date"
                      tickFormatter={v => v.slice(5)}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tick={{ fontSize: 11, fill: '#9ca3af' }}
                      width={35}
                    />
                    <Tooltip
                      contentStyle={{ borderRadius: 8, border: '1px solid #e5e7eb', fontSize: 12 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="total_score"
                      stroke="#7c3aed"
                      strokeWidth={2}
                      dot={false}
                      name="综合评分"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}

          {/* 历史评级 */}
          {!loading && history.length > 0 && (
            <div className="detail-section">
              <div className="detail-section-title">历史评级记录</div>
              <div style={{ maxHeight: 300, overflowY: 'auto' }}>
                <table className="table" style={{ fontSize: 12 }}>
                  <thead>
                    <tr>
                      <th>日期</th>
                      <th>评分</th>
                      <th>评级</th>
                    </tr>
                  </thead>
                  <tbody>
                    {history.map(h => (
                      <tr key={h.date} style={{ cursor: 'default' }}>
                        <td>{h.date}</td>
                        <td style={{ fontWeight: 600, color: getScoreColor(h.total_score) }}>
                          {typeof h.total_score === 'number' ? h.total_score.toFixed(2) : h.total_score}
                        </td>
                        <td>
                          <span className={`badge ${getBadgeClass(h.rating)}`}>{h.rating}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 数据来源 */}
          <div className="detail-data-source">
            数据来源：同花顺iFinD · 东方财富 · 腾讯混元AI · 中国政府网
          </div>
        </div>
      </div>
    </div>
  )
}
