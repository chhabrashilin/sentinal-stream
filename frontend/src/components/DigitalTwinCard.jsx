import React from 'react'

const DEPTH_COLORS = {
  '0m':  '#ff6b6b',
  '5m':  '#f59e0b',
  '10m': '#4a8fff',
  '20m': '#00ceb4',
}

function TempRow({ depth, predicted, measured }) {
  const color = DEPTH_COLORS[depth] ?? '#8aabee'
  const delta = measured != null ? (predicted - measured).toFixed(2) : null
  const deltaColor = delta == null ? null : Math.abs(delta) <= 0.3 ? '#00ceb4' : Math.abs(delta) <= 0.8 ? '#f59e0b' : '#ff6b6b'

  return (
    <div className="twin-row">
      <span className="twin-row__depth" style={{ color }}>{depth}</span>
      <span className="twin-row__predicted" style={{ color }}>{predicted?.toFixed(2)}°C</span>
      {measured != null
        ? <span className="twin-row__measured">{measured.toFixed(2)}°C</span>
        : <span className="twin-row__ice-tag">estimation</span>
      }
      {delta != null && (
        <span className="twin-row__delta" style={{ color: deltaColor }}>
          {delta > 0 ? '+' : ''}{delta}°C
        </span>
      )}
    </div>
  )
}

const R2_BANDS = [
  { min: 0.9, color: '#00ceb4', label: 'Excellent', desc: 'Model tracking live conditions closely.' },
  { min: 0.7, color: '#4a8fff', label: 'Good',      desc: 'Minor disagreements from local wind events.' },
  { min: 0.5, color: '#f59e0b', label: 'Acceptable', desc: 'Spring transition or post-turnover variance.' },
  { min: 0.0, color: '#ff6b6b', label: 'Weak fit',  desc: 'Lake undergoing rapid change (storm, turnover).' },
]

function getR2Band(r2) {
  return R2_BANDS.find(b => r2 >= b.min) ?? R2_BANDS[R2_BANDS.length - 1]
}

export default function DigitalTwinCard({ twin, loading }) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">Physics-Informed Digital Twin</div>
        <div className="state-center">Training ML model...</div>
      </div>
    )
  }

  if (!twin || twin.error) {
    const noData = twin?.status === 422
    return (
      <div className="card">
        <div className="card-title">Physics-Informed Digital Twin</div>
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">{noData ? 'Training...' : 'Unavailable'}</div>
          <div className="state-hint">
            {noData
              ? 'Accumulating records to train subsurface predictor.'
              : 'Could not retrieve digital twin state.'}
          </div>
        </div>
      </div>
    )
  }

  const isIce = twin.ice_mode
  const r2Val = twin.model_r2 ?? 0
  const r2Pct = Math.max(0, Math.min(1, r2Val)) * 100
  const r2Band = getR2Band(r2Val)

  return (
    <div className="card">
      <div className="card-header">
        <div>
          <div className="card-title">Physics-Informed Digital Twin</div>
          <div className="card-subtitle">
            Ridge regression · {twin.records_used} training records
          </div>
        </div>
        <div
          className="badge badge--sm badge--square"
          style={{
            color:       isIce ? '#7dd3fc' : '#00ceb4',
            background:  isIce ? 'rgba(125,211,252,0.1)' : 'rgba(0,206,180,0.1)',
            borderColor: isIce ? 'rgba(125,211,252,0.3)' : 'rgba(0,206,180,0.3)',
          }}
        >
          {isIce ? 'ESTIMATION' : 'VERIFICATION'}
        </div>
      </div>

      {/* Mode explanation */}
      <div className="inference-block" style={{ marginBottom: 10 }}>
        {isIce ? (
          <div className="inference-block__body">
            Ice-In mode: physical thermistor chains are retracted for winter. The ML model predicts
            subsurface temperatures from air temp and wind alone, maintaining data continuity
            through ice cover (typically December through mid-March on Mendota). Accuracy is
            lower than live mode (+/-1-2°C vs +/-0.3-0.5°C with sensors).
          </div>
        ) : (
          <div className="inference-block__body">
            Verification mode: ML predictions are compared against live sensor readings at each depth.
            The delta column shows model error. Persistent large errors (+/-0.8°C or more) at a
            specific depth may indicate a localised thermal event (upwelling, nearshore heating)
            that the atmospheric input signals alone cannot capture.
          </div>
        )}
      </div>

      <div className="twin-header-row">
        <span className="twin-col-depth">Depth</span>
        <span className="twin-col-pred">ML Predicted</span>
        <span className="twin-col-meas">{isIce ? 'Mode' : 'Measured'}</span>
        {!isIce && <span className="twin-col-delta">Dt Error</span>}
      </div>

      <div className="twin-rows">
        <TempRow depth="0m"  predicted={twin.surface_temp_c}  measured={isIce ? null : twin.surface_temp_c} />
        <TempRow depth="5m"  predicted={twin.predicted_5m_c}  measured={twin.measured_5m_c} />
        <TempRow depth="10m" predicted={twin.predicted_10m_c} measured={twin.measured_10m_c} />
        <TempRow depth="20m" predicted={twin.predicted_20m_c} measured={twin.measured_20m_c} />
      </div>

      {/* R2 bar */}
      <div className="r2-bar">
        <div className="r2-bar__header">
          <span className="r2-bar__title">Model R² (physics features)</span>
          <span className="r2-bar__value" style={{ color: r2Band.color }}>
            {r2Val.toFixed(3)} ({r2Band.label})
          </span>
        </div>
        <div className="r2-bar__track">
          <div
            className="r2-bar__fill"
            style={{ width: `${r2Pct}%`, background: r2Band.color, boxShadow: `0 0 8px ${r2Band.color}60` }}
          />
        </div>
      </div>

      {/* R2 interpretation */}
      <div className="inference-block" style={{ marginTop: 10 }}>
        <div className="inference-block__heading">R² interpretation</div>
        <div className="inference-block__body" style={{ marginBottom: 8 }}>
          R² measures how well the model predicts depth temperatures from surface atmospheric signals.
          Features used: air temperature, wind speed, wind², and air x wind (captures evaporative cooling).
          Confidence reaches full strength after ~200 clean records (about 3 minutes of streaming).
        </div>
        <div className="threshold-table">
          {R2_BANDS.map(b => (
            <div key={b.label} className={`threshold-row ${r2Val >= b.min && (R2_BANDS.indexOf(b) === 0 || r2Val < R2_BANDS[R2_BANDS.indexOf(b) - 1]?.min) ? 'threshold-row--active' : ''}`}
              style={r2Band.label === b.label ? { borderLeftColor: b.color } : {}}>
              <span className="threshold-label" style={{ color: b.color }}>{b.label}</span>
              <span className="threshold-value">R² {b.min === 0 ? '< 0.5' : b.min === 0.5 ? '0.5 - 0.7' : b.min === 0.7 ? '0.7 - 0.9' : '>= 0.9'}</span>
              <span className="threshold-desc">{b.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
