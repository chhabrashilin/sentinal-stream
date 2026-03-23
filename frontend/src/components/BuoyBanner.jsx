import React from 'react'

export default function BuoyBanner({ buoyStatus }) {
  if (!buoyStatus) return null

  const isLive = buoyStatus.pipeline_mode === 'live'

  return (
    <div className="buoy-banner">
      <div className="buoy-banner__status">
        <span style={{ fontSize: '16px' }}>🌊</span>
        <span className="buoy-banner__label">SSEC Buoy Status:</span>
        <span className="buoy-banner__message">{buoyStatus.ssec_status_message}</span>
      </div>

      <div className="buoy-banner__meta">
        <div className={`badge badge--sm badge--square ${isLive ? 'badge--live' : 'badge--replay'}`}>
          {buoyStatus.pipeline_mode.toUpperCase()} MODE
        </div>

        {!buoyStatus.ssec_api_reachable && (
          <div className="badge badge--sm badge--square badge--unreachable">API UNREACHABLE</div>
        )}

        {buoyStatus.ssec_last_updated && buoyStatus.ssec_last_updated !== 'unknown' && (
          <span className="buoy-banner__last-updated">
            Last updated: {buoyStatus.ssec_last_updated}
          </span>
        )}
      </div>
    </div>
  )
}
