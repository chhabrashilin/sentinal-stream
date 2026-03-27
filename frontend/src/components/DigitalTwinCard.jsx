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
  const r2Pct = Math.max(0, Math.min(1, twin.model_r2 ?? 0)) * 100
  const r2Color = (twin.model_r2 ?? 0) >= 0.7 ? '#00ceb4' : (twin.model_r2 ?? 0) >= 0.4 ? '#f59e0b' : '#ff6b6b'

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

      <div className="twin-header-row">
        <span className="twin-col-depth">Depth</span>
        <span className="twin-col-pred">ML Predicted</span>
        <span className="twin-col-meas">{isIce ? 'Mode' : 'Measured'}</span>
        {!isIce && <span className="twin-col-delta">Δ Error</span>}
      </div>

      <div className="twin-rows">
        <TempRow depth="0m"  predicted={twin.surface_temp_c}  measured={isIce ? null : twin.surface_temp_c} />
        <TempRow depth="5m"  predicted={twin.predicted_5m_c}  measured={twin.measured_5m_c} />
        <TempRow depth="10m" predicted={twin.predicted_10m_c} measured={twin.measured_10m_c} />
        <TempRow depth="20m" predicted={twin.predicted_20m_c} measured={twin.measured_20m_c} />
      </div>

      {/* Model R² bar */}
      <div className="r2-bar">
        <div className="r2-bar__header">
          <span className="r2-bar__title">Model R² (physics features)</span>
          <span className="r2-bar__value" style={{ color: r2Color }}>
            {(twin.model_r2 ?? 0).toFixed(3)}
          </span>
        </div>
        <div className="r2-bar__track">
          <div
            className="r2-bar__fill"
            style={{ width: `${r2Pct}%`, background: r2Color, boxShadow: `0 0 8px ${r2Color}60` }}
          />
        </div>
      </div>
    </div>
  )
}
