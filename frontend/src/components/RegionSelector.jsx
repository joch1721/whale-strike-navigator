import { useState, useRef, useEffect } from 'react'
import './RegionSelector.css'

// Mirrors the bounding boxes used in fetch_noaa_ais.py / fetch_whale_occurrences.py.
// "Southern California" combines the santa_barbara and san_pedro_channel data
// bboxes into one zoom target, since they cover largely overlapping coastline —
// the underlying data pipelines still treat them as separate bboxes.
export const REGIONS = [
  { key: 'full',             label: 'Full View',           bounds: [[-124.0, 24.0], [-60.0, 50.0]] },
  { key: 'gulf_of_maine',    label: 'Gulf of Maine',       bounds: [[-76.0, 40.0], [-60.0, 50.0]] },
  { key: 'southeast_us',     label: 'Southeast US',        bounds: [[-82.0, 24.0], [-76.0, 32.0]] },
  { key: 'socal',            label: 'Southern California', bounds: [[-122.0, 32.0], [-117.0, 35.5]] },
  { key: 'gulf_farallones',  label: 'Gulf of Farallones',  bounds: [[-124.0, 36.5], [-121.0, 38.5]] },
]

export default function RegionSelector({ mapRef }) {
  const [active, setActive] = useState('full')
  const [open, setOpen]     = useState(false)
  const containerRef        = useRef(null)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handleClickOutside = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  const handleSelect = (region) => {
    setActive(region.key)
    setOpen(false)
    const map = mapRef.current
    if (!map) return
    map.fitBounds(region.bounds, { padding: 60, duration: 1200 })
  }

  const activeLabel = REGIONS.find(r => r.key === active)?.label ?? 'Full View'

  return (
    <div className="region-selector" ref={containerRef}>
      <button
        className={`region-trigger panel ${open ? 'open' : ''}`}
        onClick={() => setOpen(o => !o)}
      >
        <span className="region-trigger-label">{activeLabel}</span>
        <span className={`region-chevron ${open ? 'open' : ''}`}>▾</span>
      </button>

      {open && (
        <div className="region-dropdown panel">
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
      )}
    </div>
  )
}