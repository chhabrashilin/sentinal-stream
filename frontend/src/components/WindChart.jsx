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

const cardStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '20px',
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  gap: '14px',
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload || !payload.length) return null
  return (
    <div style={{
      background: '#0a1e3d',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      padding: '10px 14px',
      fontSize: '12px',
    }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: '6px' }}>Reading #{label}</div>
      {payload.map((entry) => (
        <div key={entry.name} style={{ color: entry.color, marginBottom: '2px' }}>
          {entry.name}: <strong>{typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value} m/s</strong>
        </div>
      ))}
    </div>
  )
}

export default function WindChart({ readings, loading }) {
  if (loading) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          Wind Speed — Raw vs 10-Point Smoothed
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
          Loading wind data...
        </div>
      </div>
    )
  }

  if (!readings || readings.length === 0) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          Wind Speed — Raw vs 10-Point Smoothed
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '24px', opacity: 0.3 }}>~</div>
          <div>No wind data available</div>
          <div style={{ fontSize: '11px' }}>Start the sensor emulator to stream data</div>
        </div>
      </div>
    )
  }

  // Reverse so oldest is on the left
  const chartData = [...readings].reverse().map((r, i) => ({
    index: i + 1,
    raw: typeof r.raw_wind_speed_ms === 'number' ? parseFloat(r.raw_wind_speed_ms.toFixed(3)) : null,
    smoothed: typeof r.wind_speed_ms_smoothed === 'number' ? parseFloat(r.wind_speed_ms_smoothed.toFixed(3)) : null,
  }))

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', letterSpacing: '0.02em' }}>
            Wind Speed — Raw vs 10-Point Smoothed
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            Last {readings.length} readings · Lake Mendota
          </div>
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', textAlign: 'right' }}>
          <span style={{ color: 'var(--chart-wind-raw)' }}>— </span>Raw &nbsp;
          <span style={{ color: 'var(--chart-wind-smooth)' }}>— </span>Smooth
        </div>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={chartData} margin={{ top: 4, right: 12, left: -10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1a3050" vertical={false} />
            <XAxis
              dataKey="index"
              tick={{ fill: '#4a7a99', fontSize: 10 }}
              tickLine={false}
              axisLine={{ stroke: '#1e3a6e' }}
              label={{ value: 'Reading #', position: 'insideBottomRight', offset: -4, fill: '#4a7a99', fontSize: 10 }}
            />
            <YAxis
              tick={{ fill: '#4a7a99', fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              unit=" m/s"
              width={54}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: '11px', color: 'var(--text-muted)', paddingTop: '8px' }}
            />
            <Line
              type="monotone"
              dataKey="raw"
              name="Raw"
              stroke="#ff9800"
              strokeWidth={1.5}
              strokeDasharray="4 3"
              dot={false}
              activeDot={{ r: 4, fill: '#ff9800' }}
            />
            <Line
              type="monotone"
              dataKey="smoothed"
              name="Smoothed"
              stroke="#2196f3"
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 4, fill: '#2196f3' }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
