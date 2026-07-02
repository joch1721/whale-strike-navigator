import { useState, useEffect } from 'react'
import axios from 'axios'
import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'
import './SpeciesDrawer.css'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const MONTH_LABELS = ['J','F','M','A','M','J','J','A','S','O','N','D']

const IUCN_COLORS = {
  'Critically Endangered': '#ff2d55',
  'Endangered':            '#ff9f0a',
  'Vulnerable':            '#ffd60a',
  'Least Concern':         '#30d158',
}

const THREATS_ICONS = {
  'Ship strikes':                  '🚢',
  'Entanglement in fishing gear':  '🎣',
  'Entanglement':                  '🎣',
  'Climate change':                '🌡',
  'Noise pollution':               '🔊',
  'Legacy whaling impacts':        '📜',
}

// Monthly occurrence counts from our risk data per species
// We'll fetch this from the API occurrence data
function useMonthlyOccurrences(speciesKey) {
  const [data, setData] = useState(null)

  useEffect(() => {
    if (!speciesKey) return
    // Fetch risk summary and extract monthly presence signal
    axios.get(`${API}/risk/summary`)
      .then(r => {
        const months = r.data.months || []
        const chartData = Array.from({ length: 12 }, (_, i) => {
          const m = months.find(mo => mo.month === i + 1)
          if (!m) return { month: MONTH_LABELS[i], value: 0, hasData: false }
          // Count cells where this species is present
          const topCells = m.top_cells || []
          const speciesUpper = speciesKey.toUpperCase()
          const presenceCells = topCells.filter(c =>
            c.species_present && c.species_present.includes(speciesUpper)
          ).length
          return {
            month: MONTH_LABELS[i],
            value: presenceCells,
            hasData: true,
          }
        })
        setData(chartData)
      })
      .catch(console.error)
  }, [speciesKey])

  return data
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      <div className="chart-tooltip-value">{payload[0].value} cells</div>
    </div>
  )
}

export default function SpeciesDrawer({ speciesKey, speciesData, onClose }) {
  const monthlyData = useMonthlyOccurrences(speciesKey)

  if (!speciesData) return null

  const iucnColor = IUCN_COLORS[speciesData.iucn_status] || '#7eb8d4'
  const popRange = `${speciesData.est_population_low.toLocaleString()} – ${speciesData.est_population_high.toLocaleString()}`

  return (
    <div className="species-drawer">
      {/* Header */}
      <div className="drawer-header" style={{ borderColor: iucnColor }}>
        <div>
          <div className="drawer-common">{speciesData.common_name}</div>
          <div className="drawer-sci">{speciesData.scientific_name}</div>
        </div>
        <button className="drawer-close" onClick={onClose}>×</button>
      </div>

      {/* IUCN status */}
      <div className="drawer-iucn" style={{ color: iucnColor, borderColor: `${iucnColor}33` }}>
        <span className="iucn-dot" style={{ background: iucnColor }} />
        {speciesData.iucn_status}
      </div>

      {/* Population */}
      <div className="drawer-section">
        <div className="drawer-section-label">ESTIMATED POPULATION</div>
        <div className="drawer-pop">{popRange}</div>
        <div className="drawer-pop-note">{speciesData.population_note}</div>
      </div>

      {/* Primary threats */}
      <div className="drawer-section">
        <div className="drawer-section-label">PRIMARY THREATS</div>
        <div className="drawer-threats">
          {(speciesData.primary_threats || []).map(threat => (
            <div key={threat} className="threat-item">
              <span className="threat-icon">
                {THREATS_ICONS[threat] || '⚠️'}
              </span>
              <span className="threat-label">{threat}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Monthly presence chart */}
      <div className="drawer-section">
        <div className="drawer-section-label">MONTHLY PRESENCE SIGNAL</div>
        {monthlyData ? (
          <div className="drawer-chart">
            <ResponsiveContainer width="100%" height={70}>
              <BarChart data={monthlyData} margin={{ top: 4, right: 0, left: 0, bottom: 0 }}>
                <XAxis
                  dataKey="month"
                  tick={{ fill: '#3d6680', fontSize: 9, fontFamily: 'IBM Plex Mono' }}
                  axisLine={false}
                  tickLine={false}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="value" radius={[2, 2, 0, 0]}>
                  {monthlyData.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={entry.hasData ? iucnColor : '#1a2a3a'}
                      opacity={entry.value > 0 ? 0.8 : 0.3}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <div className="chart-note">Top-10 risk cells containing species per month</div>
          </div>
        ) : (
          <div className="chart-loading">Loading...</div>
        )}
      </div>

      {/* Size stats */}
      <div className="drawer-section">
        <div className="drawer-section-label">PHYSICAL PROFILE</div>
        <div className="drawer-stats-grid">
          <div className="drawer-stat">
            <div className="drawer-stat-value">
              {speciesData.typical_length_m || '—'}m
            </div>
            <div className="drawer-stat-label">Length</div>
          </div>
          <div className="drawer-stat">
            <div className="drawer-stat-value">
              {speciesData.typical_mass_tonnes || '—'}t
            </div>
            <div className="drawer-stat-label">Mass</div>
          </div>
        </div>
      </div>
    </div>
  )
}
