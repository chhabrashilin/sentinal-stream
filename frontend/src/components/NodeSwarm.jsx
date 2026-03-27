import React from 'react'

function timeSince(isoStr) {
  if (!isoStr) return 'never'
  const diff = Date.now() - new Date(isoStr).getTime()
  const s = Math.floor(diff / 1000)
  if (s < 60)  return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60)  return `${m}m ago`
  const h = Math.floor(m / 60)
  return `${h}h ago`
}

function isActive(isoStr) {
  if (!isoStr) return false
  return Date.now() - new Date(isoStr).getTime() < 15_000 // active if seen in last 15s
}

function NodeCard({ node }) {
  const active = isActive(node.last_seen)
  return (
    <div className={`node-card ${active ? 'node-card--active' : 'node-card--idle'}`}>
      <div className="node-card__header">
        <div className="node-card__id">{node.node_id}</div>
        <div className={`node-card__dot ${active ? 'node-dot--active' : 'node-dot--idle'}`} />
      </div>
      <div className="node-card__location">{node.location ?? '—'}</div>
      <div className="node-card__coords">
        {node.lat?.toFixed(4)}° N, {Math.abs(node.long)?.toFixed(4)}° W
      </div>
      <div className="node-card__footer">
        <span className="node-card__reads">{(node.reading_count ?? 0).toLocaleString()} readings</span>
        <span className="node-card__seen">{timeSince(node.last_seen)}</span>
      </div>
    </div>
  )
}

export default function NodeSwarm({ nodes, loading }) {
  if (loading && (!nodes || nodes.length === 0)) {
    return (
      <div className="swarm-panel">
        <div className="swarm-panel__header">
          <div className="swarm-panel__title">Edge Node Swarm</div>
        </div>
        <div className="state-center" style={{ padding: '20px 0' }}>
          <div className="state-title">Discovering nodes...</div>
        </div>
      </div>
    )
  }

  const nodeList = nodes?.error ? [] : (nodes ?? [])
  const activeCount = nodeList.filter(n => isActive(n.last_seen)).length

  return (
    <div className="swarm-panel">
      <div className="swarm-panel__header">
        <div>
          <div className="swarm-panel__title">Edge Node Swarm</div>
          <div className="swarm-panel__subtitle">
            Distributed sensor network — Lake Mendota spatial coverage
          </div>
        </div>
        <div className="swarm-panel__count">
          <span className="swarm-count__active">{activeCount}</span>
          <span className="swarm-count__sep">/</span>
          <span className="swarm-count__total">{nodeList.length}</span>
          <span className="swarm-count__label">nodes active</span>
        </div>
      </div>

      {nodeList.length === 0 ? (
        <div className="state-center" style={{ padding: '20px 0' }}>
          <div className="state-icon">~</div>
          <div className="state-title">No nodes registered</div>
          <div className="state-hint">Start the sensor emulator containers to populate the swarm.</div>
        </div>
      ) : (
        <div className="node-grid">
          {nodeList.map(n => <NodeCard key={n.node_id} node={n} />)}
        </div>
      )}
    </div>
  )
}
