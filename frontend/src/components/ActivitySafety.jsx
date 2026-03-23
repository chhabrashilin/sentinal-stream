import React from 'react'

// ─── Factor helpers ──────────────────────────────────────────────

function windFactor(wind, { unsafe, caution, tooLight = null }) {
  if (wind == null) return { status: 'caution', label: 'Wind: no data' }
  if (tooLight != null && wind < tooLight)
    return { status: 'caution', label: `Wind ${wind.toFixed(1)} m/s — too light` }
  if (wind >= unsafe)
    return { status: 'unsafe',  label: `Wind ${wind.toFixed(1)} m/s — dangerous` }
  if (wind >= caution)
    return { status: 'caution', label: `Wind ${wind.toFixed(1)} m/s — elevated` }
  return   { status: 'safe',   label: `Wind ${wind.toFixed(1)} m/s` }
}

function waterTempFactor(temp, { unsafe, caution, context = 'cold water risk' }) {
  if (temp == null) return { status: 'caution', label: 'Water temp: no data' }
  if (temp <= unsafe)
    return { status: 'unsafe',  label: `Water ${temp.toFixed(1)} °C — ${context}` }
  if (temp <= caution)
    return { status: 'caution', label: `Water ${temp.toFixed(1)} °C — limit exposure` }
  return   { status: 'safe',   label: `Water ${temp.toFixed(1)} °C` }
}

function algaeFactor(chl) {
  if (chl == null) return { status: 'caution', label: 'Algae: no data' }
  if (chl >= 50) return { status: 'unsafe',  label: `Chl-a ${chl.toFixed(1)} µg/L — HAB advisory` }
  if (chl >= 20) return { status: 'caution', label: `Chl-a ${chl.toFixed(1)} µg/L — elevated` }
  return           { status: 'safe',   label: `Chl-a ${chl.toFixed(1)} µg/L — clear` }
}

// ─── Aggregate status ────────────────────────────────────────────

function worstOf(factors) {
  const statuses = factors.map(f => f.status)
  if (statuses.includes('unsafe'))  return 'unsafe'
  if (statuses.includes('caution')) return 'caution'
  return 'safe'
}

// ─── Activity definitions ────────────────────────────────────────

function buildActivities({ wind, waterTemp, chl }) {
  const activities = [
    {
      label: 'Swimming',
      factors: [
        waterTempFactor(waterTemp, { unsafe: 10, caution: 15, context: 'hypothermia risk' }),
        windFactor(wind, { unsafe: 15, caution: 10 }),
        algaeFactor(chl),
      ],
    },
    {
      label: 'Kayaking',
      factors: [
        windFactor(wind, { unsafe: 20, caution: 12 }),
        waterTempFactor(waterTemp, { unsafe: 5, caution: 10, context: 'capsize = immersion' }),
        algaeFactor(chl),
      ],
    },
    {
      label: 'Sailing',
      factors: [
        windFactor(wind, { unsafe: 20, caution: 15, tooLight: 3 }),
        algaeFactor(chl),
      ],
    },
    {
      label: 'Motorboating',
      factors: [
        windFactor(wind, { unsafe: 20, caution: 15 }),
        algaeFactor(chl),
      ],
    },
    {
      label: 'Fishing',
      factors: [
        windFactor(wind, { unsafe: 20, caution: 15 }),
        algaeFactor(chl),
      ],
    },
    {
      label: 'Paddleboarding',
      factors: [
        windFactor(wind, { unsafe: 10, caution: 6 }),
        waterTempFactor(waterTemp, { unsafe: 5, caution: 12, context: 'capsize = immersion' }),
        algaeFactor(chl),
      ],
    },
  ]

  return activities.map(a => ({ ...a, status: worstOf(a.factors) }))
}

// ─── Sub-components ──────────────────────────────────────────────

const STATUS_META = {
  safe:    { label: 'SAFE',    cls: 'act-badge--safe' },
  caution: { label: 'CAUTION', cls: 'act-badge--caution' },
  unsafe:  { label: 'UNSAFE',  cls: 'act-badge--unsafe' },
}

function ActivityCard({ label, status, factors }) {
  const meta = STATUS_META[status]
  return (
    <div className={`activity-card activity-card--${status}`}>
      <div className="activity-card__header">
        <span className="activity-card__name">{label}</span>
        <span className={`act-badge ${meta.cls}`}>{meta.label}</span>
      </div>
      <ul className="activity-factors">
        {factors.map((f, i) => (
          <li key={i} className="activity-factor">
            <span className={`activity-factor__dot dot--${f.status}`} />
            <span className="activity-factor__label">{f.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ─── Main component ──────────────────────────────────────────────

export default function ActivitySafety({ wind, waterTemp, chl, loading }) {
  const noData = wind == null && waterTemp == null && chl == null

  const activities = noData ? [] : buildActivities({ wind, waterTemp, chl })

  return (
    <div className="safety-panel">
      <div className="safety-panel__header">
        <div>
          <div className="safety-panel__title">Lake Activity Safety</div>
          <div className="safety-panel__subtitle">
            Real-time assessment based on wind, water temperature, and algae levels
          </div>
        </div>
      </div>

      {loading || noData ? (
        <div className="state-center" style={{ padding: '30px 0' }}>
          <div className="state-title">{loading ? 'Loading sensor data...' : 'Awaiting readings'}</div>
          <div className="state-hint">Activity assessment requires live wind, temperature, and chlorophyll data.</div>
        </div>
      ) : (
        <>
          <div className="activity-grid">
            {activities.map(a => (
              <ActivityCard key={a.label} {...a} />
            ))}
          </div>
          <div className="safety-panel__disclaimer">
            Thresholds based on Wisconsin DNR guidelines and Lake Mendota recreational advisories.
            Always verify conditions with local forecasts before going on the water.
          </div>
        </>
      )}
    </div>
  )
}
