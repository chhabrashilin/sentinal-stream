import React from 'react'

const RISK_LEVEL = {
  low:      { color: '#00ceb4', bg: 'rgba(0,206,180,0.12)',    border: 'rgba(0,206,180,0.3)',    label: 'LOW' },
  moderate: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)',   border: 'rgba(245,158,11,0.3)',   label: 'MODERATE' },
  high:     { color: '#ff6b6b', bg: 'rgba(255,107,107,0.12)',  border: 'rgba(255,107,107,0.3)',  label: 'HIGH' },
  critical: { color: '#ff2d55', bg: 'rgba(255,45,85,0.15)',    border: 'rgba(255,45,85,0.4)',    label: 'CRITICAL' },
  unknown:  { color: '#64748b', bg: 'rgba(100,116,139,0.12)',  border: 'rgba(100,116,139,0.3)',  label: 'UNKNOWN' },
}

const RISK_ICON = { hab: '🌿', anoxia: '💧', turnover: '🌀', none: '—' }
const RISK_LABEL = { hab: 'HAB', anoxia: 'Anoxia', turnover: 'Turnover', none: 'None' }

function RiskBar({ label, value, color }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className="risk-bar">
      <div className="risk-bar__header">
        <span className="risk-bar__label">{label}</span>
        <span className="risk-bar__value" style={{ color }}>{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="risk-bar__track">
        <div
          className="risk-bar__fill"
          style={{ width: `${pct}%`, background: color, boxShadow: `0 0 6px ${color}60` }}
        />
      </div>
    </div>
  )
}

export default function ForesightCard({ foresight, loading }) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">48-Hour Foresight</div>
        <div className="state-center">Computing risk assessment...</div>
      </div>
    )
  }

  if (!foresight || foresight.error) {
    const noData = foresight?.status === 422
    return (
      <div className="card">
        <div className="card-title">48-Hour Foresight</div>
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">{noData ? 'No Data Yet' : 'Unavailable'}</div>
          <div className="state-hint">
            {noData ? 'Stream sensor data to enable foresight.' : 'Could not retrieve risk assessment.'}
          </div>
        </div>
      </div>
    )
  }

  const lvl = RISK_LEVEL[foresight.risk_level] ?? RISK_LEVEL.unknown
  const scores = foresight.risk_scores ?? {}
  const habColor    = RISK_LEVEL[scores.hab    >= 0.7 ? 'critical' : scores.hab    >= 0.5 ? 'high' : scores.hab    >= 0.3 ? 'moderate' : 'low'].color
  const anoxColor   = RISK_LEVEL[scores.anoxia >= 0.7 ? 'critical' : scores.anoxia >= 0.5 ? 'high' : scores.anoxia >= 0.3 ? 'moderate' : 'low'].color
  const turnColor   = RISK_LEVEL[scores.turnover >= 0.7 ? 'critical' : scores.turnover >= 0.5 ? 'high' : scores.turnover >= 0.3 ? 'moderate' : 'low'].color

  return (
    <div className="card foresight-card">
      <div className="card-header">
        <div>
          <div className="card-title">48-Hour Foresight</div>
          <div className="card-subtitle">HAB · Anoxia · Turnover risk assessment</div>
        </div>
        <div
          className="badge badge--sm badge--square"
          style={{ color: lvl.color, background: lvl.bg, borderColor: lvl.border }}
        >
          {RISK_ICON[foresight.primary_risk] ?? '?'} {lvl.label}
        </div>
      </div>

      {/* Aggregate risk score */}
      <div className="foresight-score">
        <div
          className="foresight-score__value"
          style={{ color: lvl.color, textShadow: `0 0 24px ${lvl.color}50` }}
        >
          {(foresight.risk_score * 100).toFixed(0)}
        </div>
        <div className="foresight-score__unit" style={{ color: lvl.color }}>/ 100</div>
        <div className="foresight-score__label">
          Primary: {RISK_LABEL[foresight.primary_risk] ?? foresight.primary_risk}
        </div>
      </div>

      {/* Per-category risk bars */}
      <div className="foresight-bars">
        <RiskBar label="HAB"      value={scores.hab      ?? 0} color={habColor} />
        <RiskBar label="Anoxia"   value={scores.anoxia   ?? 0} color={anoxColor} />
        <RiskBar label="Turnover" value={scores.turnover ?? 0} color={turnColor} />
      </div>

      {/* Recommendation */}
      <div className="foresight-rec" style={{ borderLeft: `3px solid ${lvl.color}` }}>
        <div className="foresight-rec__title" style={{ color: lvl.color }}>Recommendation</div>
        <div className="foresight-rec__body">{foresight.recommendation}</div>
      </div>

      {/* Contributing factors */}
      {foresight.contributing_factors?.length > 0 && (
        <div className="foresight-factors">
          {foresight.contributing_factors.map((f, i) => (
            <div key={i} className="foresight-factor">
              <span className="foresight-factor__dot" style={{ background: lvl.color }} />
              <span className="foresight-factor__text">{f}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
