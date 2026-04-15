import React, { useState, useEffect, useCallback } from 'react'
import { api, removeToken } from './api'
import LoginPage from './components/LoginPage'
import DetailPanel from './components/DetailPanel'
import RatingMethodology from './components/RatingMethodology'
import RatingTable from './components/RatingTable'
import StatsCards from './components/StatsCards'
import CommentarySection from './components/CommentarySection'
import ReportSection from './components/ReportSection'
import UserManagement from './components/UserManagement'
import WatchlistSection from './components/WatchlistSection'
import WeeklyDigestPanel from './components/WeeklyDigestPanel'
import REITsSection from './components/REITsSection'

const BASE_TABS = [
  { key: 'rating', label: 'AI评级' },
  { key: 'watchlist', label: '自选股' },
  { key: 'reits', label: 'REITs · 周度组合' },
  { key: 'commentary', label: '市场点评' },
  { key: 'report', label: '研究报告' },
]

const MARKET_FILTERS = [
  { value: '', label: '全部市场' },
  { value: 'A', label: 'A股' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
]

const RATING_FILTERS = [
  { value: '', label: '全部评级' },
  { value: '优选', label: '优选' },
  { value: '关注', label: '关注' },
  { value: '中性', label: '中性' },
  { value: '谨慎', label: '谨慎' },
]

const AUTO_REFRESH_INTERVAL = 30000

const MODEL_OPTIONS = [
  { value: 'quant_ai', label: '量化AI选股' },
  { value: 'soochow', label: '东吴地产选股' },
]

export default function App() {
  const [user, setUser] = useState(null)
  const [authChecked, setAuthChecked] = useState(false)
  const [activeTab, setActiveTab] = useState('rating')

  // 评级页状态
  const [modelType, setModelType] = useState('quant_ai')
  const [dashboard, setDashboard] = useState(null)
  const [ratings, setRatings] = useState([])
  const [loading, setLoading] = useState(true)
  const [selectedStock, setSelectedStock] = useState(null)
  const [annCache, setAnnCache] = useState({})
  const [marketFilter, setMarketFilter] = useState('')
  const [ratingFilter, setRatingFilter] = useState('')
  const [sortBy, setSortBy] = useState('total_score')
  const [sortDir, setSortDir] = useState('desc')
  const [dates, setDates] = useState([])
  const [selectedDate, setSelectedDate] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [refreshRunning, setRefreshRunning] = useState(false)

  // 检查已有的登录状态
  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      api.getMe()
        .then(u => setUser(u))
        .catch(() => removeToken())
        .finally(() => setAuthChecked(true))
    } else {
      setAuthChecked(true)
    }
  }, [])

  // 监听 token 过期事件
  useEffect(() => {
    const handler = () => { setUser(null) }
    window.addEventListener('auth-expired', handler)
    return () => window.removeEventListener('auth-expired', handler)
  }, [])

  const loadData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const [dash, avDates] = await Promise.all([
        api.getDashboard(modelType),
        api.getAvailableDates(modelType),
      ])
      setDashboard(dash)
      setDates(avDates)

      let data
      if (selectedDate) {
        data = await api.getRatingsByDate(selectedDate, marketFilter || undefined, modelType)
      } else {
        data = await api.getLatestRatings({
          market: marketFilter || undefined,
          rating: ratingFilter || undefined,
          sort_by: sortBy,
          sort_dir: sortDir,
          model_type: modelType,
        })
      }
      setRatings(data)
    } catch (err) {
      console.error('加载数据失败:', err)
    }
    if (!silent) setLoading(false)
  }, [marketFilter, ratingFilter, sortBy, sortDir, selectedDate, modelType])

  useEffect(() => {
    if (user && activeTab === 'rating') loadData()
  }, [user, activeTab, loadData])

  const hasFilter = marketFilter || ratingFilter || selectedDate
  const isRatingIncomplete = dashboard && dashboard.rated_today < dashboard.total_stocks

  useEffect(() => {
    if (user && activeTab === 'rating' && !loading && !hasFilter && isRatingIncomplete) {
      const timer = setInterval(() => loadData(true), AUTO_REFRESH_INTERVAL)
      return () => clearInterval(timer)
    }
  }, [user, activeTab, loading, hasFilter, isRatingIncomplete, loadData])

  const handleSort = (col) => {
    if (sortBy === col) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc')
    } else {
      setSortBy(col)
      setSortDir('desc')
    }
  }

  const handleSelectStock = useCallback((stock) => {
    setSelectedStock(stock)
    if (stock && !annCache[stock.code]) {
      api.getAnnouncements(stock.code, 90, 10)
        .then(data => setAnnCache(prev => ({ ...prev, [stock.code]: data || [] })))
        .catch(() => setAnnCache(prev => ({ ...prev, [stock.code]: [] })))
    }
  }, [annCache])

  const handleLogout = () => {
    removeToken()
    setUser(null)
  }

  // 管理员手动刷新评分
  const handleAdminRefresh = async () => {
    const confirmed = window.confirm(
      '⚠️ 确认要刷新全体股票评分吗？\n\n此操作将重新计算所有60只股票的双模型评级，预计需要5-10分钟完成。'
    )
    if (!confirmed) return

    const confirmed2 = window.confirm(
      '再次确认：刷新评分将消耗大量API资源，确定执行？'
    )
    if (!confirmed2) return

    setRefreshing(true)
    try {
      await api.adminRefreshRatings()
      setRefreshRunning(true)
      alert('评分刷新已启动，将在后台执行。页面会自动刷新数据。')
    } catch (e) {
      alert('刷新失败: ' + (e.message || '未知错误'))
      setRefreshing(false)
    }
  }

  // 轮询刷新状态
  useEffect(() => {
    if (!refreshRunning) return
    const timer = setInterval(async () => {
      try {
        const status = await api.adminRefreshStatus()
        if (!status.running) {
          setRefreshRunning(false)
          setRefreshing(false)
          loadData()
        }
      } catch {}
    }, 15000)
    return () => clearInterval(timer)
  }, [refreshRunning, loadData])

  if (!authChecked) {
    return (
      <div className="loading" style={{ height: '100vh' }}>
        <div className="loading-dot" />
        <div className="loading-dot" />
        <div className="loading-dot" />
      </div>
    )
  }

  if (!user) {
    return <LoginPage onLogin={setUser} />
  }

  const tabs = user?.is_admin
    ? [...BASE_TABS, { key: 'users', label: '用户管理' }]
    : BASE_TABS

  return (
    <div>
      <header className="header">
        <div className="container header-inner">
          <div className="logo">
            <div className="logo-icon">AI</div>
            <span>AI Haoxing@东吴地产</span>
          </div>
          <nav className="nav-tabs">
            {tabs.map(t => (
              <button
                key={t.key}
                className={`nav-tab ${activeTab === t.key ? 'active' : ''}`}
                onClick={() => setActiveTab(t.key)}
              >
                {t.label}
              </button>
            ))}
          </nav>
          <div className="header-actions">
            <span className="user-info">
              {user.display_name || user.username}
              {user.is_admin && <span className="admin-badge">管理员</span>}
            </span>
            <button className="btn btn-sm" onClick={handleLogout}>退出</button>
          </div>
        </div>
      </header>

      <main className="container" style={{ paddingBottom: 40 }}>
        {activeTab === 'rating' && (
          <>
            {/* 模型切换 */}
            <div className="model-switcher">
              <div style={{ display: 'flex', gap: 0 }}>
                {MODEL_OPTIONS.map(m => (
                  <button
                    key={m.value}
                    className={`model-btn ${modelType === m.value ? 'active' : ''}`}
                    onClick={() => { setModelType(m.value); setSelectedDate('') }}
                  >
                    {m.label}
                  </button>
                ))}
              </div>
              {user?.is_admin && (
                <button
                  className="btn btn-sm"
                  style={{
                    background: refreshing ? '#f3f4f6' : '#fee2e2',
                    color: refreshing ? '#9ca3af' : '#991b1b',
                    border: '1px solid',
                    borderColor: refreshing ? '#d1d5db' : '#fca5a5',
                    fontWeight: 500,
                  }}
                  onClick={handleAdminRefresh}
                  disabled={refreshing}
                >
                  {refreshing ? '评分刷新中...' : '刷新全体评分'}
                </button>
              )}
            </div>

            <StatsCards dashboard={dashboard} modelType={modelType} />
            <WeeklyDigestPanel type="industry" />
            <RatingMethodology modelType={modelType} />

            <div className="filters">
              {MARKET_FILTERS.map(f => (
                <button
                  key={f.value}
                  className={`filter-chip ${marketFilter === f.value ? 'active' : ''}`}
                  onClick={() => { setMarketFilter(f.value); setSelectedDate('') }}
                >
                  {f.label}
                </button>
              ))}
              <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 4px' }} />
              {RATING_FILTERS.map(f => (
                <button
                  key={f.value}
                  className={`filter-chip ${ratingFilter === f.value ? 'active' : ''}`}
                  onClick={() => { setRatingFilter(f.value); setSelectedDate('') }}
                >
                  {f.label}
                </button>
              ))}
              <div style={{ width: 1, height: 20, background: 'var(--border)', margin: '0 4px' }} />
              <div className="date-picker-wrapper">
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>历史日期:</span>
                <select
                  className="date-input"
                  value={selectedDate}
                  onChange={e => setSelectedDate(e.target.value)}
                >
                  <option value="">最新</option>
                  {dates.map(d => (
                    <option key={d} value={d}>{d}</option>
                  ))}
                </select>
              </div>
            </div>

            {loading ? (
              <div className="loading">
                <div className="loading-dot" />
                <div className="loading-dot" />
                <div className="loading-dot" />
              </div>
            ) : ratings.length === 0 ? (
              hasFilter ? (
                <div className="empty-state">
                  <div className="empty-state-icon">📭</div>
                  <div className="empty-state-title">暂无匹配数据</div>
                  <div className="empty-state-desc">
                    当前筛选条件下没有评级数据，请尝试调整筛选条件
                  </div>
                </div>
              ) : (
                <div className="empty-state">
                  <div className="empty-state-icon">📊</div>
                  <div className="empty-state-title">评级计算中...</div>
                  <div className="empty-state-desc">
                    系统正在自动获取数据并计算评级，请稍候，页面将自动刷新
                  </div>
                  <div className="loading" style={{ marginTop: 16 }}>
                    <div className="loading-dot" />
                    <div className="loading-dot" />
                    <div className="loading-dot" />
                  </div>
                </div>
              )
            ) : (
              <RatingTable
                ratings={ratings}
                sortBy={sortBy}
                sortDir={sortDir}
                onSort={handleSort}
                onSelect={handleSelectStock}
              />
            )}
          </>
        )}

        {activeTab === 'watchlist' && <WatchlistSection user={user} />}
        {activeTab === 'reits' && <REITsSection user={user} />}
        {activeTab === 'commentary' && <CommentarySection user={user} />}
        {activeTab === 'report' && <ReportSection user={user} />}
        {activeTab === 'users' && user?.is_admin && <UserManagement />}
      </main>

      <footer className="footer">
        <div className="container">
          AI评级仅供参考, 不构成投资建议。投资有风险, 入市需谨慎。
        </div>
      </footer>

      {selectedStock && (
        <DetailPanel
          rating={selectedStock}
          modelType={modelType}
          cachedAnnouncements={annCache[selectedStock.code]}
          onClose={() => setSelectedStock(null)}
        />
      )}
    </div>
  )
}
