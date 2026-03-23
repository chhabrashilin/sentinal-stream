import React, { useState, useEffect } from 'react'

export default function Header({ lastUpdated }) {
  const [tick, setTick] = useState(true)

  useEffect(() => {
    const t = setInterval(() => setTick(v => !v), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <header className="app-header">
      <div className="header-brand">
        <div>
          <div className="header-title-row">
            <h1 className="header-title">Sentinel-Stream</h1>
            <span className="header-subtitle">Lake Mendota Digital Twin</span>
          </div>
          <div className="header-coords">UW-Madison · NTL-LTER Buoy · 43.0988° N, 89.4045° W</div>
        </div>
      </div>

      <div className="header-meta">
        {lastUpdated && (
          <div className="header-updated">Updated {lastUpdated}</div>
        )}
        <div className="live-badge">
          <span
            className="live-dot"
            style={{ opacity: tick ? 1 : 0.3, boxShadow: tick ? '0 0 6px var(--accent-green)' : 'none' }}
          />
          LIVE
        </div>
      </div>
    </header>
  )
}
