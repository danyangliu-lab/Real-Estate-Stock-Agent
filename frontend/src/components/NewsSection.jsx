import { useState, useEffect } from 'react'
import { api } from '../api'

export default function NewsSection() {
  const [news, setNews] = useState({ industry_news: [], stock_news: [] })
  const [loading, setLoading] = useState(true)
  const [collapsed, setCollapsed] = useState(false)

  useEffect(() => {
    loadNews()
    const timer = setInterval(loadNews, 300000) // 5分钟刷新
    return () => clearInterval(timer)
  }, [])

  async function loadNews() {
    try {
      const data = await api.getNews()
      setNews(data)
    } catch (e) {
      console.error('获取资讯失败:', e)
    } finally {
      setLoading(false)
    }
  }

  const allNews = news.industry_news || []

  if (loading) {
    return (
      <div className="news-section">
        <div className="news-header">
          <h3>📰 房地产政策资讯</h3>
        </div>
        <div className="news-loading">加载资讯中...</div>
      </div>
    )
  }

  if (allNews.length === 0) {
    return null
  }

  return (
    <div className="news-section">
      <div className="news-header" onClick={() => setCollapsed(!collapsed)}>
        <h3>📰 房地产政策资讯</h3>
        <span className="news-toggle">{collapsed ? '展开' : '收起'}</span>
        <span className="news-count">{allNews.length} 条</span>
      </div>
      {!collapsed && (
        <div className="news-list">
          {allNews.map((item, idx) => (
            <div key={idx} className="news-item">
              <span className="news-source">{item.source}</span>
              {item.url ? (
                <a href={item.url} target="_blank" rel="noopener noreferrer" className="news-title">
                  {item.title}
                </a>
              ) : (
                <span className="news-title">{item.title}</span>
              )}
              {item.time && <span className="news-time">{item.time}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
