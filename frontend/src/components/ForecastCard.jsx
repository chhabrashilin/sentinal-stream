import React from 'react'

const cardStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '20px',
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  gap: '16px',
}

function R2Bar({ value }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  const color = value >= 0.7 ? '#4caf50' : value >= 0.4 ? '#ffc107' : '#ef5350'
  const label = value >= 0.7 ? 'Good fit' : value >= 0.4 ? 'Moderate fit' : 'Poor fit'
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '6px' }}>
        <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>R² Model Confidence</span>
        <span style={{ fontSize: '12px', fontWeight: 700, color }}>
          {value.toFixed(3)} — {label}
        </span>
      </div>
      <div style={{ height: '8px', background: '#1a3050', borderRadius: '4px', overflow: 'hidden' }}>
        <div style={{
          height: '100%',
          width: `${pct}%`,
          background: color,
          borderRadius: '4px',
          transition: 'width 0.6s ease, background 0.3s ease',
          boxShadow: `0 0 8px ${color}60`,
        }} />
      </div>
    </div>
  )
}

export default function ForecastCard({ forecast, loading }) {
  if (loading) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>5-Min Surface Temperature Forecast</div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
          Computing forecast...
        </div>
      </div>
    )
  }

  if (!forecast || forecast.error) {
    const isInsufficient = forecast?.status === 422
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>5-Min Surface Temperature Forecast</div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '10px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '32px', opacity: 0.25 }}>~</div>
          <div style={{ fontWeight: 500 }}>{isInsufficient ? 'Insufficient Data' : 'Forecast Unavailable'}</div>
          <div style={{ fontSize: '11px', textAlign: 'center', maxWidth: '220px', lineHeight: '1.6' }}>
            {isInsufficient
              ? 'Minimum 10 clean readings required. Continue streaming sensor data.'
              : 'Could not retrieve forecast from backend.'}
          </div>
        </div>
      </div>
    )
  }

  const trendConfig = {
    rising:  { icon: '↑', label: 'Rising',  color: '#ef5350', bg: 'rgba(239,83,80,0.12)' },
    falling: { icon: '↓', label: 'Falling', color: '#42a5f5', bg: 'rgba(66,165,245,0.12)' },
    stable:  { icon: '→', label: 'Stable',  color: '#78909c', bg: 'rgba(120,144,156,0.12)' },
  }
  const trend = trendConfig[forecast.trend] || trendConfig.stable

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', letterSpacing: '0.02em' }}>
            5-Min Surface Temperature Forecast
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            Linear regression · {forecast.records_used} records used
          </div>
        </div>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '5px',
          padding: '4px 10px',
          borderRadius: '20px',
          background: trend.bg,
          border: `1px solid ${trend.color}40`,
          fontSize: '12px',
          fontWeight: 700,
          color: trend.color,
        }}>
          {trend.icon} {trend.label}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', justifyContent: 'center', padding: '8px 0' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Current
          </div>
          <div style={{ fontSize: '42px', fontWeight: 800, color: 'var(--accent-teal)', letterSpacing: '-1px', lineHeight: 1 }}>
            {forecast.current_surface_temp_c.toFixed(1)}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>°C surface</div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
          <div style={{ fontSize: '28px', color: trend.color, lineHeight: 1 }}>{trend.icon}</div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>5 min</div>
        </div>

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Forecast
          </div>
          <div style={{ fontSize: '42px', fontWeight: 800, color: '#7ab3d4', letterSpacing: '-1px', lineHeight: 1 }}>
            {forecast.forecast_5min_surface_temp_c.toFixed(1)}
          </div>
          <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '2px' }}>°C predicted</div>
        </div>
      </div>

      <R2Bar value={forecast.r_squared} />
    </div>
  )
}
