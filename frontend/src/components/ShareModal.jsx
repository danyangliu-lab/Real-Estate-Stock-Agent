import { useState } from 'react'

export default function ShareModal({ title, url, onClose }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback
      const input = document.createElement('input')
      input.value = url
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content share-modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>分享到微信</h3>
          <button className="detail-close" onClick={onClose}>×</button>
        </div>
        <div className="share-modal-body">
          <div className="share-modal-title">{title}</div>
          <div className="share-modal-url-box">
            <input
              type="text"
              readOnly
              value={url}
              className="share-modal-url"
              onClick={e => e.target.select()}
            />
            <button
              className={`btn btn-primary btn-sm share-copy-btn ${copied ? 'copied' : ''}`}
              onClick={handleCopy}
            >
              {copied ? '已复制' : '复制链接'}
            </button>
          </div>
          <div className="share-modal-tips">
            <div className="share-tip-title">分享到微信朋友圈</div>
            <div className="share-tip-steps">
              <div className="share-tip-step">
                <span className="step-num">1</span>
                <span>点击「复制链接」</span>
              </div>
              <div className="share-tip-step">
                <span className="step-num">2</span>
                <span>打开微信，发朋友圈或发送给好友</span>
              </div>
              <div className="share-tip-step">
                <span className="step-num">3</span>
                <span>粘贴链接即可，对方无需登录即可查看</span>
              </div>
            </div>
          </div>
          <a
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            className="share-preview-link"
          >
            预览分享页面 →
          </a>
        </div>
      </div>
    </div>
  )
}
