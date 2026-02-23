const BASE = '/api'

async function request(url, options = {}) {
  const res = await fetch(`${BASE}${url}`, options)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export const api = {
  getDashboard: () => request('/dashboard'),
  getStocks: (market) => request(`/stocks${market ? `?market=${market}` : ''}`),
  getLatestRatings: (params = {}) => {
    const qs = new URLSearchParams()
    if (params.market) qs.set('market', params.market)
    if (params.rating) qs.set('rating', params.rating)
    if (params.sort_by) qs.set('sort_by', params.sort_by)
    if (params.sort_dir) qs.set('sort_dir', params.sort_dir)
    const q = qs.toString()
    return request(`/ratings/latest${q ? `?${q}` : ''}`)
  },
  getRatingHistory: (code, days = 30) => request(`/ratings/history/${code}?days=${days}`),
  getRatingsByDate: (date, market) =>
    request(`/ratings/date/${date}${market ? `?market=${market}` : ''}`),
  getAvailableDates: () => request('/ratings/dates'),
  getPrices: (code, days = 60) => request(`/prices/${code}?days=${days}`),
  getRatingTrend: (code, days = 30) => request(`/rating-trend/${code}?days=${days}`),
}
