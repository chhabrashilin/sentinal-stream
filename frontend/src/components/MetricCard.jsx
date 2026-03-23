import React from 'react'

const cardStyle = {
  background: 'var(--bg-card)',
  border: '1px solid var(--border)',
  borderRadius: '8px',
  padding: '18px 20px',
  display: 'flex',
  flexDirection: 'column',
  gap: '4px',
  minWidth: 0,
  transition: 'border-color 0.2s',
  position: 'relative',
  overflow: 'hidden',
}

const accentBarStyle = (color) => ({
  position: 'absolute',
  top: 0,
  left: 0,
  right: 0,
  height: '3px',
  background: color || 'var(--accent-blue)',
  borderRadius: '8px 8px 0 0',
})

export default function MetricCard({ label, value, unit, color, sublabel, loading }) {
  return (
    <div style={cardStyle}>
      <div style={accentBarStyle(color)} />
      <div style={{ fontSize: '11px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-muted)', marginTop: '2px' }}>
        {label}
      </div>
      {loading ? (
        <div style={{ height: '36px', background: 'var(--border)', borderRadius: '4px', width: '70%', marginTop: '4px', opacity: 0.5 }} />
      ) : (
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px', marginTop: '2px' }}>
          <span style={{ fontSize: '28px', fontWeight: 700, color: color || 'var(--text-primary)', lineHeight: 1, letterSpacing: '-0.5px' }}>
            {value ?? '—'}
          </span>
          {unit && (
            <span style={{ fontSize: '13px', color: 'var(--text-secondary)', fontWeight: 500 }}>
              {unit}
            </span>
          )}
        </div>
      )}
      {sublabel && (
        <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
          {sublabel}
        </div>
      )}
    </div>
  )
}
