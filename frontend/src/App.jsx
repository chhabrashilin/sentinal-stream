import React, { useState, useEffect, useCallback } from 'react'
import Header from './components/Header.jsx'
import BuoyBanner from './components/BuoyBanner.jsx'
import MetricCard from './components/MetricCard.jsx'
import WindChart from './components/WindChart.jsx'
import DepthProfile from './components/DepthProfile.jsx'
import ForecastCard from './components/ForecastCard.jsx'
import StratificationCard from './components/StratificationCard.jsx'
import LiveFeed from './components/LiveFeed.jsx'
import ActivitySafety from './components/ActivitySafety.jsx'

const POLL_MS = 2000

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

export default function App() {
  const [status,      setStatus]      = useState(null)
  const [readings,    setReadings]    = useState(null)
  const [forecast,    setForecast]    = useState(null)
  const [strat,       setStrat]       = useState(null)
  const [buoyStatus,  setBuoyStatus]  = useState(null)
  const [loading,     setLoading]     = useState(true)
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
    const timer = setInterval(fetchAll, POLL_MS)
    return () => clearInterval(timer)
  }, [fetchAll])

  // Derived metrics from the /status latest_reading snapshot
  const latest     = status?.latest_reading
  const latestFull = readings?.readings?.[0]

  const airTemp     = latest?.air_temp_c
  const windSmooth  = latest?.smoothed_wind_ms
  const surfaceTemp = latest?.water_temp_0m ?? latestFull?.water_temp_profile?.['0m']
  const chlorophyll = latest?.chlorophyll_ugl ?? latestFull?.chlorophyll_ugl
  const recordCount = status?.record_count

  const readingRows = readings?.error ? [] : (readings?.readings ?? [])

  return (
    <div className="app-shell">
      <Header lastUpdated={lastUpdated} />

      <main className="main-content">

        {/* KPI metric cards */}
        <div className="metric-grid">
          <MetricCard
            label="Air Temperature"
            value={airTemp != null ? airTemp.toFixed(1) : null}
            unit="°C"
            color="#f59e0b"
            sublabel="Buoy mast height"
            loading={loading && airTemp == null}
          />
          <MetricCard
            label="Wind Speed"
            value={windSmooth != null ? windSmooth.toFixed(2) : null}
            unit="m/s"
            color="#4a8fff"
            sublabel="10-pt smoothed"
            loading={loading && windSmooth == null}
          />
          <MetricCard
            label="Surface Water Temp"
            value={surfaceTemp != null ? surfaceTemp.toFixed(2) : null}
            unit="°C"
            color="#00ceb4"
            sublabel="Depth 0 m (epilimnion)"
            loading={loading && surfaceTemp == null}
          />
          <MetricCard
            label="Chlorophyll-a"
            value={chlorophyll != null ? chlorophyll.toFixed(1) : null}
            unit="µg/L"
            color="#a78bfa"
            sublabel="HAB proxy indicator"
            loading={loading && chlorophyll == null}
          />
          <MetricCard
            label="Total Records"
            value={recordCount != null ? recordCount.toLocaleString() : null}
            unit=""
            color="#4a8fff"
            sublabel="In database"
            loading={loading && recordCount == null}
          />
        </div>

        {/* SSEC buoy status banner */}
        <BuoyBanner buoyStatus={buoyStatus?.error ? null : buoyStatus} />

        {/* Wind + depth profile charts */}
        <div className="chart-row">
          <div className="chart-cell">
            <WindChart readings={readingRows} loading={loading && !readings} />
          </div>
          <div className="chart-cell">
            <DepthProfile reading={latestFull} loading={loading && !readings} />
          </div>
        </div>

        {/* Forecast + stratification panels */}
        <div className="panel-row">
          <div className="panel-cell">
            <ForecastCard
              forecast={forecast?.error ? { error: true, status: forecast.status } : forecast}
              loading={loading && !forecast}
            />
          </div>
          <div className="panel-cell">
            <StratificationCard
              stratification={strat?.error ? { error: true, status: strat.status } : strat}
              loading={loading && !strat}
            />
          </div>
        </div>

        {/* Activity safety assessment */}
        <ActivitySafety
          wind={windSmooth}
          waterTemp={surfaceTemp}
          chl={chlorophyll}
          loading={loading && airTemp == null}
        />

        {/* Recent readings table */}
        <LiveFeed readings={readingRows} loading={loading && !readings} />

        <footer className="app-footer">
          <span>Sentinel-Stream v2.0.0 · Lake Mendota NTL-LTER Digital Twin · UW-Madison SSEC</span>
          <span>Live sensor polling every {POLL_MS / 1000}s</span>
        </footer>

      </main>
    </div>
  )
}
