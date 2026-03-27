import React from 'react'

const STATUS = {
  stratified: {
    label: 'STRATIFIED',
    cls: 'badge--stratified',
    color: '#ff6b6b',
    note: 'Strong thermocline present. Epilimnion thermally isolated from deep water.',
    ecology: 'The warm surface layer (epilimnion) is cut off from the cold hypolimnion below the thermocline. Cyanobacteria thrive here: they float to the nutrient-rich surface, avoid the colder depths, and are not mixed back down by wind. This is the highest-HAB-risk configuration. Deep water (20m) is likely becoming or already oxygen-depleted (anoxic).',
    actions: [
      'Increase chlorophyll-a sampling to daily',
      'Prepare HAB public advisory communications',
      'Alert fish hatcheries: cold-water fish losing refugia at depth',
      'Do not allow WWTP bypass events during stratification',
    ],
  },
  weakly_stratified: {
    label: 'WEAKLY STRATIFIED',
    cls: 'badge--weakly_stratified',
    color: '#f59e0b',
    note: 'Thermocline forming. Surface warming faster than deep water.',
    ecology: 'A partial thermal barrier is developing. Some vertical mixing still occurs, distributing oxygen through the metalimnion (mid-layer). This is the transition state: if warm air and calm wind persist for several more days, the column will lock into full stratification. If a wind event (>8 m/s) arrives, it may mix the column back to uniform. Chlorophyll-a is likely rising as phytoplankton begin to accumulate in the warming surface layer.',
    actions: [
      'Sample water quality twice per week',
      'Monitor wind forecast: calm conditions will accelerate stratification',
      'Begin drafting advisory language in case chl-a rises above 20 ug/L',
    ],
  },
  mixed: {
    label: 'MIXED',
    cls: 'badge--mixed',
    color: '#00ceb4',
    note: 'Full water-column circulation. Temperature and oxygen uniform with depth.',
    ecology: 'Wind and convective cooling are continuously mixing the entire water column. Temperature, dissolved oxygen, and nutrients are distributed uniformly from surface to bottom. This is the safest configuration for water quality: algae cannot accumulate at the surface, and deep-water anoxia cannot develop. Typical of post ice-out spring conditions (March to April) and active fall turnover (October). If this reading occurs in summer, a significant wind event has temporarily mixed the column.',
    actions: [
      'Safe window for nutrient treatment or algaecide application (mixing distributes it)',
      'Routine weekly monitoring is sufficient',
      'If occurring during fall: watch for turnover-linked fish kills and surface toxin release',
    ],
  },
}

export default function StratificationCard({ stratification, loading }) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">Thermal Stratification</div>
        <div className="state-center">Computing stratification...</div>
      </div>
    )
  }

  if (!stratification || stratification.error) {
    const noData = stratification?.status === 422
    return (
      <div className="card">
        <div className="card-title">Thermal Stratification</div>
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">{noData ? 'No Data Yet' : 'Unavailable'}</div>
          <div className="state-hint">
            {noData
              ? 'Stream sensor data to compute stratification.'
              : 'Could not retrieve stratification from backend.'}
          </div>
        </div>
      </div>
    )
  }

  const cfg      = STATUS[stratification.stratification_status] ?? STATUS.mixed
  const strength = stratification.thermocline_strength_c

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">Thermal Stratification</div>
          <div className="card-subtitle">NTL-LTER depth profile analysis</div>
        </div>
        <div className={`badge badge--sm badge--square ${cfg.cls}`}>{cfg.label}</div>
      </div>

      <div className="strat-temps">
        <div className="strat-temp-block">
          <div className="strat-temp-label">Surface (0m)</div>
          <div className="strat-temp-value" style={{ color: '#ff6b6b' }}>
            {stratification.surface_temp_c.toFixed(1)}
          </div>
          <div className="strat-temp-unit">°C</div>
        </div>

        <div className="strat-delta">
          <div
            className="strat-delta__value"
            style={{ color: cfg.color, textShadow: `0 0 20px ${cfg.color}60` }}
          >
            {strength >= 0 ? '+' : ''}{strength.toFixed(1)}
          </div>
          <div className="strat-delta__unit" style={{ color: cfg.color }}>°C Dt</div>
          <div className="strat-delta__caption">thermocline strength</div>
        </div>

        <div className="strat-temp-block">
          <div className="strat-temp-label">Deep (20m)</div>
          <div className="strat-temp-value" style={{ color: '#00ceb4' }}>
            {stratification.deep_temp_c.toFixed(1)}
          </div>
          <div className="strat-temp-unit">°C</div>
        </div>
      </div>

      {/* Status note */}
      <div className="strat-note" style={{ borderLeft: `3px solid ${cfg.color}` }}>
        <div className="strat-note__title" style={{ color: cfg.color }}>{cfg.note}</div>
        <div className="strat-note__body">
          Dt = 0m temp - 20m temp. Above 10°C = strongly stratified (HAB risk elevated). Below 4°C = well-mixed column.
        </div>
      </div>

      {/* Ecological context */}
      <div className="inference-block">
        <div className="inference-block__heading">What this means</div>
        <div className="inference-block__body">{cfg.ecology}</div>
      </div>

      {/* Action list */}
      <div className="inference-actions">
        <div className="inference-actions__heading">Recommended actions</div>
        <ul className="inference-actions__list">
          {cfg.actions.map((a, i) => (
            <li key={i} className="inference-actions__item">
              <span className="inference-dot" style={{ color: cfg.color }}>+</span>
              {a}
            </li>
          ))}
        </ul>
      </div>

      {/* Threshold reference */}
      <div className="threshold-table">
        <div className="threshold-table__title">Classification thresholds</div>
        <div className="threshold-row">
          <span className="threshold-label" style={{ color: '#ff6b6b' }}>Stratified</span>
          <span className="threshold-value">Dt &gt;= 10°C</span>
          <span className="threshold-desc">HAB risk high. Deep O2 depleting.</span>
        </div>
        <div className="threshold-row">
          <span className="threshold-label" style={{ color: '#f59e0b' }}>Weakly stratified</span>
          <span className="threshold-value">4 - 10°C</span>
          <span className="threshold-desc">Transition state. Monitor closely.</span>
        </div>
        <div className="threshold-row">
          <span className="threshold-label" style={{ color: '#00ceb4' }}>Mixed</span>
          <span className="threshold-value">Dt &lt; 4°C</span>
          <span className="threshold-desc">Full circulation. Lower HAB risk.</span>
        </div>
      </div>
    </div>
  )
}
