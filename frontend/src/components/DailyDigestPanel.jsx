import React, { useState, useEffect, useCallback } from 'react'
import { api } from '../api'

export default function DailyDigestPanel({ type, onRefresh }) {
  const [digest, setDigest] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(false)

  const loadDigest = useCallback(async (force = false) => {
    setLoading(true)
    setError('')
    try {
      const data = type === 'industry'
        ? await api.getIndustryDigest(force)
        : type === 'ai_picks'
        ? await api.getAiPicksDigest(force)
        : await api.getWatchlistDigest(force)
      setDigest(data)
    } catch (err) {
      if (err.message?.includes('404')) {
        setError(type === 'industry' ? '暂无评级数据，无法生成日报' : type === 'ai_picks' ? '请先生成AI推荐组合' : '请先添加自选股')
      } else {
        setError(err.message || '加载失败')
      }
    }
    setLoading(false)
  }, [type])

  useEffect(() => {
    loadDigest(false)
  }, [loadDigest])

  const handleRegenerate = () => {
    if (loading) return
    loadDigest(true)
  }

  const renderMarkdown = (text) => {
    if (!text) return null
    const lines = text.split('\n')
    const elements = []
    let i = 0

    while (i < lines.length) {
      const line = lines[i]

      if (line.startsWith('### ')) {
        elements.push(<h4 key={i} style={{ margin: '16px 0 8px', fontSize: 15, fontWeight: 600, color: '#1a1a1a' }}>{renderInline(line.slice(4))}</h4>)
      } else if (line.startsWith('## ')) {
        elements.push(<h3 key={i} style={{ margin: '18px 0 10px', fontSize: 16, fontWeight: 600, color: '#1a1a1a' }}>{renderInline(line.slice(3))}</h3>)
      } else if (line.startsWith('# ')) {
        elements.push(<h2 key={i} style={{ margin: '20px 0 12px', fontSize: 18, fontWeight: 700, color: '#1a1a1a' }}>{renderInline(line.slice(2))}</h2>)
      } else if (line.match(/^[-*]\s/)) {
        const items = []
        while (i < lines.length && lines[i].match(/^[-*]\s/)) {
          items.push(<li key={i} style={{ marginBottom: 4 }}>{renderInline(lines[i].replace(/^[-*]\s/, ''))}</li>)
          i++
        }
        elements.push(<ul key={`ul-${i}`} style={{ margin: '8px 0', paddingLeft: 20, lineHeight: 1.7 }}>{items}</ul>)
        continue
      } else if (line.match(/^\d+\.\s/)) {
        const items = []
        while (i < lines.length && lines[i].match(/^\d+\.\s/)) {
          items.push(<li key={i} style={{ marginBottom: 4 }}>{renderInline(lines[i].replace(/^\d+\.\s/, ''))}</li>)
          i++
        }
        elements.push(<ol key={`ol-${i}`} style={{ margin: '8px 0', paddingLeft: 20, lineHeight: 1.7 }}>{items}</ol>)
        continue
      } else if (line.trim() === '') {
        elements.push(<div key={i} style={{ height: 8 }} />)
      } else {
        elements.push(<p key={i} style={{ margin: '6px 0', lineHeight: 1.8, fontSize: 14, color: '#333' }}>{renderInline(line)}</p>)
      }
      i++
    }
    return elements
  }

  const renderInline = (text) => {
    const parts = text.split(/(\*\*[^*]+\*\*)/g)
    return parts.map((part, i) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return <strong key={i} style={{ color: '#1a1a1a' }}>{part.slice(2, -2)}</strong>
      }
      return part
    })
  }

  const isIndustry = type === 'industry'
  const isAiPicks = type === 'ai_picks'
  const title = isIndustry ? '每日地产行业日报' : isAiPicks ? 'AI推荐选股日报' : '自选股每日综合日报'
  const icon = isIndustry ? '📰' : isAiPicks ? '🤖' : '📊'

  return (
    <div className="digest-panel">
      <div
        className="digest-header"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="digest-header-left">
          <span className="digest-icon">{icon}</span>
          <div>
            <h3 className="digest-title">{title}</h3>
            {digest && (
              <span className="digest-date">{digest.digest_date} · AI三模型融合生成{digest.model_sources ? ` (${digest.model_sources})` : ''}</span>
            )}
          </div>
        </div>
        <div className="digest-header-right">
          <button
            className="digest-regen-btn"
            onClick={(e) => { e.stopPropagation(); handleRegenerate() }}
            disabled={loading}
            title="重新生成"
          >
            {loading ? '生成中...' : '刷新'}
          </button>
          <span className={`digest-toggle ${expanded ? 'expanded' : ''}`}>&#x25B6;</span>
        </div>
      </div>

      {expanded && (
        <div className="digest-body">
          {loading && !digest && (
            <div className="digest-loading">
              <div className="loading-dot" />
              <div className="loading-dot" />
              <div className="loading-dot" />
              <span style={{ marginLeft: 8, fontSize: 13, color: '#9ca3af' }}>AI正在综合三个大模型生成日报...</span>
            </div>
          )}

          {loading && digest && (
            <div className="digest-loading-overlay">
              <div className="loading-dot" />
              <div className="loading-dot" />
              <div className="loading-dot" />
              <span style={{ marginLeft: 8, fontSize: 13 }}>重新生成中...</span>
            </div>
          )}

          {error && !digest && (
            <div className="digest-error">
              <span>{error}</span>
              <button className="btn btn-sm" onClick={() => loadDigest(false)}>重试</button>
            </div>
          )}

          {digest && (
            <div className={`digest-content ${loading ? 'digest-content-dim' : ''}`}>
              <h3 className="digest-content-title">{digest.title}</h3>
              <div className="digest-content-body">
                {renderMarkdown(digest.content)}
              </div>
              <div className="digest-footer">
                <span>生成时间：{digest.created_at ? new Date(digest.created_at).toLocaleString('zh-CN') : '-'}</span>
                <span>AI评级仅供参考，不构成投资建议</span>
              </div>
            </div>
          )}
        </div>
      )}

      <style>{`
        .digest-panel {
          margin-top: 16px;
          border-radius: var(--radius, 12px);
          overflow: hidden;
          border: 1px solid var(--border, #e5e7eb);
          background: var(--bg-card, #fff);
          box-shadow: var(--shadow, 0 1px 3px rgba(0,0,0,0.04));
        }
        .digest-header {
          padding: 16px 20px;
          cursor: pointer;
          display: flex;
          justify-content: space-between;
          align-items: center;
          transition: background 0.2s;
          user-select: none;
        }
        .digest-header:hover {
          background: var(--bg-hover, #f9fafb);
        }
        .digest-header-left {
          display: flex;
          align-items: center;
          gap: 12px;
        }
        .digest-icon {
          font-size: 22px;
        }
        .digest-title {
          margin: 0;
          font-size: 15px;
          font-weight: 700;
          color: #667eea;
        }
        .digest-date {
          font-size: 12px;
          color: var(--text-muted, #9ca3af);
        }
        .digest-header-right {
          display: flex;
          align-items: center;
          gap: 10px;
        }
        .digest-regen-btn {
          padding: 4px 14px;
          border: 1px solid var(--border, #e5e7eb);
          border-radius: 6px;
          background: var(--card-bg, #fff);
          color: var(--text-muted, #6b7280);
          font-size: 12px;
          cursor: pointer;
          transition: all 0.15s;
        }
        .digest-regen-btn:hover:not(:disabled) {
          border-color: var(--primary, #667eea);
          color: var(--primary, #667eea);
        }
        .digest-regen-btn:disabled {
          opacity: 0.6;
          cursor: wait;
        }
        .digest-toggle {
          font-size: 10px;
          color: var(--text-muted, #9ca3af);
          transition: transform 0.25s ease;
        }
        .digest-toggle.expanded {
          transform: rotate(90deg);
        }
        .digest-body {
          padding: 20px;
          position: relative;
        }
        .digest-loading {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 40px 0;
        }
        .digest-loading-overlay {
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 8px 0 16px;
          color: var(--primary, #667eea);
        }
        .digest-error {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 12px;
          padding: 30px 0;
          color: var(--text-muted, #9ca3af);
          font-size: 14px;
        }
        .digest-content {
          transition: opacity 0.2s;
        }
        .digest-content-dim {
          opacity: 0.4;
        }
        .digest-content-title {
          font-size: 18px;
          font-weight: 700;
          color: #1a1a1a;
          margin: 0 0 16px;
          padding-bottom: 12px;
          border-bottom: 2px solid var(--primary, #667eea);
        }
        .digest-content-body {
          font-size: 14px;
          line-height: 1.8;
          color: #333;
        }
        .digest-footer {
          margin-top: 20px;
          padding-top: 12px;
          border-top: 1px solid var(--border, #e5e7eb);
          display: flex;
          justify-content: space-between;
          font-size: 11px;
          color: var(--text-muted, #9ca3af);
          flex-wrap: wrap;
          gap: 8px;
        }
      `}</style>
    </div>
  )
}
