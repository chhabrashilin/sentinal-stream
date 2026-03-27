import React from 'react'

const TREND = {
  rising:  { icon: 'up', label: 'Rising',  cls: 'badge--rising',  color: '#ff6b6b' },
  falling: { icon: 'dn', label: 'Falling', cls: 'badge--falling', color: '#4a8fff' },
  stable:  { icon: '->', label: 'Stable',  cls: 'badge--stable',  color: '#64748b' },
}

const TREND_CONTEXT = {
  rising: {
    what: 'Surface water is warming over the last ~100 readings.',
    ecology: 'Rising surface temp in spring/summer accelerates stratification onset and increases HAB risk window. A rapid rise (+0.5°C or more in 5 minutes under current conditions) may indicate solar heating amplified by reduced cloud cover or reduced wind mixing.',
    action: 'Monitor foresight HAB score. If stratification status is "weakly stratified" and HAB score is above 30, prepare advisory communications.',
  },
  falling: {
    what: 'Surface water is cooling over the last ~100 readings.',
    ecology: 'Falling surface temperature in summer can be a precursor to fall overturn. A rapid fall while the column is stratified means the surface and deep layers are approaching the same density. If this persists with elevated wind (above 8 m/s), full turnover is possible within 24-48 hours. In spring, this is normal post ice-out behaviour.',
    action: 'Check foresight turnover score. If above 0.5 and stratification is "weakly stratified", issue a waterway advisory.',
  },
  stable: {
    what: 'Surface temperature is holding steady within +/-0.1°C over the forecast window.',
    ecology: 'Thermal stability indicates a balance between solar input and mixing or evaporative cooling. This is the most common state during calm summer afternoons. Stable temperature does not mean low risk: a stagnant, stable surface layer is optimal for cyanobacterial bloom development.',
    action: 'Check wind speed and chlorophyll-a. Calm + stable + high chl-a = elevated HAB risk despite stable temperature trend.',
  },
}

const R2_LABELS = [
  { min: 0.7, label: 'Good fit',     color: '#00ceb4' },
  { min: 0.4, label: 'Moderate fit', color: '#f59e0b' },
  { min: 0.0, label: 'Poor fit',     color: '#ff6b6b' },
]

function R2Bar({ value }) {
  const pct   = Math.max(0, Math.min(1, value)) * 100
  const band  = R2_LABELS.find(b => value >= b.min) ?? R2_LABELS[R2_LABELS.length - 1]

  return (
    <div className="r2-bar">
      <div className="r2-bar__header">
        <span className="r2-bar__title">R² Model Confidence</span>
        <span className="r2-bar__value" style={{ color: band.color }}>
          {value.toFixed(3)}, {band.label}
        </span>
      </div>
      <div className="r2-bar__track">
        <div
          className="r2-bar__fill"
          style={{ width: `${pct}%`, background: band.color, boxShadow: `0 0 8px ${band.color}60` }}
        />
      </div>
      <div className="r2-bar__context">
        R² close to 1.0 = strong linear temperature trend (reliable forecast). R² near 0 = irregular
        temperature fluctuations; forecast is less reliable. Low R² during calm conditions often
        indicates the sensor is detecting sub-minute thermal micro-turbulence.
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
  const ctx   = TREND_CONTEXT[forecast.trend] ?? TREND_CONTEXT.stable
  const delta = forecast.forecast_5min_surface_temp_c - forecast.current_surface_temp_c

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">5-Min Surface Temperature Forecast</div>
          <div className="card-subtitle">Linear regression · {forecast.records_used} records used</div>
        </div>
        <div className={`badge ${trend.cls}`}>
          {trend.label}
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
          <div className="forecast-arrow__icon" style={{ color: trend.color }}>
            {delta > 0 ? '+' : ''}{delta.toFixed(2)}°C
          </div>
          <div className="forecast-arrow__label">in 5 min</div>
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

      {/* Trend context */}
      <div className="inference-block" style={{ marginTop: 12 }}>
        <div className="inference-block__heading" style={{ color: trend.color }}>
          Trend: {trend.label}. {ctx.what}
        </div>
        <div className="inference-block__body">{ctx.ecology}</div>
        <div className="inference-action-note">
          <span className="inference-action-note__label">Action: </span>
          {ctx.action}
        </div>
      </div>
    </div>
  )
}
