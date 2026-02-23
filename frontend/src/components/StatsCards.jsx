import React from 'react'

export default function StatsCards({ dashboard }) {
  if (!dashboard) return null

  const { total_stocks, rated_today, avg_score, rating_distribution } = dashboard

  return (
    <div className="stats-grid">
      <div className="stat-card">
        <div className="stat-label">跟踪股票</div>
        <div className="stat-value">{total_stocks}</div>
        <div className="stat-sub">A股 / 港股 / 美股</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">已评级</div>
        <div className="stat-value">{rated_today}</div>
        <div className="stat-sub">最新一期</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">平均评分</div>
        <div className="stat-value" style={{ color: avg_score >= 60 ? 'var(--green)' : avg_score >= 45 ? 'var(--orange)' : 'var(--red)' }}>
          {avg_score}
        </div>
        <div className="stat-sub">满分100</div>
      </div>
      <div className="stat-card">
        <div className="stat-label">评级分布</div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          {Object.entries(rating_distribution || {}).map(([k, v]) => (
            <span key={k} className={`badge ${getBadgeClass(k)}`}>
              {k} {v}
            </span>
          ))}
          {Object.keys(rating_distribution || {}).length === 0 && (
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>暂无数据</span>
          )}
        </div>
      </div>
    </div>
  )
}

function getBadgeClass(rating) {
  switch (rating) {
    case '强烈推荐': return 'badge-strong-buy'
    case '推荐': return 'badge-buy'
    case '中性': return 'badge-neutral'
    case '谨慎': return 'badge-caution'
    case '回避': return 'badge-avoid'
    default: return 'badge-neutral'
  }
}
