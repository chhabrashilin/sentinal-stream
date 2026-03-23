import React from 'react'

function formatTime(ts) {
  if (!ts) return '—'
  try {
    return new Date(ts).toLocaleTimeString('en-US', {
      hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
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
      <div className="live-feed">
        <div className="live-feed__title">Live Data Feed</div>
        <div className="state-center" style={{ padding: '20px 0' }}>Loading readings...</div>
      </div>
    )
  }

  const rows = readings?.slice(0, 8) ?? []

  return (
    <div className="live-feed">
      <div className="live-feed__header">
        <div>
          <div className="live-feed__title">Live Data Feed</div>
          <div className="live-feed__subtitle">Most recent 8 readings · newest first</div>
        </div>
        {rows.length > 0 && (
          <div className="streaming-badge">
            <span className="streaming-dot" />
            STREAMING
          </div>
        )}
      </div>

      {rows.length === 0 ? (
        <div className="state-center" style={{ padding: '30px 0' }}>
          <div className="state-icon">~</div>
          <div>No readings in database yet</div>
          <div className="state-hint">
            Run the sensor emulator: <code>python emulator.py</code>
          </div>
        </div>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Time (UTC)</th>
                <th>Air Temp</th>
                <th>Wind Raw</th>
                <th>Wind Smooth</th>
                <th>Surface 0m</th>
                <th>Chlorophyll</th>
                <th className="center">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.id ?? i}>
                  <td className="td-mono">{formatTime(r.timestamp)}</td>
                  <td className="td-air-temp">{fmt(r.air_temp_c)} °C</td>
                  <td className="td-wind-raw">{fmt(r.raw_wind_speed_ms)} m/s</td>
                  <td className="td-wind-smooth">{fmt(r.wind_speed_ms_smoothed)} m/s</td>
                  <td className="td-surface">
                    {fmt(r.water_temp_profile?.['0m'] ?? r.water_temp_0m)} °C
                  </td>
                  <td className="td-chlorophyll">{fmt(r.chlorophyll_ugl, 1)} µg/L</td>
                  <td className="center">
                    {r.is_outlier ? (
                      <span className="badge badge--sm badge--square badge--outlier">⚠ OUTLIER</span>
                    ) : (
                      <span className="badge badge--sm badge--square badge--clean">✓ CLEAN</span>
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
