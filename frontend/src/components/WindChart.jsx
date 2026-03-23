import React from 'react'
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'

function WindTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">Reading #{label}</div>
      {payload.map((entry) => (
        <div key={entry.name} className="chart-tooltip__row" style={{ color: entry.color }}>
          {entry.name}:{' '}
          <strong>{typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value} m/s</strong>
        </div>
      ))}
    </div>
  )
}

export default function WindChart({ readings, loading }) {
  const isEmpty = !readings || readings.length === 0

  return (
    <div className="chart-card">
      <div className="card-header">
        <div>
          <div className="card-title">Wind Speed: Raw vs 10-Point Smoothed</div>
          {!isEmpty && (
            <div className="card-subtitle">Last {readings.length} readings · Lake Mendota</div>
          )}
        </div>
        {!isEmpty && (
          <div className="card-subtitle">
            <span style={{ color: 'var(--chart-wind-raw)' }}>—</span> Raw &nbsp;
            <span style={{ color: 'var(--chart-wind-smooth)' }}>—</span> Smooth
          </div>
        )}
      </div>

      {loading ? (
        <div className="state-center">Loading wind data...</div>
      ) : isEmpty ? (
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">No wind data available</div>
          <div className="state-hint">Start the sensor emulator to stream data</div>
        </div>
      ) : (
        <div className="chart-area">
          <ResponsiveContainer width="100%" height={220}>
            <LineChart
              data={[...readings].reverse().map((r, i) => ({
                index: i + 1,
                raw: typeof r.raw_wind_speed_ms === 'number'
                  ? parseFloat(r.raw_wind_speed_ms.toFixed(3)) : null,
                smoothed: typeof r.wind_speed_ms_smoothed === 'number'
                  ? parseFloat(r.wind_speed_ms_smoothed.toFixed(3)) : null,
              }))}
              margin={{ top: 4, right: 12, left: -10, bottom: 0 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#0e1848" vertical={false} />
              <XAxis
                dataKey="index"
                tick={{ fill: '#4a6aaa', fontSize: 10 }}
                tickLine={false}
                axisLine={{ stroke: '#1c2e72' }}
                label={{ value: 'Reading #', position: 'insideBottomRight', offset: -4, fill: '#4a6aaa', fontSize: 10 }}
              />
              <YAxis
                tick={{ fill: '#4a6aaa', fontSize: 10 }}
                tickLine={false}
                axisLine={false}
                unit=" m/s"
                width={54}
              />
              <Tooltip content={<WindTooltip />} />
              <Legend wrapperStyle={{ fontSize: '11px', color: 'var(--text-muted)', paddingTop: '8px' }} />
              <Line
                type="monotone"
                dataKey="raw"
                name="Raw"
                stroke="var(--chart-wind-raw)"
                strokeWidth={1.5}
                strokeDasharray="4 3"
                dot={false}
                activeDot={{ r: 4 }}
              />
              <Line
                type="monotone"
                dataKey="smoothed"
                name="Smoothed"
                stroke="var(--chart-wind-smooth)"
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  )
}
