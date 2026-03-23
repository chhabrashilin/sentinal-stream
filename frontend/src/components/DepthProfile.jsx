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

const DEPTH_COLORS = ['#ef5350', '#ff9800', '#42a5f5', '#26c6da']

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload || !payload.length) return null
  const d = payload[0].payload
  return (
    <div style={{
      background: '#0a1e3d',
      border: '1px solid var(--border)',
      borderRadius: '6px',
      padding: '10px 14px',
      fontSize: '12px',
    }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: '4px' }}>Depth: <strong style={{ color: 'var(--text-primary)' }}>{d.depth}</strong></div>
      <div style={{ color: payload[0].fill }}>Temp: <strong>{typeof d.temp === 'number' ? d.temp.toFixed(2) : d.temp} °C</strong></div>
    </div>
  )
}

export default function DepthProfile({ reading, loading }) {
  if (loading) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>
          Water Temperature Profile
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
          Loading depth profile...
        </div>
      </div>
    )
  }

  const profile = reading?.water_temp_profile
  const noData = !profile

  const chartData = noData
    ? [
        { depth: '0 m (Surface)', temp: null },
        { depth: '5 m', temp: null },
        { depth: '10 m', temp: null },
        { depth: '20 m (Deep)', temp: null },
      ]
    : [
        { depth: '0 m (Surface)', temp: profile['0m'] },
        { depth: '5 m', temp: profile['5m'] },
        { depth: '10 m', temp: profile['10m'] },
        { depth: '20 m (Deep)', temp: profile['20m'] },
      ]

  const temps = chartData.map(d => d.temp).filter(t => t != null)
  const minTemp = temps.length ? Math.floor(Math.min(...temps)) - 1 : 0
  const maxTemp = temps.length ? Math.ceil(Math.max(...temps)) + 1 : 30

  return (
    <div style={cardStyle}>
      <div>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', letterSpacing: '0.02em' }}>
          Water Temperature Profile
        </div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
          Vertical thermistor chain · 4 depths
        </div>
      </div>

      {noData ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', flexDirection: 'column', gap: '8px' }}>
          <div style={{ fontSize: '24px', opacity: 0.3 }}>~</div>
          <div>No depth data available</div>
          <div style={{ fontSize: '11px' }}>Start the sensor emulator to stream data</div>
        </div>
      ) : (
        <>
          <div style={{ flex: 1, minHeight: 0 }}>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart
                layout="vertical"
                data={chartData}
                margin={{ top: 4, right: 20, left: 10, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#1a3050" horizontal={false} />
                <XAxis
                  type="number"
                  domain={[minTemp, maxTemp]}
                  tick={{ fill: '#4a7a99', fontSize: 10 }}
                  tickLine={false}
                  axisLine={{ stroke: '#1e3a6e' }}
                  unit="°C"
                />
                <YAxis
                  type="category"
                  dataKey="depth"
                  tick={{ fill: '#7ab3d4', fontSize: 11 }}
                  tickLine={false}
                  axisLine={false}
                  width={90}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(33,150,243,0.07)' }} />
                <Bar dataKey="temp" radius={[0, 4, 4, 0]} maxBarSize={28}>
                  {chartData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={DEPTH_COLORS[index]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px', marginTop: '4px' }}>
            {chartData.map((d, i) => (
              <div key={d.depth} style={{
                background: 'rgba(255,255,255,0.03)',
                borderRadius: '6px',
                padding: '8px 6px',
                textAlign: 'center',
                border: `1px solid ${DEPTH_COLORS[i]}30`,
              }}>
                <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '2px' }}>
                  {d.depth.split(' ')[0]} {d.depth.split(' ')[1]}
                </div>
                <div style={{ fontSize: '15px', fontWeight: 700, color: DEPTH_COLORS[i] }}>
                  {d.temp != null ? d.temp.toFixed(1) : '—'}
                </div>
                <div style={{ fontSize: '9px', color: 'var(--text-muted)' }}>°C</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
