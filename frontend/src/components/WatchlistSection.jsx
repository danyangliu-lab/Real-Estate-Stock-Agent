import React, { useState, useEffect, useCallback, useRef } from 'react'
import { api } from '../api'
import DailyDigestPanel from './DailyDigestPanel'

const MAX_WATCHLIST = 15
const CACHE_KEY = 'watchlist_analysis'
const ANALYZING_KEY = 'watchlist_analyzing'

const SUGGESTION_COLORS = {
  '买入': { bg: '#dcfce7', color: '#166534', border: '#86efac' },
  '加仓': { bg: '#dcfce7', color: '#166534', border: '#86efac' },
  '持有': { bg: '#dbeafe', color: '#1e40af', border: '#93c5fd' },
  '减仓': { bg: '#fef3c7', color: '#92400e', border: '#fcd34d' },
  '观望': { bg: '#f3f4f6', color: '#4b5563', border: '#d1d5db' },
  '回避': { bg: '#fee2e2', color: '#991b1b', border: '#fca5a5' },
}

const RATING_COLORS = {
  '优选': '#10b981',
  '关注': '#3b82f6',
  '中性': '#f59e0b',
  '谨慎': '#ef4444',
}

let _analyzePromise = null

export default function WatchlistSection({ user }) {
  const [subTab, setSubTab] = useState('my') // 'my' | 'ai'
  const [watchlist, setWatchlist] = useState([])
  const [analysis, setAnalysis] = useState([])
  const [stocks, setStocks] = useState([])
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [searchText, setSearchText] = useState('')
  const [addLoading, setAddLoading] = useState(false)
  const mountedRef = useRef(true)

  // 模拟仓位
  const [showPortfolio, setShowPortfolio] = useState(true)
  const [weights, setWeights] = useState({})
  const [savedWeights, setSavedWeights] = useState({})
  const [savingWeights, setSavingWeights] = useState(false)
  const [performance, setPerformance] = useState(null)
  const [perfLoading, setPerfLoading] = useState(false)
  const [perfDays, setPerfDays] = useState(30)

  // AI推荐选股
  const [aiPicks, setAiPicks] = useState(null)
  const [aiPicksLoading, setAiPicksLoading] = useState(false)
  const [aiPicksDays, setAiPicksDays] = useState(30)

  useEffect(() => {
    mountedRef.current = true
    try {
      const cached = localStorage.getItem(CACHE_KEY)
      if (cached) {
        const { data, time } = JSON.parse(cached)
        if (Date.now() - time < 24 * 60 * 60 * 1000 && Array.isArray(data)) {
          setAnalysis(data)
        }
      }
    } catch {}
    if (_analyzePromise || localStorage.getItem(ANALYZING_KEY)) {
      setAnalyzing(true)
      if (_analyzePromise) {
        _analyzePromise.then(data => {
          if (mountedRef.current && data) { setAnalysis(data); setAnalyzing(false) }
        }).catch(() => { if (mountedRef.current) setAnalyzing(false) })
      } else {
        localStorage.removeItem(ANALYZING_KEY)
        setAnalyzing(false)
      }
    }
    return () => { mountedRef.current = false }
  }, [])

  const loadWatchlist = useCallback(async () => {
    setLoading(true)
    try { setWatchlist(await api.getWatchlist()) } catch (e) { console.error(e) }
    setLoading(false)
  }, [])

  const loadStocks = useCallback(async () => {
    try { setStocks(await api.getStocks()) } catch (e) { console.error(e) }
  }, [])

  const loadPortfolioWeights = useCallback(async () => {
    try {
      const data = await api.getPortfolioWeights()
      const wMap = {}
      data.forEach(d => { wMap[d.stock_code] = d.weight })
      setWeights(wMap)
      setSavedWeights(wMap)
    } catch (e) { console.error(e) }
  }, [])

  const loadPerformance = useCallback(async (d) => {
    setPerfLoading(true)
    try {
      const data = await api.getPortfolioPerformance(d || perfDays)
      if (mountedRef.current) setPerformance(data)
    } catch (e) { console.error(e) }
    if (mountedRef.current) setPerfLoading(false)
  }, [perfDays])

  const loadAIPicks = useCallback(async (force = false, d) => {
    setAiPicksLoading(true)
    try {
      const data = await api.getAIPicks(force, d || aiPicksDays)
      if (mountedRef.current) setAiPicks(data)
    } catch (e) { console.error(e) }
    if (mountedRef.current) setAiPicksLoading(false)
  }, [aiPicksDays])

  useEffect(() => {
    loadWatchlist()
    loadStocks()
    loadPortfolioWeights()
  }, [loadWatchlist, loadStocks, loadPortfolioWeights])

  useEffect(() => {
    if (Object.keys(savedWeights).length > 0) loadPerformance()
  }, [savedWeights, loadPerformance])

  useEffect(() => {
    if (subTab === 'ai' && !aiPicks && !aiPicksLoading) loadAIPicks()
  }, [subTab, aiPicks, aiPicksLoading, loadAIPicks])

  const handleAdd = async (stock) => {
    setAddLoading(true)
    try { await api.addToWatchlist(stock.code); await loadWatchlist(); setSearchText('') }
    catch (e) { alert(e.message) }
    setAddLoading(false)
  }

  const handleRemove = async (code) => {
    if (!window.confirm('确定从自选中移除？')) return
    try {
      await api.removeFromWatchlist(code)
      setWatchlist(prev => prev.filter(w => w.stock_code !== code))
      setAnalysis(prev => prev.filter(a => a.stock_code !== code))
    } catch (e) { alert('移除失败: ' + e.message) }
  }

  const handleAnalyze = () => {
    if (watchlist.length === 0 || _analyzePromise) return
    setAnalyzing(true)
    localStorage.setItem(ANALYZING_KEY, '1')
    _analyzePromise = api.getWatchlistAnalysis()
      .then(data => {
        localStorage.setItem(CACHE_KEY, JSON.stringify({ data, time: Date.now() }))
        localStorage.removeItem(ANALYZING_KEY)
        if (mountedRef.current) { setAnalysis(data); setAnalyzing(false) }
        _analyzePromise = null
        return data
      })
      .catch(err => {
        localStorage.removeItem(ANALYZING_KEY)
        if (mountedRef.current) { setAnalyzing(false); alert('获取AI分析失败: ' + err.message) }
        _analyzePromise = null
        throw err
      })
  }

  const handleWeightChange = (code, val) => {
    const num = parseFloat(val) || 0
    setWeights(prev => ({ ...prev, [code]: Math.min(100, Math.max(0, num)) }))
  }

  const handleEqualWeight = () => {
    const n = watchlist.length
    if (n === 0) return
    const w = parseFloat((100 / n).toFixed(2))
    const nw = {}
    watchlist.forEach((item, i) => {
      nw[item.stock_code] = i === n - 1 ? parseFloat((100 - w * (n - 1)).toFixed(2)) : w
    })
    setWeights(nw)
  }

  const handleSaveWeights = async () => {
    const wl = watchlist.filter(w => (weights[w.stock_code] || 0) > 0)
      .map(w => ({ stock_code: w.stock_code, weight: weights[w.stock_code] || 0 }))
    const total = wl.reduce((s, w) => s + w.weight, 0)
    if (wl.length > 0 && Math.abs(total - 100) > 0.01) {
      alert(`仓位百分比之和须等于100%，当前为${total.toFixed(1)}%`)
      return
    }
    setSavingWeights(true)
    try { await api.updatePortfolioWeights(wl); setSavedWeights({ ...weights }); await loadPerformance() }
    catch (e) { alert('保存失败: ' + e.message) }
    setSavingWeights(false)
  }

  const totalWeight = watchlist.reduce((s, w) => s + (weights[w.stock_code] || 0), 0)
  const hasWeightChanges = JSON.stringify(weights) !== JSON.stringify(savedWeights)
  const watchlistCodes = new Set(watchlist.map(w => w.stock_code))
  const filteredStocks = stocks.filter(s =>
    !watchlistCodes.has(s.code) && (searchText === '' || s.name.includes(searchText) || s.code.includes(searchText))
  )
  const analysisMap = {}
  analysis.forEach(a => { analysisMap[a.stock_code] = a })

  return (
    <div className="watchlist-section">
      {/* 子板块切换 */}
      <div className="sub-tabs">
        <button className={`sub-tab ${subTab === 'my' ? 'active' : ''}`} onClick={() => setSubTab('my')}>
          我的自选股
        </button>
        <button className={`sub-tab ${subTab === 'ai' ? 'active' : ''}`} onClick={() => setSubTab('ai')}>
          AI推荐选股
        </button>
      </div>

      {/* ===== 我的自选股 ===== */}
      {subTab === 'my' && (
        <>
          <div className="section-header">
            <div className="section-title-row">
              <h2 className="section-title">自选股票池</h2>
              <span className="section-desc">已选 {watchlist.length}/{MAX_WATCHLIST} 只</span>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              {watchlist.length > 0 && (
                <button className="btn btn-primary" onClick={handleAnalyze} disabled={analyzing}>
                  {analyzing ? 'AI分析中...' : 'AI操作建议'}
                </button>
              )}
              {watchlist.length > 0 && (
                <button className="btn" onClick={() => setShowPortfolio(!showPortfolio)}>
                  {showPortfolio ? '▲ 收起仓位' : '▼ 展开仓位'}
                </button>
              )}
              {watchlist.length < MAX_WATCHLIST && (
                <button className="btn" onClick={() => setShowAdd(!showAdd)}>
                  {showAdd ? '收起' : '+ 添加股票'}
                </button>
              )}
            </div>
          </div>

          {showAdd && (
            <div className="watchlist-add-panel">
              <input type="text" className="watchlist-search" placeholder="搜索股票名称或代码..."
                value={searchText} onChange={e => setSearchText(e.target.value)} autoFocus />
              <div className="watchlist-stock-grid">
                {filteredStocks.map(s => (
                  <button key={s.code} className="watchlist-stock-chip" onClick={() => handleAdd(s)} disabled={addLoading}>
                    <span className="chip-name">{s.name}</span>
                    <span className="chip-code">{s.code}</span>
                    <span className={`chip-market chip-market-${s.market}`}>{s.market}</span>
                  </button>
                ))}
                {filteredStocks.length === 0 && (
                  <div style={{ padding: '12px 0', color: 'var(--text-muted)', fontSize: 13 }}>
                    {searchText ? '无匹配股票' : '所有股票已在自选中'}
                  </div>
                )}
              </div>
            </div>
          )}

          {loading ? (
            <div className="loading"><div className="loading-dot" /><div className="loading-dot" /><div className="loading-dot" /></div>
          ) : watchlist.length === 0 ? (
            <div className="empty-state">
              <div className="empty-state-icon">📋</div>
              <div className="empty-state-title">暂无自选股</div>
              <div className="empty-state-desc">点击「+ 添加股票」从60只房地产股中选择您关注的标的</div>
            </div>
          ) : (
            <div className="watchlist-cards">
              {watchlist.map(w => {
                const a = analysisMap[w.stock_code]
                const sugStyle = a ? (SUGGESTION_COLORS[a.suggestion] || SUGGESTION_COLORS['观望']) : null
                const ratingColor = a?.latest_rating ? (RATING_COLORS[a.latest_rating] || '#6b7280') : '#6b7280'
                return (
                  <div key={w.stock_code} className="watchlist-card">
                    <div className="watchlist-card-header">
                      <div className="watchlist-card-info">
                        <span className="watchlist-card-name">{w.stock_name}</span>
                        <span className="watchlist-card-code">{w.stock_code}</span>
                        <span className={`watchlist-card-market market-${w.market}`}>{w.market}</span>
                      </div>
                      <button className="watchlist-remove-btn" onClick={() => handleRemove(w.stock_code)} title="移除">×</button>
                    </div>
                    {a && (
                      <div className="watchlist-card-analysis">
                        <div className="watchlist-card-scores">
                          <div className="watchlist-score-item">
                            <span className="score-label">评分</span>
                            <span className="score-value">{a.latest_score != null ? a.latest_score.toFixed(1) : '-'}</span>
                          </div>
                          <div className="watchlist-score-item">
                            <span className="score-label">变化</span>
                            <span className={`score-value ${a.score_change > 0 ? 'up' : a.score_change < 0 ? 'down' : ''}`}>
                              {a.score_change != null ? `${a.score_change > 0 ? '+' : ''}${a.score_change}` : '-'}
                            </span>
                          </div>
                          <div className="watchlist-score-item">
                            <span className="score-label">评级</span>
                            <span className="score-value" style={{ color: ratingColor }}>{a.latest_rating || '-'}</span>
                          </div>
                        </div>
                        <div className="watchlist-suggestion" style={{ background: sugStyle?.bg, color: sugStyle?.color, borderColor: sugStyle?.border }}>
                          <span className="suggestion-tag">{a.suggestion}</span>
                          <span className="suggestion-reason">{a.reason}</span>
                        </div>
                      </div>
                    )}
                    {!a && !analyzing && <div className="watchlist-card-placeholder">点击「AI操作建议」获取分析</div>}
                    {!a && analyzing && <div className="watchlist-card-placeholder analyzing"><div className="loading-dot" /><div className="loading-dot" /><div className="loading-dot" /></div>}
                  </div>
                )
              })}
            </div>
          )}

          {/* 自选股日报 */}
          {watchlist.length > 0 && <DailyDigestPanel type="watchlist" />}

          {/* 模拟仓位 */}
          {showPortfolio && watchlist.length > 0 && (
            <div className="portfolio-section">
              <div className="portfolio-header">
                <h3 className="portfolio-title">模拟仓位配置</h3>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                  <span className={`portfolio-total ${Math.abs(totalWeight - 100) < 0.01 ? 'valid' : totalWeight > 0 ? 'invalid' : ''}`}>
                    合计: {totalWeight.toFixed(1)}%
                  </span>
                  <button className="btn btn-sm" onClick={handleEqualWeight}>均分</button>
                  <button className="btn btn-sm btn-primary" onClick={handleSaveWeights} disabled={savingWeights || !hasWeightChanges}>
                    {savingWeights ? '保存中...' : '保存'}
                  </button>
                </div>
              </div>
              <div className="portfolio-grid">
                {watchlist.map(w => (
                  <div key={w.stock_code} className="portfolio-item">
                    <div className="portfolio-stock-info">
                      <span className="portfolio-stock-name">{w.stock_name}</span>
                      <span className="portfolio-stock-code">{w.stock_code}</span>
                    </div>
                    <div className="portfolio-weight-input-wrap">
                      <input type="number" className="portfolio-weight-input" value={weights[w.stock_code] || ''} onChange={e => handleWeightChange(w.stock_code, e.target.value)} placeholder="0" min="0" max="100" step="0.1" />
                      <span className="portfolio-weight-unit">%</span>
                    </div>
                    <div className="portfolio-weight-bar">
                      <div className="portfolio-weight-bar-fill" style={{ width: `${Math.min(100, weights[w.stock_code] || 0)}%` }} />
                    </div>
                  </div>
                ))}
              </div>
              <PerformancePanel performance={performance} perfDays={perfDays} setPerfDays={setPerfDays} loadPerformance={loadPerformance} perfLoading={perfLoading} />
            </div>
          )}
        </>
      )}

      {/* ===== AI推荐选股 ===== */}
      {subTab === 'ai' && (
        <div className="ai-picks-section">
          <div className="section-header">
            <div className="section-title-row">
              <h2 className="section-title">AI推荐选股组合</h2>
              <span className="section-desc">三模型融合，每日自动生成最优组合</span>
            </div>
            <button className="btn btn-primary" onClick={() => loadAIPicks(true)} disabled={aiPicksLoading}>
              {aiPicksLoading ? '生成中...' : '刷新推荐'}
            </button>
          </div>

          {aiPicksLoading && !aiPicks && (
            <div className="loading" style={{ padding: '40px 0' }}><div className="loading-dot" /><div className="loading-dot" /><div className="loading-dot" /></div>
          )}

          {aiPicks && (
            <>
              <div className="ai-picks-meta">
                <span>生成日期: {aiPicks.generated_date}</span>
                <span>模型: {aiPicks.model_sources}</span>
              </div>

              <div className="ai-picks-grid">
                {aiPicks.picks.map(p => (
                  <div key={p.stock_code} className="ai-pick-card">
                    <div className="ai-pick-header">
                      <div>
                        <span className="ai-pick-name">{p.stock_name}</span>
                        <span className="ai-pick-code">{p.stock_code}</span>
                        <span className={`chip-market chip-market-${p.market}`}>{p.market}</span>
                      </div>
                      <span className="ai-pick-weight">{p.weight.toFixed(1)}%</span>
                    </div>
                    <div className="ai-pick-body">
                      {p.rating && (
                        <span className="ai-pick-rating" style={{ color: RATING_COLORS[p.rating] || '#6b7280' }}>
                          {p.rating} {p.score != null ? `${p.score.toFixed(1)}分` : ''}
                        </span>
                      )}
                      <span className="ai-pick-reason">{p.reason}</span>
                    </div>
                    <div className="ai-pick-bar">
                      <div className="ai-pick-bar-fill" style={{ width: `${Math.min(100, p.weight)}%` }} />
                    </div>
                  </div>
                ))}
              </div>

              {aiPicks.performance && (
                <div className="portfolio-section" style={{ marginTop: 16 }}>
                  <PerformancePanel
                    performance={aiPicks.performance}
                    perfDays={aiPicksDays}
                    setPerfDays={setAiPicksDays}
                    loadPerformance={(d) => loadAIPicks(false, d)}
                    perfLoading={aiPicksLoading}
                  />
                </div>
              )}
            </>
          )}
        </div>
      )}

      <style>{`
        .sub-tabs { display: flex; gap: 0; margin-bottom: 16px; border-bottom: 2px solid var(--border, #e5e7eb); }
        .sub-tab { padding: 10px 24px; border: none; background: none; font-size: 15px; font-weight: 500; color: var(--text-muted, #6b7280); cursor: pointer; border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all 0.2s; }
        .sub-tab:hover { color: var(--primary, #667eea); }
        .sub-tab.active { color: var(--primary, #667eea); border-bottom-color: var(--primary, #667eea); font-weight: 600; }

        .watchlist-section { margin-top: 16px; }
        .watchlist-add-panel { background: var(--card-bg, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 12px; padding: 16px; margin-top: 12px; }
        .watchlist-search { width: 100%; padding: 10px 14px; border: 1px solid var(--border, #e5e7eb); border-radius: 8px; font-size: 14px; outline: none; background: var(--bg, #f9fafb); margin-bottom: 12px; }
        .watchlist-search:focus { border-color: var(--primary, #667eea); box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.15); }
        .watchlist-stock-grid { display: flex; flex-wrap: wrap; gap: 8px; max-height: 200px; overflow-y: auto; }
        .watchlist-stock-chip { display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; border: 1px solid var(--border, #e5e7eb); border-radius: 20px; background: var(--card-bg, #fff); cursor: pointer; font-size: 13px; transition: all 0.15s; }
        .watchlist-stock-chip:hover { border-color: var(--primary, #667eea); background: rgba(102, 126, 234, 0.05); }
        .watchlist-stock-chip:disabled { opacity: 0.5; cursor: wait; }
        .chip-name { font-weight: 500; }
        .chip-code { color: var(--text-muted, #9ca3af); font-size: 12px; }
        .chip-market { font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500; }
        .chip-market-A { background: #dbeafe; color: #1e40af; }
        .chip-market-HK { background: #fef3c7; color: #92400e; }
        .chip-market-US { background: #dcfce7; color: #166534; }
        .watchlist-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; margin-top: 16px; }
        .watchlist-card { background: var(--card-bg, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 12px; padding: 16px; transition: box-shadow 0.2s; }
        .watchlist-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
        .watchlist-card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px; }
        .watchlist-card-info { display: flex; align-items: center; gap: 8px; }
        .watchlist-card-name { font-weight: 600; font-size: 15px; }
        .watchlist-card-code { color: var(--text-muted, #9ca3af); font-size: 12px; }
        .watchlist-card-market { font-size: 10px; padding: 1px 6px; border-radius: 4px; font-weight: 500; }
        .market-A { background: #dbeafe; color: #1e40af; }
        .market-HK { background: #fef3c7; color: #92400e; }
        .market-US { background: #dcfce7; color: #166534; }
        .watchlist-remove-btn { width: 24px; height: 24px; border: none; background: transparent; color: var(--text-muted, #9ca3af); font-size: 18px; cursor: pointer; border-radius: 50%; display: flex; align-items: center; justify-content: center; transition: all 0.15s; }
        .watchlist-remove-btn:hover { background: #fee2e2; color: #ef4444; }
        .watchlist-card-analysis { display: flex; flex-direction: column; gap: 10px; }
        .watchlist-card-scores { display: flex; gap: 16px; }
        .watchlist-score-item { display: flex; flex-direction: column; gap: 2px; }
        .score-label { font-size: 11px; color: var(--text-muted, #9ca3af); }
        .score-value { font-size: 16px; font-weight: 600; }
        .score-value.up { color: #10b981; }
        .score-value.down { color: #ef4444; }
        .watchlist-suggestion { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-radius: 8px; border: 1px solid; font-size: 13px; }
        .suggestion-tag { font-weight: 600; white-space: nowrap; font-size: 14px; }
        .suggestion-reason { flex: 1; line-height: 1.5; }
        .watchlist-card-placeholder { color: var(--text-muted, #9ca3af); font-size: 13px; padding: 8px 0; }
        .watchlist-card-placeholder.analyzing { display: flex; gap: 4px; align-items: center; }

        @media (max-width: 768px) {
          .watchlist-cards { grid-template-columns: 1fr; }
          .portfolio-grid { grid-template-columns: 1fr; }
          .ai-picks-grid { grid-template-columns: 1fr !important; }
        }

        .portfolio-section { margin-top: 20px; background: var(--card-bg, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 12px; padding: 20px; }
        .portfolio-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
        .portfolio-title { font-size: 16px; font-weight: 600; margin: 0; }
        .portfolio-total { font-size: 13px; font-weight: 600; padding: 2px 10px; border-radius: 12px; background: #f3f4f6; color: #6b7280; }
        .portfolio-total.valid { background: #dcfce7; color: #166534; }
        .portfolio-total.invalid { background: #fee2e2; color: #991b1b; }
        .btn-sm { padding: 4px 12px; font-size: 12px; border-radius: 6px; }
        .portfolio-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
        .portfolio-item { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border: 1px solid var(--border, #e5e7eb); border-radius: 8px; background: var(--bg, #f9fafb); }
        .portfolio-stock-info { flex: 1; min-width: 0; }
        .portfolio-stock-name { font-weight: 500; font-size: 13px; display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .portfolio-stock-code { font-size: 11px; color: var(--text-muted, #9ca3af); }
        .portfolio-weight-input-wrap { display: flex; align-items: center; gap: 2px; }
        .portfolio-weight-input { width: 56px; padding: 4px 6px; border: 1px solid var(--border, #e5e7eb); border-radius: 6px; font-size: 13px; text-align: right; outline: none; background: var(--card-bg, #fff); }
        .portfolio-weight-input:focus { border-color: var(--primary, #667eea); box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.15); }
        .portfolio-weight-unit { font-size: 12px; color: var(--text-muted, #9ca3af); }
        .portfolio-weight-bar { width: 50px; height: 6px; background: #e5e7eb; border-radius: 3px; overflow: hidden; }
        .portfolio-weight-bar-fill { height: 100%; background: var(--primary, #667eea); border-radius: 3px; transition: width 0.2s; }
        .portfolio-perf { margin-top: 20px; padding-top: 20px; border-top: 1px solid var(--border, #e5e7eb); }
        .portfolio-perf-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
        .portfolio-perf-title { font-size: 15px; font-weight: 600; margin: 0; }
        .portfolio-perf-days { display: flex; gap: 6px; }
        .portfolio-perf-stats { display: flex; gap: 24px; margin-bottom: 16px; flex-wrap: wrap; }
        .perf-stat { display: flex; flex-direction: column; gap: 4px; }
        .perf-stat-label { font-size: 12px; color: var(--text-muted, #9ca3af); }
        .perf-stat-value { font-size: 20px; font-weight: 700; }
        .perf-stat-value.up { color: #10b981; }
        .perf-stat-value.down { color: #ef4444; }
        .portfolio-chart { margin-bottom: 16px; background: var(--bg, #f9fafb); border-radius: 8px; padding: 12px; }
        .portfolio-chart svg { width: 100%; height: auto; }
        .portfolio-table-wrap { max-height: 300px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border, #e5e7eb); }
        .portfolio-table { width: 100%; border-collapse: collapse; font-size: 13px; }
        .portfolio-table th { background: var(--bg, #f9fafb); padding: 8px 12px; text-align: left; font-weight: 600; position: sticky; top: 0; border-bottom: 1px solid var(--border, #e5e7eb); }
        .portfolio-table td { padding: 6px 12px; border-bottom: 1px solid var(--border, #e5e7eb); }
        .portfolio-table td.up { color: #10b981; font-weight: 500; }
        .portfolio-table td.down { color: #ef4444; font-weight: 500; }
        .chart-legend { display: flex; gap: 16px; margin-bottom: 8px; font-size: 11px; color: #6b7280; justify-content: center; }
        .chart-legend-item { display: flex; align-items: center; gap: 4px; }
        .chart-legend-dot { width: 12px; height: 3px; border-radius: 2px; }

        .ai-picks-section { margin-top: 8px; }
        .ai-picks-meta { display: flex; gap: 16px; font-size: 12px; color: var(--text-muted, #9ca3af); margin-bottom: 12px; }
        .ai-picks-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
        .ai-pick-card { background: var(--card-bg, #fff); border: 1px solid var(--border, #e5e7eb); border-radius: 10px; padding: 14px; transition: box-shadow 0.2s; }
        .ai-pick-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); }
        .ai-pick-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .ai-pick-name { font-weight: 600; font-size: 14px; margin-right: 6px; }
        .ai-pick-code { color: var(--text-muted, #9ca3af); font-size: 12px; margin-right: 6px; }
        .ai-pick-weight { font-size: 18px; font-weight: 700; color: var(--primary, #667eea); }
        .ai-pick-body { display: flex; align-items: center; gap: 8px; font-size: 13px; color: #555; margin-bottom: 8px; }
        .ai-pick-rating { font-weight: 600; white-space: nowrap; }
        .ai-pick-reason { flex: 1; line-height: 1.5; }
        .ai-pick-bar { height: 4px; background: #e5e7eb; border-radius: 2px; overflow: hidden; }
        .ai-pick-bar-fill { height: 100%; background: var(--primary, #667eea); border-radius: 2px; transition: width 0.3s; }
      `}</style>
    </div>
  )
}


function PerformancePanel({ performance, perfDays, setPerfDays, loadPerformance, perfLoading }) {
  if (perfLoading && !performance) {
    return <div className="loading" style={{ padding: '20px 0' }}><div className="loading-dot" /><div className="loading-dot" /><div className="loading-dot" /></div>
  }
  if (!performance || !performance.daily_returns || performance.daily_returns.length === 0) return null

  const hasBenchmark = performance.daily_returns.some(d => d.benchmark_hs300 != null)

  return (
    <div className="portfolio-perf">
      <div className="portfolio-perf-header">
        <h4 className="portfolio-perf-title">组合收益率</h4>
        <div className="portfolio-perf-days">
          {[7, 30, 90].map(d => (
            <button key={d} className={`btn btn-sm ${perfDays === d ? 'btn-primary' : ''}`}
              onClick={() => { setPerfDays(d); loadPerformance(d) }}>
              {d}天
            </button>
          ))}
        </div>
      </div>
      <div className="portfolio-perf-stats">
        <div className="perf-stat">
          <span className="perf-stat-label">组合总收益</span>
          <span className={`perf-stat-value ${performance.total_return >= 0 ? 'up' : 'down'}`}>
            {performance.total_return >= 0 ? '+' : ''}{performance.total_return.toFixed(2)}%
          </span>
        </div>
        {performance.annualized_return != null && (
          <div className="perf-stat">
            <span className="perf-stat-label">年化收益率</span>
            <span className={`perf-stat-value ${performance.annualized_return >= 0 ? 'up' : 'down'}`}>
              {performance.annualized_return >= 0 ? '+' : ''}{performance.annualized_return.toFixed(2)}%
            </span>
          </div>
        )}
        {performance.max_drawdown != null && (
          <div className="perf-stat">
            <span className="perf-stat-label">最大回撤</span>
            <span className="perf-stat-value down">-{performance.max_drawdown.toFixed(2)}%</span>
          </div>
        )}
        {hasBenchmark && (() => {
          const last = performance.daily_returns[performance.daily_returns.length - 1]
          return <>
            {last.benchmark_hs300 != null && (
              <div className="perf-stat">
                <span className="perf-stat-label">沪深300</span>
                <span className={`perf-stat-value ${last.benchmark_hs300 >= 0 ? 'up' : 'down'}`} style={{ fontSize: 16 }}>
                  {last.benchmark_hs300 >= 0 ? '+' : ''}{last.benchmark_hs300.toFixed(2)}%
                </span>
              </div>
            )}
            {last.benchmark_realestate != null && (
              <div className="perf-stat">
                <span className="perf-stat-label">地产指数</span>
                <span className={`perf-stat-value ${last.benchmark_realestate >= 0 ? 'up' : 'down'}`} style={{ fontSize: 16 }}>
                  {last.benchmark_realestate >= 0 ? '+' : ''}{last.benchmark_realestate.toFixed(2)}%
                </span>
              </div>
            )}
          </>
        })()}
      </div>

      <div className="portfolio-chart">
        {hasBenchmark && (
          <div className="chart-legend">
            <div className="chart-legend-item"><div className="chart-legend-dot" style={{ background: '#667eea' }} /> 组合</div>
            <div className="chart-legend-item"><div className="chart-legend-dot" style={{ background: '#f59e0b' }} /> 沪深300</div>
            <div className="chart-legend-item"><div className="chart-legend-dot" style={{ background: '#8b5cf6' }} /> 地产指数</div>
          </div>
        )}
        <PerformanceChart data={performance.daily_returns} />
      </div>

      <div className="portfolio-table-wrap">
        <table className="portfolio-table">
          <thead>
            <tr>
              <th>日期</th>
              <th>日收益率</th>
              <th>累计收益率</th>
              {hasBenchmark && <th>沪深300</th>}
              {hasBenchmark && <th>地产指数</th>}
            </tr>
          </thead>
          <tbody>
            {[...performance.daily_returns].reverse().slice(0, 10).map(d => (
              <tr key={d.date}>
                <td>{d.date}</td>
                <td className={d.daily_return >= 0 ? 'up' : 'down'}>
                  {d.daily_return >= 0 ? '+' : ''}{d.daily_return.toFixed(2)}%
                </td>
                <td className={d.cumulative_return >= 0 ? 'up' : 'down'}>
                  {d.cumulative_return >= 0 ? '+' : ''}{d.cumulative_return.toFixed(2)}%
                </td>
                {hasBenchmark && (
                  <td className={d.benchmark_hs300 != null ? (d.benchmark_hs300 >= 0 ? 'up' : 'down') : ''}>
                    {d.benchmark_hs300 != null ? `${d.benchmark_hs300 >= 0 ? '+' : ''}${d.benchmark_hs300.toFixed(2)}%` : '-'}
                  </td>
                )}
                {hasBenchmark && (
                  <td className={d.benchmark_realestate != null ? (d.benchmark_realestate >= 0 ? 'up' : 'down') : ''}>
                    {d.benchmark_realestate != null ? `${d.benchmark_realestate >= 0 ? '+' : ''}${d.benchmark_realestate.toFixed(2)}%` : '-'}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {perfLoading && (
        <div className="loading" style={{ padding: '10px 0' }}><div className="loading-dot" /><div className="loading-dot" /><div className="loading-dot" /></div>
      )}
    </div>
  )
}


function PerformanceChart({ data }) {
  if (!data || data.length < 2) return null

  const width = 800, height = 220
  const padding = { top: 20, right: 20, bottom: 30, left: 50 }
  const chartW = width - padding.left - padding.right
  const chartH = height - padding.top - padding.bottom

  const hasBm = data.some(d => d.benchmark_hs300 != null)
  const allValues = [
    ...data.map(d => d.cumulative_return),
    ...(hasBm ? data.filter(d => d.benchmark_hs300 != null).map(d => d.benchmark_hs300) : []),
    ...(hasBm ? data.filter(d => d.benchmark_realestate != null).map(d => d.benchmark_realestate) : []),
    0,
  ]
  const minV = Math.min(...allValues)
  const maxV = Math.max(...allValues)
  const range = maxV - minV || 1

  const xScale = (i) => padding.left + (i / (data.length - 1)) * chartW
  const yScale = (v) => padding.top + chartH - ((v - minV) / range) * chartH

  const makeLine = (vals) => vals.map((v, i) => `${xScale(i)},${yScale(v)}`).join(' ')

  const cumVals = data.map(d => d.cumulative_return)
  const points = makeLine(cumVals)
  const zeroY = yScale(0)

  const areaPoints = [`${xScale(0)},${zeroY}`, ...data.map((d, i) => `${xScale(i)},${yScale(d.cumulative_return)}`), `${xScale(data.length - 1)},${zeroY}`].join(' ')
  const lastVal = cumVals[cumVals.length - 1]
  const lineColor = lastVal >= 0 ? '#667eea' : '#ef4444'
  const fillColor = lastVal >= 0 ? 'rgba(102,126,234,0.08)' : 'rgba(239,68,68,0.08)'

  const yTicks = 5
  const yLabels = Array.from({ length: yTicks + 1 }, (_, i) => minV + (range / yTicks) * i)
  const xLabelCount = Math.min(6, data.length)
  const xStep = Math.max(1, Math.floor((data.length - 1) / (xLabelCount - 1)))

  // Benchmark lines
  let hs300Line = null, reLine = null
  if (hasBm) {
    const hs300Vals = data.map(d => d.benchmark_hs300 ?? 0)
    const reVals = data.map(d => d.benchmark_realestate ?? 0)
    hs300Line = makeLine(hs300Vals)
    reLine = makeLine(reVals)
  }

  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet">
      {yLabels.map((v, i) => (
        <g key={i}>
          <line x1={padding.left} y1={yScale(v)} x2={width - padding.right} y2={yScale(v)} stroke="#e5e7eb" strokeWidth="1" strokeDasharray={v === 0 ? '' : '4,4'} />
          <text x={padding.left - 6} y={yScale(v) + 4} textAnchor="end" fontSize="10" fill="#9ca3af">{v.toFixed(1)}%</text>
        </g>
      ))}
      <line x1={padding.left} y1={zeroY} x2={width - padding.right} y2={zeroY} stroke="#9ca3af" strokeWidth="1" />
      <polygon points={areaPoints} fill={fillColor} />
      {hs300Line && <polyline points={hs300Line} fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="4,3" opacity="0.7" />}
      {reLine && <polyline points={reLine} fill="none" stroke="#8b5cf6" strokeWidth="1.5" strokeDasharray="4,3" opacity="0.7" />}
      <polyline points={points} fill="none" stroke={lineColor} strokeWidth="2" />
      {Array.from({ length: xLabelCount }, (_, i) => {
        const idx = Math.min(i * xStep, data.length - 1)
        return <text key={i} x={xScale(idx)} y={height - 6} textAnchor="middle" fontSize="10" fill="#9ca3af">{data[idx].date.slice(5)}</text>
      })}
    </svg>
  )
}
