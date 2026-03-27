import React from 'react'

// ─── Cold water reference ─────────────────────────────────────
const COLD_WATER_BANDS = [
  { max: 5,  risk: 'Critical', color: '#ff4444', incapacitation: 'under 7 min', survival: 'under 30 min', note: 'Cold shock and cardiac arrest risk on entry. Drysuit mandatory.' },
  { max: 10, risk: 'High',     color: '#ff6b35', incapacitation: '7 - 30 min',  survival: '30 - 60 min',  note: 'Rapid muscle incapacitation. Wetsuit minimum. PFD required.' },
  { max: 15, risk: 'Moderate', color: '#f59e0b', incapacitation: '30 - 60 min', survival: '1 - 6 hours',  note: 'Prolonged immersion hazardous. Wetsuit recommended.' },
  { max: 20, risk: 'Low',      color: '#4a8fff', incapacitation: '1 - 2 hours', survival: '6 - 12 hours', note: 'Comfortable for short activities. Wetsuit for multi-hour exposure.' },
  { max: 999,risk: 'Negligible',color: '#00ceb4',incapacitation: 'over 2 hours',survival: 'Safe',         note: 'Comfortable for recreational activities.' },
]

function getColdWaterBand(temp) {
  return COLD_WATER_BANDS.find(b => temp < b.max) ?? COLD_WATER_BANDS[COLD_WATER_BANDS.length - 1]
}

// ─── Algae reference ──────────────────────────────────────────
const CHL_BANDS = [
  { max: 5,   level: 'Excellent', color: '#00ceb4', visual: 'Crystal clear, deep visibility', contact: 'Safe' },
  { max: 15,  level: 'Good',      color: '#4a8fff', visual: 'Slight greenish tinge, normal',  contact: 'Safe' },
  { max: 30,  level: 'Fair',      color: '#f59e0b', visual: 'Noticeably green, shore foam possible', contact: 'Rinse after contact' },
  { max: 70,  level: 'HAB Advisory', color: '#ff6b35', visual: 'Dense green/blue-green, scum possible', contact: 'Avoid contact (cyanotoxin risk)' },
  { max: 999, level: 'HAB Warning',  color: '#ff4444', visual: 'Paint-like surface, blue-green scum',   contact: 'No contact (cyanotoxins confirmed)' },
]

function getChlBand(chl) {
  return CHL_BANDS.find(b => chl < b.max) ?? CHL_BANDS[CHL_BANDS.length - 1]
}

// ─── Factor helpers ───────────────────────────────────────────

function windFactor(wind, { unsafe, caution, tooLight = null }) {
  if (wind == null) return { status: 'caution', label: 'Wind: no data' }
  if (tooLight != null && wind < tooLight)
    return { status: 'caution', label: `Wind ${wind.toFixed(1)} m/s (too light)` }
  if (wind >= unsafe)
    return { status: 'unsafe',  label: `Wind ${wind.toFixed(1)} m/s (dangerous)` }
  if (wind >= caution)
    return { status: 'caution', label: `Wind ${wind.toFixed(1)} m/s (elevated)` }
  return   { status: 'safe',   label: `Wind ${wind.toFixed(1)} m/s` }
}

function waterTempFactor(temp, { unsafe, caution, context = 'cold water risk' }) {
  if (temp == null) return { status: 'caution', label: 'Water temp: no data' }
  if (temp <= unsafe)
    return { status: 'unsafe',  label: `Water ${temp.toFixed(1)} °C (${context})` }
  if (temp <= caution)
    return { status: 'caution', label: `Water ${temp.toFixed(1)} °C (limit exposure)` }
  return   { status: 'safe',   label: `Water ${temp.toFixed(1)} °C` }
}

function algaeFactor(chl) {
  if (chl == null) return { status: 'caution', label: 'Algae: no data' }
  if (chl >= 50) return { status: 'unsafe',  label: `Chl-a ${chl.toFixed(1)} ug/L (HAB advisory)` }
  if (chl >= 20) return { status: 'caution', label: `Chl-a ${chl.toFixed(1)} ug/L (elevated)` }
  return           { status: 'safe',   label: `Chl-a ${chl.toFixed(1)} ug/L (clear)` }
}

// ─── Aggregate status ─────────────────────────────────────────

function worstOf(factors) {
  const statuses = factors.map(f => f.status)
  if (statuses.includes('unsafe'))  return 'unsafe'
  if (statuses.includes('caution')) return 'caution'
  return 'safe'
}

// ─── Activity definitions ─────────────────────────────────────

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

// ─── Sub-components ───────────────────────────────────────────

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

// ─── Main component ───────────────────────────────────────────

export default function ActivitySafety({ wind, waterTemp, chl, loading }) {
  const noData = wind == null && waterTemp == null && chl == null

  const activities = noData ? [] : buildActivities({ wind, waterTemp, chl })
  const coldBand   = waterTemp != null ? getColdWaterBand(waterTemp) : null
  const chlBand    = chl != null ? getChlBand(chl) : null

  return (
    <div className="safety-panel">
      <div className="safety-panel__header">
        <div>
          <div className="safety-panel__title">Lake Activity Safety</div>
          <div className="safety-panel__subtitle">
            Real-time assessment based on wind, water temperature, and algae levels.
            For full vessel-class breakdown, see the Vessel and Recreation Guide above.
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

          {/* Cold water context */}
          {coldBand && (
            <div className="safety-context-block" style={{ borderLeftColor: coldBand.color }}>
              <div className="safety-context-block__heading" style={{ color: coldBand.color }}>
                Cold water risk: {coldBand.risk}
              </div>
              <div className="safety-context-block__row">
                <span className="safety-context-key">Water temp:</span>
                <span>{waterTemp?.toFixed(1)}°C</span>
              </div>
              <div className="safety-context-block__row">
                <span className="safety-context-key">Incapacitation:</span>
                <span>{coldBand.incapacitation}</span>
              </div>
              <div className="safety-context-block__row">
                <span className="safety-context-key">Survival time:</span>
                <span>{coldBand.survival}</span>
              </div>
              <div className="safety-context-block__note">{coldBand.note}</div>
              <div className="safety-context-block__rule">
                Rule: dress for the water temperature, not the air. A warm sunny day with 8°C water
                is still a survival situation on capsize. Incapacitation begins before you feel cold.
              </div>
            </div>
          )}

          {/* Algae/HAB context */}
          {chlBand && (
            <div className="safety-context-block" style={{ borderLeftColor: chlBand.color }}>
              <div className="safety-context-block__heading" style={{ color: chlBand.color }}>
                Water quality: {chlBand.level}
              </div>
              <div className="safety-context-block__row">
                <span className="safety-context-key">Chlorophyll-a:</span>
                <span>{chl?.toFixed(1)} ug/L</span>
              </div>
              <div className="safety-context-block__row">
                <span className="safety-context-key">Appearance:</span>
                <span>{chlBand.visual}</span>
              </div>
              <div className="safety-context-block__row">
                <span className="safety-context-key">Contact:</span>
                <span style={{ color: chlBand.color }}>{chlBand.contact}</span>
              </div>
              {chl >= 30 && (
                <div className="safety-context-block__note">
                  Cyanobacterial HABs produce microcystin (liver toxin). Above 30 ug/L: avoid skin
                  contact. Above 70 ug/L: do not enter the water. Keep children and pets out regardless of appearance.
                  After a bloom collapses, toxin levels may remain elevated for 1-2 weeks.
                </div>
              )}
              {chl >= 15 && chl < 30 && (
                <div className="safety-context-block__note">
                  Algal biomass is elevated above baseline. Not yet at advisory levels, but rinse off
                  after water contact and avoid swallowing lake water.
                </div>
              )}
            </div>
          )}

          <div className="safety-panel__disclaimer">
            Thresholds based on Wisconsin DNR guidelines and Lake Mendota recreational advisories.
            Always verify conditions with local forecasts before going on the water.
          </div>
        </>
      )}
    </div>
  )
}
