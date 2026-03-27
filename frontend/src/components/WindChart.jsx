import React from 'react'
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts'

const BEAUFORT = [
  { max: 0.3,  bf: 0, label: 'Calm',           note: 'Mirror flat. Algae scum may form.' },
  { max: 1.6,  bf: 1, label: 'Light air',       note: 'Slight ripples. Ideal conditions.' },
  { max: 3.4,  bf: 2, label: 'Light breeze',    note: 'Small wavelets. Best for swimming.' },
  { max: 5.5,  bf: 3, label: 'Gentle breeze',   note: 'Whitecaps forming. SUP caution.' },
  { max: 8.0,  bf: 4, label: 'Moderate breeze', note: 'Regular whitecaps. Paddling limit.' },
  { max: 10.8, bf: 5, label: 'Fresh breeze',    note: 'Many whitecaps. Rowing shells dock.' },
  { max: 13.9, bf: 6, label: 'Strong breeze',   note: 'Large waves. Dinghy capsize risk.' },
  { max: 17.2, bf: 7, label: 'Near gale',       note: 'Rough. Keelboats reef.' },
  { max: 999,  bf: 8, label: 'Gale+',           note: 'Dangerous. Clear the lake.' },
]

function getBf(wind) {
  return BEAUFORT.find(b => wind < b.max) ?? BEAUFORT[BEAUFORT.length - 1]
}

function WindTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const rawVal = payload.find(p => p.dataKey === 'raw')?.value
  const bf = rawVal != null ? getBf(rawVal) : null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip__label">Reading #{label}</div>
      {payload.map((entry) => (
        <div key={entry.name} className="chart-tooltip__row" style={{ color: entry.color }}>
          {entry.name}:{' '}
          <strong>{typeof entry.value === 'number' ? entry.value.toFixed(2) : entry.value} m/s</strong>
        </div>
      ))}
      {bf && (
        <div className="chart-tooltip__row" style={{ color: '#8aabee', fontSize: '0.72rem', marginTop: 4 }}>
          Bf{bf.bf}: {bf.label}. {bf.note}
        </div>
      )}
    </div>
  )
}

export default function WindChart({ readings, loading }) {
  const isEmpty = !readings || readings.length === 0

  const latestWind = readings?.[0]?.wind_speed_ms_smoothed ?? readings?.[0]?.raw_wind_speed_ms
  const currentBf = latestWind != null ? getBf(latestWind) : null

  const chartData = isEmpty ? [] : [...readings].reverse().map((r, i) => ({
    index: i + 1,
    raw: typeof r.raw_wind_speed_ms === 'number'
      ? parseFloat(r.raw_wind_speed_ms.toFixed(3)) : null,
    smoothed: typeof r.wind_speed_ms_smoothed === 'number'
      ? parseFloat(r.wind_speed_ms_smoothed.toFixed(3)) : null,
  }))

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
            <span style={{ color: 'var(--chart-wind-raw)' }}>---</span> Raw &nbsp;
            <span style={{ color: 'var(--chart-wind-smooth)' }}>---</span> Smooth
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
        <>
          <div className="chart-area">
            <ResponsiveContainer width="100%" height={240}>
              <AreaChart
                data={chartData}
                margin={{ top: 4, right: 12, left: -10, bottom: 0 }}
              >
                <defs>
                  <linearGradient id="gradRaw" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f59e0b" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#f59e0b" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradSmooth" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#4f8eff" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#4f8eff" stopOpacity={0} />
                  </linearGradient>
                </defs>
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
                <Area
                  type="monotone"
                  dataKey="raw"
                  name="Raw"
                  stroke="#f59e0b"
                  strokeWidth={1.5}
                  strokeDasharray="4 3"
                  fill="url(#gradRaw)"
                  dot={false}
                  activeDot={{ r: 4 }}
                />
                <Area
                  type="monotone"
                  dataKey="smoothed"
                  name="Smoothed"
                  stroke="#4f8eff"
                  strokeWidth={2.5}
                  fill="url(#gradSmooth)"
                  dot={false}
                  activeDot={{ r: 4 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {currentBf && (
            <div className="wind-inference">
              <div className="wind-inference__current">
                Current: <strong>Beaufort {currentBf.bf}: {currentBf.label}</strong>
                <span className="wind-inference__note">{currentBf.note}</span>
              </div>
              <div className="wind-inference__table">
                <div className="wind-inference__heading">Beaufort reference for Lake Mendota</div>
                {BEAUFORT.map(b => (
                  <div key={b.bf}
                    className={`beaufort-ref-row ${currentBf.bf === b.bf ? 'beaufort-ref-row--active' : ''}`}>
                    <span className="beaufort-ref-bf">Bf{b.bf}</span>
                    <span className="beaufort-ref-label">{b.label}</span>
                    <span className="beaufort-ref-range">
                      {b.bf === 0 ? '< 0.3' : b.bf === 8 ? '> 17.2' : `${BEAUFORT[b.bf - 1]?.max ?? 0} - ${b.max}`} m/s
                    </span>
                    <span className="beaufort-ref-note">{b.note}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
