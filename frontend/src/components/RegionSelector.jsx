import { useState } from 'react'
import './RegionSelector.css'

// Mirrors the bounding boxes used in fetch_noaa_ais.py / fetch_whale_occurrences.py
export const REGIONS = [
  { key: 'full',              label: 'Full View',          bounds: null },
  { key: 'gulf_of_maine',      label: 'Gulf of Maine',       bounds: [[-76.0, 40.0], [-60.0, 50.0]] },
  { key: 'southeast_us',       label: 'Southeast US',        bounds: [[-82.0, 24.0], [-76.0, 32.0]] },
  { key: 'santa_barbara',      label: 'Santa Barbara',       bounds: [[-122.0, 32.0], [-117.0, 35.5]] },
  { key: 'gulf_farallones',    label: 'Gulf of Farallones',  bounds: [[-124.0, 36.5], [-121.0, 38.5]] },
  { key: 'san_pedro_channel',  label: 'San Pedro Channel',   bounds: [[-120.5, 32.5], [-117.0, 34.5]] },
]

const DEFAULT_VIEW = { center: [-70.0, 38.0], zoom: 5.2 }

export default function RegionSelector({ mapRef }) {
  const [active, setActive] = useState('full')

  const handleSelect = (region) => {
    setActive(region.key)
    const map = mapRef.current
    if (!map) return

    if (region.bounds) {
      map.fitBounds(region.bounds, { padding: 60, duration: 1200 })
    } else {
      map.flyTo({ center: DEFAULT_VIEW.center, zoom: DEFAULT_VIEW.zoom, duration: 1200 })
    }
  }

  return (
    <div className="region-selector panel">
      <div className="panel-label">MONITORED REGIONS</div>
      <div className="region-list">
        {REGIONS.map((region) => (
          <button
            key={region.key}
            className={`region-btn ${active === region.key ? 'active' : ''}`}
            onClick={() => handleSelect(region)}
          >
            {region.label}
          </button>
        ))}
      </div>
    </div>
  )
}