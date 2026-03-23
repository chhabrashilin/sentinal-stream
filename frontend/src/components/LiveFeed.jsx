import React from 'react'

const containerStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '20px',
  display: 'flex',
  flexDirection: 'column',
  gap: '14px',
}

const thStyle = {
  padding: '8px 12px',
  textAlign: 'left',
  fontSize: '10px',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--text-muted)',
  borderBottom: '1px solid var(--border)',
  whiteSpace: 'nowrap',
}

const tdStyle = (extra = {}) => ({
  padding: '10px 12px',
  fontSize: '12px',
  color: 'var(--text-primary)',
  verticalAlign: 'middle',
  ...extra,
})

function formatTime(ts) {
  if (!ts) return '—'
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return ts
  }
}

function fmt(val, decimals = 2) {
  if (val == null) return '—'
  if (typeof val !== 'number') return val
  return val.toFixed(decimals)
}

export default function LiveFeed({ readings, loading }) {
  if (loading) {
    return (
      <div style={containerStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>Live Data Feed</div>
        <div style={{ color: 'var(--text-muted)', padding: '20px 0', textAlign: 'center' }}>Loading readings...</div>
      </div>
    )
  }

  const rows = readings ? readings.slice(0, 8) : []

  return (
    <div style={containerStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', letterSpacing: '0.02em' }}>
            Live Data Feed
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            Most recent 8 readings · newest first
          </div>
        </div>
        {rows.length > 0 && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '11px',
            color: 'var(--accent-green)',
            background: 'rgba(76,175,80,0.1)',
            border: '1px solid rgba(76,175,80,0.25)',
            borderRadius: '4px',
            padding: '3px 8px',
          }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'var(--accent-green)', display: 'inline-block', animation: 'pulse 2s infinite' }} />
            STREAMING
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <div style={{ color: 'var(--text-muted)', padding: '30px 0', textAlign: 'center', flexDirection: 'column', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ fontSize: '24px', opacity: 0.25 }}>~</div>
          <div>No readings in database yet</div>
          <div style={{ fontSize: '11px' }}>Run the sensor emulator: <code style={{ color: 'var(--accent-blue)', background: 'rgba(33,150,243,0.1)', padding: '1px 5px', borderRadius: '3px' }}>python emulator.py</code></div>
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '640px' }}>
            <thead>
              <tr>
                <th style={thStyle}>Time (UTC)</th>
                <th style={thStyle}>Air Temp</th>
                <th style={thStyle}>Wind Raw</th>
                <th style={thStyle}>Wind Smooth</th>
                <th style={thStyle}>Surface 0m</th>
                <th style={thStyle}>Chlorophyll</th>
                <th style={{ ...thStyle, textAlign: 'center' }}>Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr
                  key={r.id ?? i}
                  style={{
                    background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)',
                    borderBottom: '1px solid rgba(30,58,110,0.4)',
                    transition: 'background 0.15s',
                  }}
                >
                  <td style={tdStyle({ color: 'var(--text-muted)', fontFamily: 'monospace', fontSize: '11px' })}>
                    {formatTime(r.timestamp)}
                  </td>
                  <td style={tdStyle({ color: '#ff9800' })}>
                    {fmt(r.air_temp_c)} °C
                  </td>
                  <td style={tdStyle({ color: 'var(--chart-wind-raw)' })}>
                    {fmt(r.raw_wind_speed_ms)} m/s
                  </td>
                  <td style={tdStyle({ color: 'var(--chart-wind-smooth)', fontWeight: 600 })}>
                    {fmt(r.wind_speed_ms_smoothed)} m/s
                  </td>
                  <td style={tdStyle({ color: '#ef5350', fontWeight: 600 })}>
                    {fmt(r.water_temp_profile?.['0m'] ?? r.water_temp_0m)} °C
                  </td>
                  <td style={tdStyle({ color: 'var(--accent-teal)' })}>
                    {fmt(r.chlorophyll_ugl, 1)} µg/L
                  </td>
                  <td style={{ ...tdStyle(), textAlign: 'center' }}>
                    {r.is_outlier ? (
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: 'rgba(200,16,46,0.15)',
                        border: '1px solid rgba(200,16,46,0.4)',
                        color: '#ef5350',
                        fontSize: '10px',
                        fontWeight: 700,
                        letterSpacing: '0.04em',
                      }}>
                        ⚠ OUTLIER
                      </span>
                    ) : (
                      <span style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        padding: '2px 8px',
                        borderRadius: '4px',
                        background: 'rgba(76,175,80,0.1)',
                        border: '1px solid rgba(76,175,80,0.25)',
                        color: '#4caf50',
                        fontSize: '10px',
                        fontWeight: 700,
                      }}>
                        ✓ CLEAN
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
