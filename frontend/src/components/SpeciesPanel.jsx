import { useState, useEffect } from 'react'
import axios from 'axios'
import './SpeciesPanel.css'
import SpeciesDrawer from './SpeciesDrawer'
import WhaleIcon from './WhaleIcon'

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const IUCN_COLORS = {
  'Critically Endangered': '#ff2d55',
  'Endangered':            '#ff9f0a',
  'Vulnerable':            '#ffd60a',
  'Least Concern':         '#30d158',
}



export default function SpeciesPanel({ active, onSelect }) {
  const [species, setSpecies]     = useState([])
  const [expanded, setExpanded]   = useState(null)

  useEffect(() => {
    axios.get(`${API}/species`)
      .then(r => setSpecies(r.data.species))
      .catch(console.error)
  }, [])

  const handleCardClick = (key) => {
    onSelect(active === key ? null : key)
    setExpanded(expanded === key ? null : key)
  }

  const expandedSpecies = species.find(s => s.key === expanded)

  return (
    <div className="species-panel-wrapper">
      <div className="panel species-panel">
        <div className="panel-label">Target Species</div>
        <div className="species-list">
          {species.map(sp => {
            const isActive = active === sp.key
            const iucnColor = IUCN_COLORS[sp.iucn_status] || '#7eb8d4'
            const popMid = Math.round((sp.est_population_low + sp.est_population_high) / 2)

            return (
              <button
                key={sp.key}
                className={`species-card ${isActive ? 'active' : ''}`}
                onClick={() => handleCardClick(sp.key)}
                style={{ '--species-color': iucnColor }}
              >
                <div className="species-header">
                  <WhaleIcon color={iucnColor} size={22} className="species-icon" />
                  <div>
                    <div className="species-name">{sp.common_name}</div>
                    <div className="species-sci">{sp.scientific_name}</div>
                  </div>
                </div>
                <div className="species-meta">
                  <span className="species-iucn" style={{ color: iucnColor }}>
                    {sp.iucn_status}
                  </span>
                  <span className="species-pop">~{popMid.toLocaleString()}</span>
                </div>
              </button>
            )
          })}
        </div>
        {active && (
          <button className="clear-filter" onClick={() => { onSelect(null); setExpanded(null) }}>
            CLEAR FILTER ×
          </button>
        )}
      </div>

      {/* Detail drawer slides in below panel */}
      {expanded && expandedSpecies && (
        <SpeciesDrawer
          speciesKey={expanded}
          speciesData={expandedSpecies}
          onClose={() => { setExpanded(null); onSelect(null) }}
        />
      )}
    </div>
  )
}
