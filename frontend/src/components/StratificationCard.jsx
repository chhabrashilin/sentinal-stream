import React from 'react'

const cardStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '20px',
  height: '100%',
  display: 'flex',
  flexDirection: 'column',
  gap: '16px',
}

const STATUS_CONFIG = {
  stratified: {
    label: 'STRATIFIED',
    color: '#ef5350',
    bg: 'rgba(239,83,80,0.12)',
    border: 'rgba(239,83,80,0.3)',
    note: 'HAB risk elevated — thermally isolated epilimnion',
  },
  weakly_stratified: {
    label: 'WEAKLY STRATIFIED',
    color: '#ff9800',
    bg: 'rgba(255,152,0,0.12)',
    border: 'rgba(255,152,0,0.3)',
    note: 'Partial mixing — some vertical exchange occurring',
  },
  mixed: {
    label: 'MIXED',
    color: '#00bcd4',
    bg: 'rgba(0,188,212,0.12)',
    border: 'rgba(0,188,212,0.3)',
    note: 'Full water column turnover — lower HAB risk',
  },
}

export default function StratificationCard({ stratification, loading }) {
  if (loading) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>Thermal Stratification</div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
          Computing stratification...
        </div>
      </div>
    )
  }

  if (!stratification || stratification.error) {
    return (
      <div style={cardStyle}>
        <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)' }}>Thermal Stratification</div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: '10px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '32px', opacity: 0.25 }}>~</div>
          <div style={{ fontWeight: 500 }}>{stratification?.status === 422 ? 'No Data Yet' : 'Unavailable'}</div>
          <div style={{ fontSize: '11px', textAlign: 'center', maxWidth: '220px', lineHeight: '1.6' }}>
            {stratification?.status === 422
              ? 'Stream sensor data to compute stratification.'
              : 'Could not retrieve stratification from backend.'}
          </div>
        </div>
      </div>
    )
  }

  const cfg = STATUS_CONFIG[stratification.stratification_status] || STATUS_CONFIG.mixed
  const strength = stratification.thermocline_strength_c

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: '13px', fontWeight: 600, color: 'var(--text-secondary)', letterSpacing: '0.02em' }}>
            Thermal Stratification
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
            NTL-LTER depth profile analysis
          </div>
        </div>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          padding: '4px 10px',
          borderRadius: '4px',
          background: cfg.bg,
          border: `1px solid ${cfg.border}`,
          fontSize: '11px',
          fontWeight: 700,
          color: cfg.color,
          letterSpacing: '0.06em',
        }}>
          {cfg.label}
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '12px', padding: '8px 0' }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Surface (0m)
          </div>
          <div style={{ fontSize: '32px', fontWeight: 800, color: '#ef5350', lineHeight: 1 }}>
            {stratification.surface_temp_c.toFixed(1)}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>°C</div>
        </div>

        <div style={{ textAlign: 'center', padding: '0 16px' }}>
          <div style={{
            fontSize: '52px',
            fontWeight: 900,
            color: cfg.color,
            lineHeight: 1,
            letterSpacing: '-2px',
            textShadow: `0 0 20px ${cfg.color}60`,
          }}>
            {strength >= 0 ? '+' : ''}{strength.toFixed(1)}
          </div>
          <div style={{ fontSize: '12px', color: cfg.color, fontWeight: 600, marginTop: '2px' }}>°C Δt</div>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginTop: '2px' }}>thermocline strength</div>
        </div>

        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '4px' }}>
            Deep (20m)
          </div>
          <div style={{ fontSize: '32px', fontWeight: 800, color: '#26c6da', lineHeight: 1 }}>
            {stratification.deep_temp_c.toFixed(1)}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '2px' }}>°C</div>
        </div>
      </div>

      <div style={{ padding: '10px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: '6px', borderLeft: `3px solid ${cfg.color}` }}>
        <div style={{ fontSize: '11px', color: cfg.color, fontWeight: 500, marginBottom: '4px' }}>{cfg.note}</div>
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', lineHeight: '1.6' }}>
          Δt = 0m temp − 20m temp. {'>'} 10°C = strongly stratified (HAB risk elevated). {'<'} 4°C = well-mixed column.
        </div>
      </div>
    </div>
  )
}
