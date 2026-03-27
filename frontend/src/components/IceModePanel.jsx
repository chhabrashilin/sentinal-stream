import React, { useState } from 'react'

export default function IceModePanel({ iceMode, onToggle, loading }) {
  const [toggling, setToggling] = useState(false)

  async function handleToggle() {
    if (toggling) return
    setToggling(true)
    try {
      await onToggle(!iceMode?.ice_mode_enabled)
    } finally {
      setToggling(false)
    }
  }

  const enabled = iceMode?.ice_mode_enabled ?? false

  return (
    <div className={`ice-panel ${enabled ? 'ice-panel--active' : ''}`}>
      <div className="ice-panel__left">
        <div className="ice-panel__icon">{enabled ? '❄' : '🌊'}</div>
        <div>
          <div className="ice-panel__title">
            Ice-In Mode
            <span
              className="ice-panel__badge"
              style={{
                color:       enabled ? '#7dd3fc' : '#00ceb4',
                background:  enabled ? 'rgba(125,211,252,0.1)' : 'rgba(0,206,180,0.1)',
                borderColor: enabled ? 'rgba(125,211,252,0.3)' : 'rgba(0,206,180,0.3)',
              }}
            >
              {enabled ? 'ESTIMATION' : 'LIVE'}
            </span>
          </div>
          <div className="ice-panel__subtitle">
            {enabled
              ? 'Physical sensors retracted. Digital twin running on ML estimation only.'
              : 'Physical sensors online. Digital twin in live verification mode.'}
          </div>
          <div className="ice-panel__context">
            {enabled
              ? 'Activate during ice cover (typically late November through mid-March on Mendota). The ML model predicts subsurface water temperatures from air temp and wind alone, maintaining data continuity year-round. Accuracy is lower than live mode (+/-1-2°C vs +/-0.3-0.5°C with sensors deployed).'
              : 'Activate when buoy technicians retract the thermistor chain for winter. Keep off during the open-water season so the digital twin can compare ML predictions against live sensor readings.'}
          </div>
        </div>
      </div>

      <button
        className={`ice-toggle ${enabled ? 'ice-toggle--on' : 'ice-toggle--off'}`}
        onClick={handleToggle}
        disabled={toggling || loading}
        title={enabled ? 'Deactivate Ice-In mode' : 'Activate Ice-In mode'}
      >
        <span className="ice-toggle__track">
          <span className="ice-toggle__thumb" />
        </span>
        <span className="ice-toggle__label">
          {toggling ? '...' : enabled ? 'ON' : 'OFF'}
        </span>
      </button>
    </div>
  )
}
