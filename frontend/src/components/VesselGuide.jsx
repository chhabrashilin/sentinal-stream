import React, { useState } from 'react'

const ADVISORY_COLORS = {
  safe:    { bg: '#0a2a1f', border: '#00ceb4', text: '#00ceb4', label: 'SAFE' },
  caution: { bg: '#2a1f00', border: '#f59e0b', text: '#f59e0b', label: 'CAUTION' },
  danger:  { bg: '#2a0a0a', border: '#ff4444', text: '#ff4444', label: 'DANGER' },
}

const HYPOTHERMIA_COLORS = {
  negligible: '#00ceb4',
  low:        '#4a8fff',
  moderate:   '#f59e0b',
  high:       '#ff6b35',
  critical:   '#ff4444',
}

const WATER_QUALITY_COLORS = {
  excellent: '#00ceb4',
  good:      '#4a8fff',
  fair:      '#f59e0b',
  poor:      '#ff6b35',
  hazardous: '#ff4444',
}

const STRAT_ICONS = {
  mixed:              '〰',
  weakly_stratified:  '≋',
  stratified:         '≡',
}

function BeaufortBar({ number }) {
  const pct = Math.min(100, (number / 12) * 100)
  const color =
    number <= 2 ? '#00ceb4' :
    number <= 4 ? '#4a8fff' :
    number <= 6 ? '#f59e0b' :
    number <= 8 ? '#ff6b35' : '#ff4444'
  return (
    <div className="beaufort-bar-wrap">
      <div className="beaufort-bar-track">
        <div className="beaufort-bar-fill" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="beaufort-label" style={{ color }}>Bf {number}</span>
    </div>
  )
}

function VesselCard({ vessel }) {
  const [open, setOpen] = useState(false)
  const colors = ADVISORY_COLORS[vessel.status]

  return (
    <div
      className="vessel-card"
      style={{ borderColor: colors.border, background: colors.bg }}
      onClick={() => setOpen(o => !o)}
    >
      <div className="vessel-card-header">
        <span className="vessel-icon">{vessel.icon}</span>
        <div className="vessel-card-title">
          <span className="vessel-name">{vessel.name}</span>
          <span className="vessel-description">{vessel.description}</span>
        </div>
        <span className="vessel-status-badge" style={{ color: colors.text, borderColor: colors.border }}>
          {colors.label}
        </span>
        <span className="vessel-expand-icon">{open ? '▲' : '▼'}</span>
      </div>

      {open && (
        <div className="vessel-card-body">
          <div className="vessel-reasons">
            {vessel.reasons.map((r, i) => (
              <div key={i} className="vessel-reason">
                <span className="vessel-reason-dot" style={{ color: colors.text }}>●</span>
                <span>{r}</span>
              </div>
            ))}
          </div>
          <div className="vessel-rec" style={{ borderLeftColor: colors.border }}>
            {vessel.recommendation}
          </div>
          <div className="vessel-limits-row">
            <span className="vessel-limit-item">
              Wind caution: <b>{vessel.limits.wind_caution_ms} m/s</b>
            </span>
            <span className="vessel-limit-item">
              Wind danger: <b>{vessel.limits.wind_danger_ms} m/s</b>
            </span>
            <span className="vessel-limit-item">
              Wave caution: <b>{vessel.limits.wave_caution_m} m</b>
            </span>
            <span className="vessel-limit-item">
              Wave danger: <b>{vessel.limits.wave_danger_m} m</b>
            </span>
            {vessel.limits.water_temp_danger_c != null && (
              <span className="vessel-limit-item">
                Temp danger: <b>≤{vessel.limits.water_temp_danger_c}°C</b>
              </span>
            )}
            {vessel.limits.chl_danger_ugl != null && (
              <span className="vessel-limit-item">
                Chl-a danger: <b>≥{vessel.limits.chl_danger_ugl} µg/L</b>
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default function VesselGuide({ guide, loading }) {
  const [filterStatus, setFilterStatus] = useState('all')

  if (loading) {
    return (
      <div className="vessel-guide-panel loading-panel">
        <div className="panel-loading">Loading vessel guide…</div>
      </div>
    )
  }

  if (!guide || guide.error) {
    return (
      <div className="vessel-guide-panel">
        <div className="panel-header">
          <span className="panel-title">Vessel & Recreation Guide</span>
        </div>
        <div className="panel-error">
          {guide?.status === 422
            ? 'Vessel guide unavailable. Stream sensor data first.'
            : 'Vessel guide service unavailable.'}
        </div>
      </div>
    )
  }

  const overall   = ADVISORY_COLORS[guide.overall_advisory]
  const hydro     = HYPOTHERMIA_COLORS[guide.hypothermia_risk]    ?? '#aaa'
  const waterQual = WATER_QUALITY_COLORS[guide.water_quality_level] ?? '#aaa'

  const filteredVessels = guide.vessels.filter(
    v => filterStatus === 'all' || v.status === filterStatus
  )

  return (
    <div className="vessel-guide-panel">
      {/* Header */}
      <div className="panel-header">
        <span className="panel-title">Vessel &amp; Recreation Guide</span>
        <span
          className="overall-advisory-badge"
          style={{ background: overall.bg, color: overall.text, borderColor: overall.border }}
        >
          {overall.label}: {guide.safe_count} safe · {guide.caution_count} caution · {guide.danger_count} danger
        </span>
      </div>

      {/* Conditions summary strip */}
      <div className="vessel-conditions-strip">

        {/* Wind / Beaufort */}
        <div className="condition-block">
          <div className="condition-label">Wind</div>
          <div className="condition-value">{guide.wind_ms.toFixed(1)} <span className="condition-unit">m/s</span></div>
          <BeaufortBar number={guide.beaufort_number} />
          <div className="condition-sub">{guide.beaufort_description}</div>
        </div>

        {/* Wave height */}
        <div className="condition-block">
          <div className="condition-label">Waves (sig. / max)</div>
          <div className="condition-value">
            {guide.wave_height_sig_m.toFixed(2)} <span className="condition-unit">m</span>
          </div>
          <div className="condition-sub">Max ~{guide.wave_height_max_m.toFixed(2)} m</div>
          <div className="condition-sub" style={{ marginTop: 4, opacity: 0.6, fontSize: '0.68rem' }}>
            H<sub>sig</sub> = 0.01 × U<sup>1.5</sup>
          </div>
        </div>

        {/* Air temperature */}
        <div className="condition-block">
          <div className="condition-label">Air Temp</div>
          <div className="condition-value">{guide.air_temp_c.toFixed(1)} <span className="condition-unit">°C</span></div>
          <div className="condition-sub">Buoy mast height</div>
        </div>

        {/* Hypothermia */}
        <div className="condition-block">
          <div className="condition-label">Water Temp</div>
          <div className="condition-value" style={{ color: hydro }}>
            {guide.water_temp_c.toFixed(1)} <span className="condition-unit">°C</span>
          </div>
          <div className="condition-sub" style={{ color: hydro, fontWeight: 600 }}>
            Hypothermia: {guide.hypothermia_risk.toUpperCase()}
          </div>
          <div className="condition-sub">Incapacitation {guide.hypothermia_incapacitation}</div>
          <div className="condition-sub">Survival {guide.hypothermia_survival}</div>
        </div>

        {/* Water quality */}
        <div className="condition-block">
          <div className="condition-label">Water Quality</div>
          <div className="condition-value" style={{ color: waterQual }}>
            {guide.chlorophyll_ugl.toFixed(1)} <span className="condition-unit">µg/L</span>
          </div>
          <div className="condition-sub" style={{ color: waterQual, fontWeight: 600 }}>
            {guide.water_quality_advisory}
          </div>
          <div className="condition-sub">{guide.water_quality_visual}</div>
          <div className="condition-sub" style={{ opacity: 0.75 }}>Contact: {guide.water_quality_contact}</div>
        </div>

        {/* Stratification */}
        <div className="condition-block">
          <div className="condition-label">Lake Stratification</div>
          <div className="condition-value">
            {STRAT_ICONS[guide.stratification_status] ?? '?'}
          </div>
          <div className="condition-sub" style={{ fontWeight: 600, textTransform: 'capitalize' }}>
            {guide.stratification_status.replace('_', ' ')}
          </div>
          <div className="condition-sub" style={{ fontSize: '0.68rem', lineHeight: 1.3 }}>
            {guide.stratification_note}
          </div>
        </div>
      </div>

      {/* Hypothermia advisory */}
      <div className="hypothermia-advisory" style={{ borderLeftColor: hydro }}>
        <span className="hypo-label" style={{ color: hydro }}>Cold water risk:</span>
        <span className="hypo-note">{guide.hypothermia_note}</span>
      </div>

      {/* Vessel filter buttons */}
      <div className="vessel-filter-row">
        <span className="vessel-filter-label">Show:</span>
        {['all', 'safe', 'caution', 'danger'].map(s => (
          <button
            key={s}
            className={`vessel-filter-btn ${filterStatus === s ? 'active' : ''}`}
            style={filterStatus === s ? {
              borderColor: s === 'all' ? '#4a8fff' : ADVISORY_COLORS[s]?.border,
              color:       s === 'all' ? '#4a8fff' : ADVISORY_COLORS[s]?.text,
            } : {}}
            onClick={() => setFilterStatus(s)}
          >
            {s === 'all'
              ? `All (${guide.vessels.length})`
              : `${s.charAt(0).toUpperCase() + s.slice(1)} (${guide.vessels.filter(v => v.status === s).length})`}
          </button>
        ))}
      </div>

      {/* Vessel cards */}
      <div className="vessel-list">
        {filteredVessels.map(v => (
          <VesselCard key={v.vessel_type} vessel={v} />
        ))}
      </div>

      <div className="vessel-guide-footer">
        Limits based on US Coast Guard, ACA, Wisconsin DNR, and UW-Madison Hoofer Clubs guidelines.
        Last updated: {new Date(guide.timestamp + (guide.timestamp.endsWith('Z') ? '' : 'Z')).toLocaleTimeString()}
      </div>
    </div>
  )
}
