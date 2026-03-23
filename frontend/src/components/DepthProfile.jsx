import React from 'react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
} from 'recharts'

// Hex values used for both the chart cells and depth-grid borders
const DEPTH_COLORS = ['#ff6b6b', '#f59e0b', '#4a8fff', '#00ceb4']

const DEPTHS = [
  { key: '0m',  label: '0 m (Surface)' },
  { key: '5m',  label: '5 m' },
  { key: '10m', label: '10 m' },
  { key: '20m', label: '20 m (Deep)' },
]

function DepthTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const d = payload[0].payload
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">
        Depth: <strong style={{ color: 'var(--text-primary)' }}>{d.label}</strong>
      </div>
      <div className="chart-tooltip__row" style={{ color: payload[0].fill }}>
        Temp: <strong>{typeof d.temp === 'number' ? d.temp.toFixed(2) : d.temp} °C</strong>
      </div>
    </div>
  )
}

export default function DepthProfile({ reading, loading }) {
  const profile = reading?.water_temp_profile

  const chartData = DEPTHS.map(({ key, label }) => ({
    label,
    depth: key,
    temp: profile?.[key] ?? null,
  }))

  const temps = chartData.map(d => d.temp).filter(t => t != null)
  const minTemp = temps.length ? Math.floor(Math.min(...temps)) - 1 : 0
  const maxTemp = temps.length ? Math.ceil(Math.max(...temps)) + 1 : 30

  return (
    <div className="chart-card">
      <div>
        <div className="card-title">Water Temperature Profile</div>
        <div className="card-subtitle">Vertical thermistor chain · 4 depths</div>
      </div>

      {loading ? (
        <div className="state-center">Loading depth profile...</div>
      ) : !profile ? (
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">No depth data available</div>
          <div className="state-hint">Start the sensor emulator to stream data</div>
        </div>
      ) : (
        <>
          <div className="chart-area">
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                layout="vertical"
                data={chartData}
                margin={{ top: 4, right: 20, left: 10, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#0e1848" horizontal={false} />
                <XAxis
                  type="number"
                  domain={[minTemp, maxTemp]}
                  tick={{ fill: '#4a6aaa', fontSize: 10 }}
                  tickLine={false}
                  axisLine={{ stroke: '#1c2e72' }}
                  unit="°C"
                />
                <YAxis
                  type="category"
                  dataKey="label"
                  tick={{ fill: '#8aabee', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={90}
                />
                <Tooltip content={<DepthTooltip />} cursor={{ fill: 'rgba(33,150,243,0.07)' }} />
                <Bar dataKey="temp" radius={[0, 4, 4, 0]} maxBarSize={28}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={DEPTH_COLORS[i]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="depth-grid">
            {chartData.map((d, i) => (
              <div
                key={d.depth}
                className="depth-cell"
                style={{ border: `1px solid ${DEPTH_COLORS[i]}30` }}
              >
                <div className="depth-cell__label">{d.depth}</div>
                <div className="depth-cell__value" style={{ color: DEPTH_COLORS[i] }}>
                  {d.temp != null ? d.temp.toFixed(1) : '—'}
                </div>
                <div className="depth-cell__unit">°C</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
