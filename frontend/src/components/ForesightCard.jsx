import React from 'react'

const RISK_LEVEL = {
  low:      { color: '#00ceb4', bg: 'rgba(0,206,180,0.12)',    border: 'rgba(0,206,180,0.3)',    label: 'LOW' },
  moderate: { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)',   border: 'rgba(245,158,11,0.3)',   label: 'MODERATE' },
  high:     { color: '#ff6b6b', bg: 'rgba(255,107,107,0.12)',  border: 'rgba(255,107,107,0.3)',  label: 'HIGH' },
  critical: { color: '#ff2d55', bg: 'rgba(255,45,85,0.15)',    border: 'rgba(255,45,85,0.4)',    label: 'CRITICAL' },
  unknown:  { color: '#64748b', bg: 'rgba(100,116,139,0.12)',  border: 'rgba(100,116,139,0.3)',  label: 'UNKNOWN' },
}

const RISK_ICON = { hab: 'HAB', anoxia: 'O2', turnover: 'MIX', none: '-' }
const RISK_LABEL = { hab: 'HAB', anoxia: 'Anoxia', turnover: 'Turnover', none: 'None' }

const RISK_CONTEXT = {
  hab: {
    what: 'Harmful Algal Bloom (HAB) risk from cyanobacteria accumulating in the surface layer.',
    driven: 'Driven by: strong stratification (traps algae near surface) + calm wind (no mixing) + existing chlorophyll-a (nutrients available).',
    thresholds: [
      { score: '0 - 30', level: 'Low', action: 'Routine monitoring. No action required.' },
      { score: '30 - 50', level: 'Moderate', action: 'Weekly water sampling. Alert beach managers.' },
      { score: '50 - 70', level: 'High', action: 'Daily sampling. Prepare public advisory language.' },
      { score: '70+', level: 'Critical', action: 'Issue HAB advisory. Notify DNR. Close affected beaches.' },
    ],
  },
  anoxia: {
    what: 'Hypolimnetic oxygen depletion: the deep water layer losing dissolved oxygen due to prolonged thermal isolation.',
    driven: 'Driven by: thermocline strength (cuts off O2 recharge) + warm deep water (bacterial decomposition accelerates) + algal biomass (more decomposition as cells sink).',
    thresholds: [
      { score: '0 - 30', level: 'Low', action: 'No action. Deep water well-oxygenated.' },
      { score: '30 - 50', level: 'Moderate', action: 'Monitor dissolved oxygen at depth. Alert fish hatcheries.' },
      { score: '50 - 70', level: 'High', action: 'Deep O2 depletion likely. Cold-water fish refugia at risk.' },
      { score: '70+', level: 'Critical', action: 'Benthic organisms at risk. Issue advisory. Monitor for fish stress.' },
    ],
  },
  turnover: {
    what: 'Lake overturn risk: surface cooling to hypolimnion density, causing full water-column mixing.',
    driven: 'Driven by: rapid surface cooling rate + high wind speed (physical mixing energy) + stratification vulnerability (weakly stratified columns are closest to the tipping point).',
    thresholds: [
      { score: '0 - 30', level: 'Low', action: 'No action. Column thermally stable.' },
      { score: '30 - 50', level: 'Moderate', action: 'Monitor wind and surface temp. Alert downstream waterways.' },
      { score: '50 - 70', level: 'High', action: 'Overturn possible in 24-48 h. Post waterway advisory.' },
      { score: '70+', level: 'Critical', action: 'Overturn likely. Anoxic water may resurface. Possible fish kill.' },
    ],
  },
}

function RiskBar({ label, value, color }) {
  const pct = Math.max(0, Math.min(1, value)) * 100
  return (
    <div className="risk-bar">
      <div className="risk-bar__header">
        <span className="risk-bar__label">{label}</span>
        <span className="risk-bar__value" style={{ color }}>{(value * 100).toFixed(0)}%</span>
      </div>
      <div className="risk-bar__track">
        <div
          className="risk-bar__fill"
          style={{ width: `${pct}%`, background: color, boxShadow: `0 0 6px ${color}60` }}
        />
      </div>
    </div>
  )
}

function RiskExplainer({ riskKey, scores }) {
  const ctx = RISK_CONTEXT[riskKey]
  if (!ctx) return null
  const score = (scores?.[riskKey] ?? 0) * 100
  const active = score >= 30 ? 'moderate' : 'low'
  const lvl = RISK_LEVEL[score >= 70 ? 'critical' : score >= 50 ? 'high' : score >= 30 ? 'moderate' : 'low']

  return (
    <div className="risk-explainer" style={{ borderLeftColor: lvl.color }}>
      <div className="risk-explainer__name" style={{ color: lvl.color }}>
        {RISK_LABEL[riskKey]}: {score.toFixed(0)}/100
      </div>
      <div className="risk-explainer__what">{ctx.what}</div>
      <div className="risk-explainer__driven">{ctx.driven}</div>
      <div className="risk-explainer__thresholds">
        {ctx.thresholds.map((t, i) => {
          const isActive =
            (t.level === 'Critical' && score >= 70) ||
            (t.level === 'High' && score >= 50 && score < 70) ||
            (t.level === 'Moderate' && score >= 30 && score < 50) ||
            (t.level === 'Low' && score < 30)
          return (
            <div key={i} className={`risk-threshold-row ${isActive ? 'risk-threshold-row--active' : ''}`}
              style={isActive ? { borderLeftColor: lvl.color } : {}}>
              <span className="risk-threshold-score">{t.score}</span>
              <span className="risk-threshold-level">{t.level}</span>
              <span className="risk-threshold-action">{t.action}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default function ForesightCard({ foresight, loading }) {
  if (loading) {
    return (
      <div className="card">
        <div className="card-title">48-Hour Foresight</div>
        <div className="state-center">Computing risk assessment...</div>
      </div>
    )
  }

  if (!foresight || foresight.error) {
    const noData = foresight?.status === 422
    return (
      <div className="card">
        <div className="card-title">48-Hour Foresight</div>
        <div className="state-center">
          <div className="state-icon">~</div>
          <div className="state-title">{noData ? 'No Data Yet' : 'Unavailable'}</div>
          <div className="state-hint">
            {noData ? 'Stream sensor data to enable foresight.' : 'Could not retrieve risk assessment.'}
          </div>
        </div>
      </div>
    )
  }

  const lvl = RISK_LEVEL[foresight.risk_level] ?? RISK_LEVEL.unknown
  const scores = foresight.risk_scores ?? {}
  const habColor    = RISK_LEVEL[scores.hab    >= 0.7 ? 'critical' : scores.hab    >= 0.5 ? 'high' : scores.hab    >= 0.3 ? 'moderate' : 'low'].color
  const anoxColor   = RISK_LEVEL[scores.anoxia >= 0.7 ? 'critical' : scores.anoxia >= 0.5 ? 'high' : scores.anoxia >= 0.3 ? 'moderate' : 'low'].color
  const turnColor   = RISK_LEVEL[scores.turnover >= 0.7 ? 'critical' : scores.turnover >= 0.5 ? 'high' : scores.turnover >= 0.3 ? 'moderate' : 'low'].color

  return (
    <div className="card foresight-card">
      <div className="card-header">
        <div>
          <div className="card-title">48-Hour Foresight</div>
          <div className="card-subtitle">HAB + Anoxia + Turnover risk assessment</div>
        </div>
        <div
          className="badge badge--sm badge--square"
          style={{ color: lvl.color, background: lvl.bg, borderColor: lvl.border }}
        >
          {RISK_ICON[foresight.primary_risk] ?? '?'} {lvl.label}
        </div>
      </div>

      {/* Aggregate risk score */}
      <div className="foresight-score">
        <div
          className="foresight-score__value"
          style={{ color: lvl.color, textShadow: `0 0 24px ${lvl.color}50` }}
        >
          {(foresight.risk_score * 100).toFixed(0)}
        </div>
        <div className="foresight-score__unit" style={{ color: lvl.color }}>/ 100</div>
        <div className="foresight-score__label">
          Primary: {RISK_LABEL[foresight.primary_risk] ?? foresight.primary_risk}
        </div>
      </div>

      {/* Per-category risk bars */}
      <div className="foresight-bars">
        <RiskBar label="HAB"      value={scores.hab      ?? 0} color={habColor} />
        <RiskBar label="Anoxia"   value={scores.anoxia   ?? 0} color={anoxColor} />
        <RiskBar label="Turnover" value={scores.turnover ?? 0} color={turnColor} />
      </div>

      {/* Recommendation */}
      <div className="foresight-rec" style={{ borderLeft: `3px solid ${lvl.color}` }}>
        <div className="foresight-rec__title" style={{ color: lvl.color }}>Recommendation</div>
        <div className="foresight-rec__body">{foresight.recommendation}</div>
      </div>

      {/* Contributing factors */}
      {foresight.contributing_factors?.length > 0 && (
        <div className="foresight-factors">
          {foresight.contributing_factors.map((f, i) => (
            <div key={i} className="foresight-factor">
              <span className="foresight-factor__dot" style={{ background: lvl.color }} />
              <span className="foresight-factor__text">{f}</span>
            </div>
          ))}
        </div>
      )}

      {/* Per-risk explanations */}
      <div className="foresight-explainers">
        <div className="inference-block__heading" style={{ marginBottom: 8 }}>Risk category breakdown</div>
        <RiskExplainer riskKey="hab"      scores={scores} />
        <RiskExplainer riskKey="anoxia"   scores={scores} />
        <RiskExplainer riskKey="turnover" scores={scores} />
      </div>
    </div>
  )
}
