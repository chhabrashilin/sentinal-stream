import React from 'react'

const TREND = {
  rising:  { icon: '↑', label: 'Rising',  cls: 'badge--rising',  color: '#ff6b6b' },
  falling: { icon: '↓', label: 'Falling', cls: 'badge--falling', color: '#4a8fff' },
  stable:  { icon: '→', label: 'Stable',  cls: 'badge--stable',  color: '#64748b' },
}

function R2Bar({ value }) {
  const pct   = Math.max(0, Math.min(1, value)) * 100
  const color = value >= 0.7 ? '#00ceb4' : value >= 0.4 ? '#f59e0b' : '#ff6b6b'
  const label = value >= 0.7 ? 'Good fit' : value >= 0.4 ? 'Moderate fit' : 'Poor fit'

  return (
    <div className="r2-bar">
      <div className="r2-bar__header">
        <span className="r2-bar__title">R² Model Confidence</span>
        <span className="r2-bar__value" style={{ color }}>
          {value.toFixed(3)}, {label}
        </span>
      </div>
      <div className="r2-bar__track">
        <div
          className="r2-bar__fill"
          style={{ width: `${pct}%`, background: color, boxShadow: `0 0 8px ${color}60` }}
        />
      </div>
    </div>
  )
}

export default function ForecastCard({ forecast, loading }) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">5-Min Surface Temperature Forecast</div>
        <div className="state-center">Computing forecast...</div>
      </div>
    )
  }

  if (!forecast || forecast.error) {
    const isInsufficient = forecast?.status === 422
    return (
      <div className="card">
        <div className="card-title">5-Min Surface Temperature Forecast</div>
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">{isInsufficient ? 'Insufficient Data' : 'Forecast Unavailable'}</div>
          <div className="state-hint">
            {isInsufficient
              ? 'Minimum 10 clean readings required. Continue streaming sensor data.'
              : 'Could not retrieve forecast from backend.'}
          </div>
        </div>
      </div>
    )
  }

  const trend = TREND[forecast.trend] ?? TREND.stable

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">5-Min Surface Temperature Forecast</div>
          <div className="card-subtitle">Linear regression · {forecast.records_used} records used</div>
        </div>
        <div className={`badge ${trend.cls}`}>
          {trend.icon} {trend.label}
        </div>
      </div>

      <div className="forecast-temps">
        <div className="forecast-temp-block">
          <div className="forecast-temp-label">Current</div>
          <div className="forecast-temp-value" style={{ color: 'var(--accent-teal)' }}>
            {forecast.current_surface_temp_c.toFixed(1)}
          </div>
          <div className="forecast-temp-unit">°C surface</div>
        </div>

        <div className="forecast-arrow">
          <div className="forecast-arrow__icon" style={{ color: trend.color }}>{trend.icon}</div>
          <div className="forecast-arrow__label">5 min</div>
        </div>

        <div className="forecast-temp-block">
          <div className="forecast-temp-label">Forecast</div>
          <div className="forecast-temp-value" style={{ color: '#8aabee' }}>
            {forecast.forecast_5min_surface_temp_c.toFixed(1)}
          </div>
          <div className="forecast-temp-unit">°C predicted</div>
        </div>
      </div>

      <R2Bar value={forecast.r_squared} />
    </div>
  )
}
