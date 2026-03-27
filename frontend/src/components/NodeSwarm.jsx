import React from 'react'

const NODE_CONTEXT = {
  'node-center': { role: 'NTL-LTER reference buoy position (master)', note: 'Primary measurement point matching the UW-Madison SSEC buoy. All foresight and stratification calculations use readings from the most recent clean record across all nodes.' },
  'node-north':  { role: 'Northern basin monitor', note: 'Deeper water zone. HAB onset typically arrives here later than in the shallow south bay. Watch for chl-a divergence from center node.' },
  'node-south':  { role: 'Southern shallow bay', note: 'First to show HAB conditions. Warm, nutrient-rich, less wind exposure. If chl-a here is elevated vs. center, bloom is nucleating in the south bay.' },
  'node-east':   { role: 'Yahara River inlet', note: 'Primary external phosphorus source. Elevated chl-a or turbidity after rain events indicates watershed nutrient loading.' },
  'node-west':   { role: 'Western shore / upwelling zone', note: 'In prevailing SW winds, this node may show cooler subsurface upwelling. Temperature anomaly vs. center = wind-driven circulation event.' },
}

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
  return Date.now() - new Date(isoStr).getTime() < 15_000
}

function NodeCard({ node }) {
  const active = isActive(node.last_seen)
  const ctx    = NODE_CONTEXT[node.node_id]
  return (
    <div className={`node-card ${active ? 'node-card--active' : 'node-card--idle'}`}>
      <div className="node-card__header">
        <div className="node-card__id">{node.node_id}</div>
        <div className={`node-card__dot ${active ? 'node-dot--active' : 'node-dot--idle'}`} />
      </div>
      <div className="node-card__location">{node.location ?? 'Unknown'}</div>
      {ctx && <div className="node-card__role">{ctx.role}</div>}
      <div className="node-card__coords">
        {node.lat?.toFixed(4)}° N, {Math.abs(node.long)?.toFixed(4)}° W
      </div>
      <div className="node-card__footer">
        <span className="node-card__reads">{(node.reading_count ?? 0).toLocaleString()} readings</span>
        <span className="node-card__seen">{timeSince(node.last_seen)}</span>
      </div>
      {ctx && <div className="node-card__note">{ctx.note}</div>}
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
            Distributed sensor network across Lake Mendota (5 positions)
          </div>
        </div>
        <div className="swarm-panel__count">
          <span className="swarm-count__active">{activeCount}</span>
          <span className="swarm-count__sep">/</span>
          <span className="swarm-count__total">{nodeList.length}</span>
          <span className="swarm-count__label">nodes active</span>
        </div>
      </div>

      <div className="inference-block" style={{ marginBottom: 12 }}>
        <div className="inference-block__body">
          Spatial divergence between nodes is ecologically informative. If the south node shows
          elevated chlorophyll while others remain low, a bloom is nucleating in the warm shallow
          bay. If the east node spikes after a rain event, the Yahara River is delivering
          phosphorus load. Active nodes (green pulse) sent a reading in the last 15 seconds.
          Idle nodes may be experiencing RF packet loss (normal at 10% drop rate) or a hardware fault.
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
