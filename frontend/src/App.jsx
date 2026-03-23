import React, { useState, useEffect, useCallback } from 'react'
import MetricCard from './components/MetricCard.jsx'
import WindChart from './components/WindChart.jsx'
import DepthProfile from './components/DepthProfile.jsx'
import ForecastCard from './components/ForecastCard.jsx'
import StratificationCard from './components/StratificationCard.jsx'
import LiveFeed from './components/LiveFeed.jsx'

const POLL_INTERVAL_MS = 2000

async function fetchJSON(path) {
  try {
    const res = await fetch(path)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      return { error: true, status: res.status, detail: body.detail }
    }
    return await res.json()
  } catch (err) {
    return { error: true, status: 0, detail: err.message }
  }
}

// ──────────────────────────────────────────────────────
// Header
// ──────────────────────────────────────────────────────
function Header({ lastUpdated }) {
  const [tick, setTick] = useState(true)

  useEffect(() => {
    const t = setInterval(() => setTick(v => !v), 1000)
    return () => clearInterval(t)
  }, [])

  return (
    <header style={{
      background: 'linear-gradient(135deg, #0a1628 0%, #0d1f3c 50%, #091422 100%)',
      borderBottom: '1px solid var(--border)',
      padding: '16px 28px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      flexWrap: 'wrap',
      gap: '10px',
      position: 'sticky',
      top: 0,
      zIndex: 100,
      boxShadow: '0 2px 20px rgba(0,0,0,0.4)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <div style={{
          width: '40px',
          height: '40px',
          borderRadius: '10px',
          background: 'linear-gradient(135deg, #c8102e, #a00d25)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '20px',
          boxShadow: '0 0 16px rgba(200,16,46,0.4)',
          flexShrink: 0,
        }}>
          🛰️
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            <h1 style={{
              fontSize: '18px',
              fontWeight: 800,
              letterSpacing: '-0.3px',
              background: 'linear-gradient(90deg, #e8f4fd, #7ab3d4)',
              WebkitBackgroundClip: 'text',
              WebkitTextFillColor: 'transparent',
            }}>
              Sentinel-Stream
            </h1>
            <span style={{
              fontSize: '13px',
              color: 'var(--text-muted)',
              fontWeight: 400,
              borderLeft: '1px solid var(--border)',
              paddingLeft: '10px',
            }}>
              Lake Mendota Digital Twin
            </span>
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            UW-Madison · NTL-LTER Buoy · 43.0988° N, 89.4045° W
          </div>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
        {lastUpdated && (
          <div style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            Updated {lastUpdated}
          </div>
        )}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '7px',
          padding: '5px 12px',
          borderRadius: '20px',
          background: 'rgba(76,175,80,0.1)',
          border: '1px solid rgba(76,175,80,0.3)',
          fontSize: '11px',
          fontWeight: 700,
          color: '#4caf50',
          letterSpacing: '0.06em',
        }}>
          <span style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            background: '#4caf50',
            display: 'inline-block',
            opacity: tick ? 1 : 0.3,
            transition: 'opacity 0.3s',
            boxShadow: tick ? '0 0 6px #4caf50' : 'none',
          }} />
          LIVE
        </div>
      </div>
    </header>
  )
}

// ──────────────────────────────────────────────────────
// Buoy Status Banner
// ──────────────────────────────────────────────────────
function BuoyBanner({ buoyStatus }) {
  if (!buoyStatus) return null

  const isLive = buoyStatus.pipeline_mode === 'live'
  const modeColor = isLive ? '#4caf50' : '#ff9800'
  const modeBg   = isLive ? 'rgba(76,175,80,0.1)' : 'rgba(255,152,0,0.1)'
  const modeBorder = isLive ? 'rgba(76,175,80,0.3)' : 'rgba(255,152,0,0.3)'

  return (
    <div style={{
      background: 'rgba(255,255,255,0.02)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      padding: '12px 20px',
      display: 'flex',
      alignItems: 'center',
      gap: '14px',
      flexWrap: 'wrap',
      fontSize: '12px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <span style={{ fontSize: '16px' }}>🌊</span>
        <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>SSEC Buoy Status:</span>
        <span style={{ color: 'var(--text-primary)' }}>{buoyStatus.ssec_status_message}</span>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginLeft: 'auto', flexWrap: 'wrap' }}>
        <span style={{
          padding: '3px 10px',
          borderRadius: '4px',
          background: modeBg,
          border: `1px solid ${modeBorder}`,
          color: modeColor,
          fontWeight: 700,
          fontSize: '11px',
          letterSpacing: '0.06em',
        }}>
          {buoyStatus.pipeline_mode.toUpperCase()} MODE
        </span>

        {!buoyStatus.ssec_api_reachable && (
          <span style={{
            padding: '3px 10px',
            borderRadius: '4px',
            background: 'rgba(120,144,156,0.1)',
            border: '1px solid rgba(120,144,156,0.3)',
            color: '#78909c',
            fontWeight: 600,
            fontSize: '11px',
          }}>
            API UNREACHABLE
          </span>
        )}

        {buoyStatus.ssec_last_updated && buoyStatus.ssec_last_updated !== 'unknown' && (
          <span style={{ color: 'var(--text-muted)', fontSize: '11px' }}>
            Last updated: {buoyStatus.ssec_last_updated}
          </span>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────
// Main App
// ──────────────────────────────────────────────────────
export default function App() {
  const [status, setStatus]           = useState(null)
  const [readings, setReadings]       = useState(null)
  const [forecast, setForecast]       = useState(null)
  const [stratification, setStrat]   = useState(null)
  const [buoyStatus, setBuoyStatus]  = useState(null)
  const [loading, setLoading]        = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchAll = useCallback(async () => {
    const [statusData, readingsData, forecastData, stratData, buoyData] = await Promise.all([
      fetchJSON('/api/status'),
      fetchJSON('/api/readings?n=60'),
      fetchJSON('/api/forecast'),
      fetchJSON('/api/stratification'),
      fetchJSON('/api/buoy-status'),
    ])

    setStatus(statusData)
    setReadings(readingsData)
    setForecast(forecastData)
    setStrat(stratData)
    setBuoyStatus(buoyData)
    setLoading(false)
    setLastUpdated(new Date().toLocaleTimeString('en-US', { hour12: false }))
  }, [])

  useEffect(() => {
    fetchAll()
    const timer = setInterval(fetchAll, POLL_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [fetchAll])

  // ── Derived metrics from latest reading ──
  const latest = status?.latest_reading
  const latestFull = readings?.readings?.[0]

  const airTemp    = latest?.air_temp_c
  const windSmooth = latest?.smoothed_wind_ms
  const surfaceTemp = latest?.water_temp_0m ?? latestFull?.water_temp_profile?.['0m']
  const chlorophyll = latest?.chlorophyll_ugl ?? latestFull?.chlorophyll_ugl
  const recordCount = status?.record_count

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>
      <Header lastUpdated={lastUpdated} />

      <main style={{ padding: '24px 28px', display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '1600px', margin: '0 auto' }}>

        {/* ── Metric Cards Row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: '12px' }}>
          <MetricCard
            label="Air Temperature"
            value={airTemp != null ? airTemp.toFixed(1) : null}
            unit="°C"
            color="#ff9800"
            sublabel="Buoy mast height"
            loading={loading && airTemp == null}
          />
          <MetricCard
            label="Wind Speed"
            value={windSmooth != null ? windSmooth.toFixed(2) : null}
            unit="m/s"
            color="var(--accent-blue)"
            sublabel="10-pt smoothed"
            loading={loading && windSmooth == null}
          />
          <MetricCard
            label="Surface Water Temp"
            value={surfaceTemp != null ? surfaceTemp.toFixed(2) : null}
            unit="°C"
            color="var(--accent-teal)"
            sublabel="Depth 0 m (epilimnion)"
            loading={loading && surfaceTemp == null}
          />
          <MetricCard
            label="Chlorophyll-a"
            value={chlorophyll != null ? chlorophyll.toFixed(1) : null}
            unit="µg/L"
            color="#ce93d8"
            sublabel="HAB proxy indicator"
            loading={loading && chlorophyll == null}
          />
          <MetricCard
            label="Total Records"
            value={recordCount != null ? recordCount.toLocaleString() : null}
            unit=""
            color="var(--accent-red)"
            sublabel="In database"
            loading={loading && recordCount == null}
          />
        </div>

        {/* ── Buoy Banner ── */}
        <BuoyBanner buoyStatus={buoyStatus?.error ? null : buoyStatus} />

        {/* ── Charts Row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div style={{ minHeight: '320px' }}>
            <WindChart
              readings={readings?.error ? [] : (readings?.readings ?? [])}
              loading={loading && !readings}
            />
          </div>
          <div style={{ minHeight: '320px' }}>
            <DepthProfile
              reading={latestFull}
              loading={loading && !readings}
            />
          </div>
        </div>

        {/* ── Forecast + Stratification Row ── */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
          <div style={{ minHeight: '280px' }}>
            <ForecastCard
              forecast={forecast?.error ? { error: true, status: forecast.status } : forecast}
              loading={loading && !forecast}
            />
          </div>
          <div style={{ minHeight: '280px' }}>
            <StratificationCard
              stratification={stratification?.error ? { error: true, status: stratification.status } : stratification}
              loading={loading && !stratification}
            />
          </div>
        </div>

        {/* ── Live Feed ── */}
        <LiveFeed
          readings={readings?.error ? [] : (readings?.readings ?? [])}
          loading={loading && !readings}
        />

        {/* ── Footer ── */}
        <footer style={{
          borderTop: '1px solid var(--border)',
          paddingTop: '16px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '8px',
          color: 'var(--text-muted)',
          fontSize: '11px',
        }}>
          <span>Sentinel-Stream v2.0.0 · Lake Mendota NTL-LTER Digital Twin · UW-Madison SSEC</span>
          <span>Polling every {POLL_INTERVAL_MS / 1000}s · FastAPI @ localhost:8000</span>
        </footer>
      </main>
    </div>
  )
}
