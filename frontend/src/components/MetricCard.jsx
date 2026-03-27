import React from 'react'

export default function MetricCard({ label, value, unit, color, sublabel, context, loading }) {
  return (
    <div className="metric-card">
      <div className="metric-card__accent" style={{ background: color || 'var(--accent-blue)' }} />
      <div className="metric-card__label">{label}</div>

      {loading ? (
        <div className="skeleton" />
      ) : (
        <div className="metric-card__value-row">
          <span className="metric-card__value" style={{ color: color || 'var(--text-primary)' }}>
            {value ?? 'N/A'}
          </span>
          {unit && <span className="metric-card__unit">{unit}</span>}
        </div>
      )}

      {sublabel && <div className="metric-card__sublabel">{sublabel}</div>}
      {context && <div className="metric-card__context">{context}</div>}
    </div>
  )
}
