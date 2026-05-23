import './StatsBar.css'

const MONTHS = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December'
]

export default function StatsBar({ summary, month, loading }) {
  if (!summary) return (
    <div className="stats-bar">
      <div className="stat-item">
        <div className="stat-value dim">—</div>
        <div className="stat-label">LOADING</div>
      </div>
    </div>
  )

  const { tier_counts, max_score, total_cells } = summary
  const critical = tier_counts?.critical || 0
  const high     = tier_counts?.high || 0
  const medium   = tier_counts?.medium || 0

  return (
    <div className="stats-bar">
      <div className="stat-item">
        <div className="stat-value" style={{ color: '#ff2d55' }}>
          {critical.toLocaleString()}
        </div>
        <div className="stat-label">CRITICAL</div>
      </div>
      <div className="stat-divider" />
      <div className="stat-item">
        <div className="stat-value" style={{ color: '#ff9f0a' }}>
          {high.toLocaleString()}
        </div>
        <div className="stat-label">HIGH</div>
      </div>
      <div className="stat-divider" />
      <div className="stat-item">
        <div className="stat-value" style={{ color: '#30d158' }}>
          {medium.toLocaleString()}
        </div>
        <div className="stat-label">MEDIUM</div>
      </div>
      <div className="stat-divider" />
      <div className="stat-item">
        <div className="stat-value">{max_score?.toFixed(1)}</div>
        <div className="stat-label">MAX SCORE</div>
      </div>
      <div className="stat-divider" />
      <div className="stat-item">
        <div className="stat-value dim">{MONTHS[month - 1].toUpperCase()}</div>
        <div className="stat-label">2024</div>
      </div>
      {loading && <div className="stat-loading">↻</div>}
    </div>
  )
}
