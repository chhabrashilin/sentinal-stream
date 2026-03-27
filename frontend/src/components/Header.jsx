import React, { useState, useEffect } from 'react'

function SignalBarsIcon() {
  return (
    <svg
      width="28"
      height="24"
      viewBox="0 0 28 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="bar1-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#00d9c0" />
          <stop offset="100%" stopColor="#00d9c0" stopOpacity="0.5" />
        </linearGradient>
        <linearGradient id="bar2-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#4f8eff" />
          <stop offset="100%" stopColor="#4f8eff" stopOpacity="0.5" />
        </linearGradient>
        <linearGradient id="bar3-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#a78bfa" />
          <stop offset="100%" stopColor="#a78bfa" stopOpacity="0.5" />
        </linearGradient>
        <linearGradient id="bar4-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#00d9c0" />
          <stop offset="100%" stopColor="#4f8eff" stopOpacity="0.6" />
        </linearGradient>
      </defs>
      {/* bar 1 - shortest */}
      <rect x="0" y="16" width="5" height="8" rx="1.5" fill="url(#bar1-grad)" />
      {/* bar 2 */}
      <rect x="7.5" y="10" width="5" height="14" rx="1.5" fill="url(#bar2-grad)" />
      {/* bar 3 */}
      <rect x="15" y="5" width="5" height="19" rx="1.5" fill="url(#bar3-grad)" />
      {/* bar 4 - tallest */}
      <rect x="22.5" y="0" width="5" height="24" rx="1.5" fill="url(#bar4-grad)" />
    </svg>
  )
}

export default function Header({ lastUpdated }) {
  const [pulse, setPulse] = useState(true)

  useEffect(() => {
    const t = setInterval(() => setPulse(v => !v), 1400)
    return () => clearInterval(t)
  }, [])

  return (
    <header className="app-header">
      <div className="header-brand">
        <div className="header-logo">
          <SignalBarsIcon />
        </div>
        <div className="header-identity">
          <div className="header-title-row">
            <h1 className="header-title">
              <span className="header-title__sentinel">Sentinel</span>
              <span className="header-title__sep">-</span>
              <span className="header-title__stream">Stream</span>
            </h1>
          </div>
          <div className="header-coords">
            Lake Mendota Digital Twin
            <span className="header-coords__sep">·</span>
            UW-Madison NTL-LTER
            <span className="header-coords__sep">·</span>
            43.0988° N, 89.4045° W
          </div>
        </div>
      </div>

      <div className="header-meta">
        {lastUpdated && (
          <div className="header-updated">
            <span className="header-updated__label">Last sync</span>
            <span className="header-updated__value">{lastUpdated}</span>
          </div>
        )}
        <div className={`live-badge ${pulse ? 'live-badge--active' : ''}`}>
          <span className="live-dot" />
          LIVE
        </div>
      </div>
    </header>
  )
}
