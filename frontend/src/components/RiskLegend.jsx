import './RiskLegend.css'

const TIERS = [
  { key: 'critical', color: '#ff2d55', label: 'CRITICAL', range: '≥ 20.5' },
  { key: 'high', color: '#ff9f0a', label: 'HIGH', range: '15.8 – 20.5' },
  { key: 'medium', color: '#30d158', label: 'MEDIUM', range: '8.5 – 15.8' },
  { key: 'low', color: '#0a84ff', label: 'LOW', range: '< 8.5' },
]

const VESSEL_SPEEDS = [
  { color: '#ff9f0a', label: 'Fast', range: '> 14 kn' },
  { color: '#ffd60a', label: 'Medium', range: '10–14 kn' },
  { color: '#30d158', label: 'Slow', range: '< 10 kn' },
]

export default function RiskLegend({ showLive }) {
  return (
    <div className="panel legend">
      <div className="panel-label">Risk Score</div>
      <div className="legend-items">
        {TIERS.map(t => (
          <div key={t.key} className="legend-item">
            <span className="legend-dot" style={{ background: t.color }} />
            <span className="legend-tier">{t.label}</span>
            <span className="legend-range">{t.range}</span>
          </div>
        ))}
      </div>
      <div className="legend-divider" />
      <div className="legend-items">
        <div className="legend-item">
          <span className="legend-line sma-line" />
          <span className="legend-tier">SMA Zone</span>
        </div>
        <div className="legend-item">
          <span className="legend-dot incident-dot" />
          <span className="legend-tier">Strike Incident</span>
        </div>
      </div>

      <div className="legend-divider" />
      <div className="legend-items">
        <div className="legend-item">
          <span className="legend-dot confidence-dot" />
          <span className="legend-tier">Low confidence</span>
          <span className="legend-range">&lt;5 sightings</span>
        </div>
      </div>

      {showLive && (
        <>
          <div className="legend-divider" />
          <div className="panel-label" style={{ marginBottom: 6 }}>Live Vessels</div>
          <div className="legend-items">
            {VESSEL_SPEEDS.map(v => (
              <div key={v.label} className="legend-item">
                <span className="legend-dot" style={{ background: v.color, borderRadius: '50%' }} />
                <span className="legend-tier">{v.label}</span>
                <span className="legend-range">{v.range}</span>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
