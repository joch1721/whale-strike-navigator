import { useState, useEffect, useRef, useCallback } from 'react'
import mapboxgl from 'mapbox-gl'
import axios from 'axios'
import 'mapbox-gl/dist/mapbox-gl.css'
import './App.css'
import SpeciesPanel from './components/SpeciesPanel'
import RiskLegend from './components/RiskLegend'
import MonthScrubber from './components/MonthScrubber'
import StatsBar from './components/StatsBar'
import WhaleIcon from './components/WhaleIcon'

mapboxgl.accessToken = import.meta.env.VITE_MAPBOX_TOKEN
const API = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const TIER_COLORS = {
  critical: '#ff2d55',
  high:     '#ff9f0a',
  medium:   '#30d158',
  low:      '#0a84ff',
}

// Live vessel refresh interval (ms)
const LIVE_REFRESH_MS = 60_000

export default function App() {
  const mapContainer = useRef(null)
  const map          = useRef(null)
  const liveTimer    = useRef(null)

  const [month, setMonth]                 = useState(3)
  const [activeSpecies, setActiveSpecies] = useState(null)
  const [riskSummary, setRiskSummary]     = useState(null)
  const [loading, setLoading]             = useState(true)
  const [dataReady, setDataReady]         = useState(false)
  const [hoveredCell, setHoveredCell]     = useState(null)
  const [liveStatus, setLiveStatus]       = useState({ count: 0, date: null })
  const [liveRiskCount, setLiveRiskCount] = useState(0)
  const [showLive, setShowLive]           = useState(true)

  // ── Init map ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (map.current) return

    map.current = new mapboxgl.Map({
      container: mapContainer.current,
      style: 'mapbox://styles/mapbox/navigation-night-v1',
      center: [-70.0, 38.0],
      zoom: 5.2,
      minZoom: 3,
      maxZoom: 12,
      projection: 'mercator',
    })

    map.current.addControl(new mapboxgl.NavigationControl(), 'top-right')
    map.current.addControl(new mapboxgl.ScaleControl({ unit: 'nautical' }), 'bottom-right')

    map.current.on('load', () => {
      // Risk grid
      map.current.addSource('risk-grid', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.current.addLayer({
        id: 'risk-heat',
        type: 'fill',
        source: 'risk-grid',
        paint: {
          'fill-color': [
            'match', ['get', 'risk_tier'],
            'critical', TIER_COLORS.critical,
            'high',     TIER_COLORS.high,
            'medium',   TIER_COLORS.medium,
            'low',      TIER_COLORS.low,
            '#0a84ff',
          ],
          'fill-opacity': [
            'interpolate', ['linear'], ['get', 'risk_score'],
            0, 0.0, 8.5, 0.25, 20.0, 0.55, 35.0, 0.80, 49.5, 0.95,
          ],
        },
      })
      map.current.addLayer({
        id: 'risk-border',
        type: 'line',
        source: 'risk-grid',
        paint: { 'line-color': '#ffffff', 'line-opacity': 0.05, 'line-width': 0.3 },
      })

      // SMA zones
      map.current.addSource('sma-zones', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.current.addLayer({
        id: 'sma-fill',
        type: 'fill',
        source: 'sma-zones',
        paint: { 'fill-color': '#5ac8fa', 'fill-opacity': 0.08 },
      })
      map.current.addLayer({
        id: 'sma-border',
        type: 'line',
        source: 'sma-zones',
        paint: {
          'line-color': '#5ac8fa', 'line-opacity': 0.6,
          'line-width': 1.5, 'line-dasharray': [4, 2],
        },
      })

      // Strike incidents
      map.current.addSource('incidents', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })
      map.current.addLayer({
        id: 'incidents-layer',
        type: 'circle',
        source: 'incidents',
        paint: {
          'circle-radius': 5,
          'circle-color': '#ff375f',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1.5,
          'circle-opacity': 0.85,
        },
      })

      // Live vessels source
      map.current.addSource('live-vessels', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })

      // Live vessel dots — color by speed tier
      map.current.addLayer({
        id: 'live-vessels-layer',
        type: 'circle',
        source: 'live-vessels',
        paint: {
          'circle-radius': [
            'interpolate', ['linear'], ['zoom'],
            4, 2, 8, 4, 12, 6,
          ],
          'circle-color': [
            'match', ['get', 'speed_tier'],
            'fast',    '#ff9f0a',
            'medium',  '#ffd60a',
            'slow',    '#30d158',
            'unknown', '#5ac8fa',
            '#5ac8fa',
          ],
          'circle-opacity': 0.75,
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 0.5,
        },
      })

      // Live risk grid source
      map.current.addSource('live-risk', {
        type: 'geojson',
        data: { type: 'FeatureCollection', features: [] },
      })

      // Live risk fill — semi-transparent overlay on top of historical
      map.current.addLayer({
        id: 'live-risk-fill',
        type: 'fill',
        source: 'live-risk',
        paint: {
          'fill-color': [
            'match', ['get', 'risk_tier'],
            'critical', '#ff2d55',
            'high',     '#ff9f0a',
            'medium',   '#30d158',
            '#0a84ff',
          ],
          'fill-opacity': 0.35,
        },
      })

      // Live risk border — pulsing outline to signal real-time data
      map.current.addLayer({
        id: 'live-risk-border',
        type: 'line',
        source: 'live-risk',
        paint: {
          'line-color': '#5ac8fa',
          'line-width': 1.5,
          'line-opacity': 0.9,
        },
      })

      // Vessel hover popup
      const vesselPopup = new mapboxgl.Popup({
        closeButton: false,
        closeOnClick: false,
        className: 'vessel-popup',
      })

      map.current.on('mouseenter', 'live-vessels-layer', (e) => {
        map.current.getCanvas().style.cursor = 'pointer'
        const props = e.features[0].properties
        const coords = e.features[0].geometry.coordinates
        const speed = props.speed_knots != null ? `${parseFloat(props.speed_knots).toFixed(1)} kn` : 'speed unknown'
        vesselPopup
          .setLngLat(coords)
          .setHTML(`
            <div class="vpopup-name">${props.vessel_name}</div>
            <div class="vpopup-mmsi">MMSI ${props.mmsi}</div>
            <div class="vpopup-speed">${speed}</div>
          `)
          .addTo(map.current)
      })

      map.current.on('mouseleave', 'live-vessels-layer', () => {
        map.current.getCanvas().style.cursor = ''
        vesselPopup.remove()
      })

      // Incident click popup
      const incidentPopup = new mapboxgl.Popup({
        closeButton: true,
        closeOnClick: true,
        className: 'vessel-popup',
      })

      map.current.on('click', 'incidents-layer', (e) => {
        const props = e.features[0].properties
        const coords = e.features[0].geometry.coordinates
        const speed = props.vessel_speed_knots
          ? `${parseFloat(props.vessel_speed_knots).toFixed(1)} kn`
          : 'unknown speed'
        const outcome = props.outcome ? props.outcome.toUpperCase() : 'UNKNOWN'
        const outcomeColor =
          props.outcome === 'lethal'   ? '#ff2d55' :
          props.outcome === 'injurious'? '#ff9f0a' : '#7eb8d4'
        incidentPopup
          .setLngLat(coords)
          .setHTML(`
            <div class="vpopup-name">${props.species_code || 'Unknown'} — Strike Incident</div>
            <div class="vpopup-mmsi">${props.year || '—'} · ${props.vessel_type || 'Unknown vessel'} · ${speed}</div>
            <div class="vpopup-speed" style="color:${outcomeColor}">${outcome}</div>
            <div class="vpopup-mmsi">${props.source || ''}</div>
          `)
          .addTo(map.current)
      })

      map.current.on('mouseenter', 'incidents-layer', () => {
        map.current.getCanvas().style.cursor = 'pointer'
      })
      map.current.on('mouseleave', 'incidents-layer', () => {
        map.current.getCanvas().style.cursor = ''
      })

      // Risk cell hover
      map.current.on('mousemove', 'risk-heat', (e) => {
        if (e.features.length > 0) {
          const props = e.features[0].properties
          setHoveredCell({
            score:   props.risk_score,
            tier:    props.risk_tier,
            species: props.species_present,
            lat:     props.lat,
            lon:     props.lon,
          })
          map.current.getCanvas().style.cursor = 'crosshair'
        }
      })
      map.current.on('mouseleave', 'risk-heat', () => {
        setHoveredCell(null)
        map.current.getCanvas().style.cursor = ''
      })

      setDataReady(true)
    })
  }, [])

  // ── Risk summary ──────────────────────────────────────────────────────────
  useEffect(() => {
    axios.get(`${API}/risk/summary`)
      .then(r => setRiskSummary(r.data))
      .catch(console.error)
  }, [])

  // ── Load live vessels ─────────────────────────────────────────────────────
  const loadLiveVessels = useCallback(async () => {
    if (!dataReady) return
    try {
      const { data } = await axios.get(`${API}/vessels/live`)
      if (map.current.getSource('live-vessels')) {
        map.current.getSource('live-vessels').setData(data)
        map.current.setLayoutProperty(
          'live-vessels-layer', 'visibility', showLive ? 'visible' : 'none'
        )
      }
      setLiveStatus({ count: data.vessel_count, date: data.data_date })
    } catch (err) {
      console.error('Live vessel load error:', err)
    }
  }, [dataReady, showLive])

  useEffect(() => {
    loadLiveVessels()
    clearInterval(liveTimer.current)
    liveTimer.current = setInterval(loadLiveVessels, LIVE_REFRESH_MS)
    return () => clearInterval(liveTimer.current)
  }, [loadLiveVessels])

  // ── Load live risk grid ──────────────────────────────────────────────────
  const loadLiveRisk = useCallback(async () => {
    if (!dataReady) return
    try {
      const { data } = await axios.get(`${API}/risk/live`)
      if (data.status !== 'ok' || !data.cells?.length) return

      const features = data.cells.map(c => ({
        type: 'Feature',
        geometry: {
          type: 'Polygon',
          coordinates: [[
            [c.lon - 0.05, c.lat - 0.05],
            [c.lon + 0.05, c.lat - 0.05],
            [c.lon + 0.05, c.lat + 0.05],
            [c.lon - 0.05, c.lat + 0.05],
            [c.lon - 0.05, c.lat - 0.05],
          ]],
        },
        properties: c,
      }))

      if (map.current.getSource('live-risk')) {
        map.current.getSource('live-risk').setData({
          type: 'FeatureCollection', features,
        })
        const visibility = showLive ? 'visible' : 'none'
        map.current.setLayoutProperty('live-risk-fill',   'visibility', visibility)
        map.current.setLayoutProperty('live-risk-border', 'visibility', visibility)
      }
      setLiveRiskCount(data.cell_count)
    } catch (err) {
      console.error('Live risk load error:', err)
    }
  }, [dataReady, showLive])

  useEffect(() => {
    loadLiveRisk()
  }, [loadLiveRisk])

  // Toggle live layer visibility
  useEffect(() => {
    if (!dataReady) return
    const vis = showLive ? 'visible' : 'none'
    if (map.current.getLayer('live-vessels-layer'))
      map.current.setLayoutProperty('live-vessels-layer', 'visibility', vis)
    if (map.current.getLayer('live-risk-fill'))
      map.current.setLayoutProperty('live-risk-fill', 'visibility', vis)
    if (map.current.getLayer('live-risk-border'))
      map.current.setLayoutProperty('live-risk-border', 'visibility', vis)
  }, [showLive, dataReady])

  // ── Load risk + zones + incidents ─────────────────────────────────────────
  const loadLayers = useCallback(async () => {
    if (!dataReady) return
    setLoading(true)
    try {
      const params = { month, min_score: 0 }
      if (activeSpecies) params.species = activeSpecies
      const { data: riskData } = await axios.get(`${API}/risk`, { params })
      const riskFeatures = riskData.cells
        .filter(c => c.risk_score > 0)
        .map(c => ({
          type: 'Feature',
          geometry: {
            type: 'Polygon',
            coordinates: [[
              [c.lon - 0.05, c.lat - 0.05],
              [c.lon + 0.05, c.lat - 0.05],
              [c.lon + 0.05, c.lat + 0.05],
              [c.lon - 0.05, c.lat + 0.05],
              [c.lon - 0.05, c.lat - 0.05],
            ]],
          },
          properties: c,
        }))
      map.current.getSource('risk-grid').setData({
        type: 'FeatureCollection', features: riskFeatures,
      })

      const { data: zoneData } = await axios.get(`${API}/whale-zones`, { params: { month } })
      map.current.getSource('sma-zones').setData(zoneData)

      const { data: incidentData } = await axios.get(`${API}/incidents`)
      const incidentFeatures = incidentData.incidents.map(i => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [i.lon, i.lat] },
        properties: i,
      }))
      map.current.getSource('incidents').setData({
        type: 'FeatureCollection', features: incidentFeatures,
      })
    } catch (err) {
      console.error('Layer load error:', err)
    } finally {
      setLoading(false)
    }
  }, [dataReady, month, activeSpecies])

  useEffect(() => { loadLayers() }, [loadLayers])

  const monthSummary = riskSummary?.months?.find(m => m.month === month)

  return (
    <div className="app">
      <div ref={mapContainer} className="map-container" />

      <header className="top-bar">
        <div className="wordmark">
          <WhaleIcon color="#5ac8fa" size={30} className="wordmark-icon" />
          <div>
            <div className="wordmark-title">WHALE STRIKE NAVIGATOR</div>
            <div className="wordmark-sub">Ship–Whale Collision Risk · North Atlantic</div>
          </div>
        </div>
        <div className="top-bar-right">
          <StatsBar summary={monthSummary} month={month} loading={loading} />
          <button
            className={`live-badge ${showLive ? 'active' : 'inactive'}`}
            onClick={() => setShowLive(v => !v)}
            title={showLive ? 'Hide live vessels' : 'Show live vessels'}
          >
            <span className="live-dot" />
            LIVE · {liveStatus.count} vessels · {liveRiskCount} risk cells
          </button>
        </div>
      </header>

      <div className="scrubber-container">
        <MonthScrubber
  month={month}
  onChange={setMonth}
  dataMonths={riskSummary?.months?.map(m => m.month).sort((a, b) => a - b) ?? [1]}
/>
      </div>

      <div className="species-container">
        <SpeciesPanel active={activeSpecies} onSelect={setActiveSpecies} />
      </div>

      <div className="legend-container">
        <RiskLegend showLive={showLive} />
      </div>

      {hoveredCell && (
        <div className="hover-tooltip">
          <div className="tooltip-score" style={{ color: TIER_COLORS[hoveredCell.tier] }}>
            {hoveredCell.score.toFixed(1)}
          </div>
          <div className="tooltip-tier">{hoveredCell.tier.toUpperCase()}</div>
          {hoveredCell.species && (
            <div className="tooltip-species">{hoveredCell.species.replace(/,/g, ' · ')}</div>
          )}
          <div className="tooltip-coords">
            {hoveredCell.lat.toFixed(2)}°N {Math.abs(hoveredCell.lon).toFixed(2)}°W
          </div>
        </div>
      )}

      {loading && <div className="loading-bar" />}
    </div>
  )
}
