import React from 'react'

const STATUS = {
  stratified: {
    label: 'STRATIFIED',
    cls: 'badge--stratified',
    color: '#ff6b6b',
    note: 'HAB risk elevated; thermally isolated epilimnion',
  },
  weakly_stratified: {
    label: 'WEAKLY STRATIFIED',
    cls: 'badge--weakly_stratified',
    color: '#f59e0b',
    note: 'Partial mixing; some vertical exchange occurring',
  },
  mixed: {
    label: 'MIXED',
    cls: 'badge--mixed',
    color: '#00ceb4',
    note: 'Full water column turnover; lower HAB risk',
  },
}

export default function StratificationCard({ stratification, loading }) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">Thermal Stratification</div>
        <div className="state-center">Computing stratification...</div>
      </div>
    )
  }

  if (!stratification || stratification.error) {
    const noData = stratification?.status === 422
    return (
      <div className="card">
        <div className="card-title">Thermal Stratification</div>
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">{noData ? 'No Data Yet' : 'Unavailable'}</div>
          <div className="state-hint">
            {noData
              ? 'Stream sensor data to compute stratification.'
              : 'Could not retrieve stratification from backend.'}
          </div>
        </div>
      </div>
    )
  }

  const cfg      = STATUS[stratification.stratification_status] ?? STATUS.mixed
  const strength = stratification.thermocline_strength_c

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">Thermal Stratification</div>
          <div className="card-subtitle">NTL-LTER depth profile analysis</div>
        </div>
        <div className={`badge badge--sm badge--square ${cfg.cls}`}>{cfg.label}</div>
      </div>

      <div className="strat-temps">
        <div className="strat-temp-block">
          <div className="strat-temp-label">Surface (0m)</div>
          <div className="strat-temp-value" style={{ color: '#ff6b6b' }}>
            {stratification.surface_temp_c.toFixed(1)}
          </div>
          <div className="strat-temp-unit">°C</div>
        </div>

        <div className="strat-delta">
          <div
            className="strat-delta__value"
            style={{ color: cfg.color, textShadow: `0 0 20px ${cfg.color}60` }}
          >
            {strength >= 0 ? '+' : ''}{strength.toFixed(1)}
          </div>
          <div className="strat-delta__unit" style={{ color: cfg.color }}>°C Δt</div>
          <div className="strat-delta__caption">thermocline strength</div>
        </div>

        <div className="strat-temp-block">
          <div className="strat-temp-label">Deep (20m)</div>
          <div className="strat-temp-value" style={{ color: '#00ceb4' }}>
            {stratification.deep_temp_c.toFixed(1)}
          </div>
          <div className="strat-temp-unit">°C</div>
        </div>
      </div>

      <div className="strat-note" style={{ borderLeft: `3px solid ${cfg.color}` }}>
        <div className="strat-note__title" style={{ color: cfg.color }}>{cfg.note}</div>
        <div className="strat-note__body">
          Δt = 0m temp − 20m temp. &gt; 10°C = strongly stratified (HAB risk elevated).
          &lt; 4°C = well-mixed column.
        </div>
      </div>
    </div>
  )
}
