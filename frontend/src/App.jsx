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
import ForesightCard from './components/ForesightCard.jsx'
import IceModePanel from './components/IceModePanel.jsx'
import NodeSwarm from './components/NodeSwarm.jsx'
import DigitalTwinCard from './components/DigitalTwinCard.jsx'
import VesselGuide from './components/VesselGuide.jsx'

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

async function postJSON(path, body) {
  try {
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      return { error: true, status: res.status, detail: data.detail }
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
  const [foresight,   setForesight]   = useState(null)
  const [iceMode,     setIceMode]     = useState(null)
  const [nodes,       setNodes]       = useState(null)
  const [twin,        setTwin]        = useState(null)
  const [vesselGuide, setVesselGuide] = useState(null)
  const [loading,     setLoading]     = useState(true)
  const [lastUpdated, setLastUpdated] = useState(null)

  const fetchAll = useCallback(async () => {
    const [
      statusData, readingsData, forecastData, stratData, buoyData,
      foresightData, iceModeData, nodesData, twinData, vesselData,
    ] = await Promise.all([
      fetchJSON('/api/status'),
      fetchJSON('/api/readings?n=60'),
      fetchJSON('/api/forecast'),
      fetchJSON('/api/stratification'),
      fetchJSON('/api/buoy-status'),
      fetchJSON('/api/foresight'),
      fetchJSON('/api/ice-mode'),
      fetchJSON('/api/nodes'),
      fetchJSON('/api/digital-twin'),
      fetchJSON('/api/vessel-guide'),
    ])

    setStatus(statusData)
    setReadings(readingsData)
    setForecast(forecastData)
    setStrat(stratData)
    setBuoyStatus(buoyData)
    setForesight(foresightData)
    setIceMode(iceModeData)
    setNodes(nodesData)
    setTwin(twinData)
    setVesselGuide(vesselData)
    setLoading(false)
    setLastUpdated(new Date().toLocaleTimeString('en-US', { hour12: false }))
  }, [])

  useEffect(() => {
    fetchAll()
    const timer = setInterval(fetchAll, POLL_MS)
    return () => clearInterval(timer)
  }, [fetchAll])

  async function handleIceModeToggle(enabled) {
    const result = await postJSON('/api/ice-mode', { enabled })
    if (!result.error) {
      setIceMode(result)
    }
  }

  // Derived metrics
  const latest     = status?.latest_reading
  const latestFull = readings?.readings?.[0]

  const airTemp     = latest?.air_temp_c
  const windSmooth  = latest?.smoothed_wind_ms
  const surfaceTemp = latest?.water_temp_0m ?? latestFull?.water_temp_profile?.['0m']
  const chlorophyll = latest?.chlorophyll_ugl ?? latestFull?.chlorophyll_ugl
  const recordCount = status?.record_count

  const readingRows = readings?.error ? [] : (readings?.readings ?? [])
  const nodeList    = Array.isArray(nodes) ? nodes : []

  return (
    <div className="app-shell">
      <Header lastUpdated={lastUpdated} />

      <main className="main-content">

        {/* Ice-In mode toggle */}
        <IceModePanel
          iceMode={iceMode?.error ? null : iceMode}
          onToggle={handleIceModeToggle}
          loading={loading && !iceMode}
        />

        {/* KPI metric cards */}
        <div className="metric-grid">
          <MetricCard
            label="Air Temperature"
            value={airTemp != null ? airTemp.toFixed(1) : null}
            unit="°C"
            color="#f59e0b"
            sublabel="Buoy mast height"
            context={
              airTemp != null
                ? airTemp > 25
                  ? 'Warm air accelerates surface heating. HAB risk window elevated if wind stays calm.'
                  : airTemp < 0
                    ? 'Below freezing. Ice formation possible within 1-3 days. Prepare sensors for winter.'
                    : 'Normal range for current season. Mar avg: 0-12°C. Jul avg: 20-32°C.'
                : 'Air temp drives surface heat flux and evaporative cooling. Key input for digital twin.'
            }
            loading={loading && airTemp == null}
          />
          <MetricCard
            label="Wind Speed"
            value={windSmooth != null ? windSmooth.toFixed(2) : null}
            unit="m/s"
            color="#4a8fff"
            sublabel="10-pt smoothed"
            context={
              windSmooth != null
                ? windSmooth < 2
                  ? 'Calm. Algae scum may form at surface. HAB risk elevated if conditions persist 3+ days.'
                  : windSmooth < 5
                    ? 'Light wind. Minimal mixing. Cyanobacteria can aggregate at surface.'
                    : windSmooth < 8
                      ? 'Moderate wind disrupting surface algae accumulation.'
                      : windSmooth < 15
                        ? 'Strong mixing. Bloom disruption likely. Small craft exercise caution.'
                        : 'Dangerous wind. All small craft should be off the water.'
                : 'Wind is the primary lake mixing driver. Above 5 m/s disrupts HAB blooms. Below 2 m/s for 3+ days is the classic HAB setup.'
            }
            loading={loading && windSmooth == null}
          />
          <MetricCard
            label="Surface Water Temp"
            value={surfaceTemp != null ? surfaceTemp.toFixed(2) : null}
            unit="°C"
            color="#00ceb4"
            sublabel="Depth 0 m (epilimnion)"
            context={
              surfaceTemp != null
                ? surfaceTemp < 5
                  ? 'Critical cold water. Survival time under 30 min without drysuit. No swimming.'
                  : surfaceTemp < 10
                    ? 'High hypothermia risk. Incapacitation in 7-30 min. Wetsuit + PFD required.'
                    : surfaceTemp < 15
                      ? 'Moderate cold water risk. Dress for immersion, not air temperature.'
                      : surfaceTemp < 20
                        ? 'Cool but manageable. Wetsuit recommended for multi-hour activities.'
                        : 'Comfortable. Cyanobacteria thrive above 20°C. Monitor chl-a closely.'
                : 'Surface temp drives stratification, HAB risk, and cold water survival time.'
            }
            loading={loading && surfaceTemp == null}
          />
          <MetricCard
            label="Chlorophyll-a"
            value={chlorophyll != null ? chlorophyll.toFixed(1) : null}
            unit="µg/L"
            color="#a78bfa"
            sublabel="HAB proxy indicator"
            context={
              chlorophyll != null
                ? chlorophyll < 5
                  ? 'Excellent. Crystal clear water. No algal concerns.'
                  : chlorophyll < 15
                    ? 'Good. Slight greenish tinge. Normal seasonal appearance.'
                    : chlorophyll < 30
                      ? 'Fair. Noticeably green. Shore foam possible. Rinse after water contact.'
                      : chlorophyll < 70
                        ? 'HAB Advisory. Avoid skin contact. Paint-like green surface. Cyanotoxin risk.'
                        : 'HAB Warning. Do not enter the water. Notify Wisconsin DNR. Close beaches.'
                : 'Chl-a is a proxy for algal biomass. Above 30 ug/L = HAB advisory. Above 70 ug/L = HAB warning. Historical Mendota peak: 300+ ug/L in severe summers.'
            }
            loading={loading && chlorophyll == null}
          />
          <MetricCard
            label="Total Records"
            value={recordCount != null ? recordCount.toLocaleString() : null}
            unit=""
            color="#4a8fff"
            sublabel="In database"
            context="Number of sensor readings ingested since last reset. Outliers are stored but flagged. The digital twin retrains every 100 new records."
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

        {/* Digital Twin + Foresight panels */}
        <div className="panel-row">
          <div className="panel-cell">
            <DigitalTwinCard
              twin={twin?.error ? { error: true, status: twin.status } : twin}
              loading={loading && !twin}
            />
          </div>
          <div className="panel-cell">
            <ForesightCard
              foresight={foresight?.error ? { error: true, status: foresight.status } : foresight}
              loading={loading && !foresight}
            />
          </div>
        </div>

        {/* Edge node swarm */}
        <NodeSwarm nodes={nodeList} loading={loading && !nodes} />

        {/* Vessel & recreation guide */}
        <VesselGuide
          guide={vesselGuide?.error ? { error: true, status: vesselGuide.status } : vesselGuide}
          loading={loading && !vesselGuide}
        />

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
