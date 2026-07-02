import { useState, useEffect, useRef } from 'react'
import './MonthScrubber.css'

const MONTHS = [
  'JAN','FEB','MAR','APR','MAY','JUN',
  'JUL','AUG','SEP','OCT','NOV','DEC'
]

const SMA_ACTIVE = [11, 12, 1, 2, 3, 4]

const SPEEDS = [
  { label: '0.5×', ms: 2000 },
  { label: '1×',   ms: 1000 },
  { label: '2×',   ms: 500  },
]

export default function MonthScrubber({ month, onChange, dataMonths }) {
  const safeMonths = dataMonths?.length ? dataMonths : [month]

  const [playing, setPlaying]   = useState(false)
  const [speedIdx, setSpeedIdx] = useState(1)
  const intervalRef             = useRef(null)

  useEffect(() => {
    if (!playing) {
      clearInterval(intervalRef.current)
      return
    }

    intervalRef.current = setInterval(() => {
      onChange(prev => {
        const currentIdx = safeMonths.indexOf(prev)
        const nextIdx    = (currentIdx + 1) % safeMonths.length
        // Stop at end of data months
        if (nextIdx === 0) {
          setPlaying(false)
          return safeMonths[0]
        }
        return safeMonths[nextIdx]
      })
    }, SPEEDS[speedIdx].ms)

    return () => clearInterval(intervalRef.current)
  }, [playing, speedIdx, onChange, safeMonths])

  const togglePlay = () => {
    if (!playing && !safeMonths.includes(month)) {
      onChange(safeMonths[0])
    }
    setPlaying(p => !p)
  }

  const cycleSpeed = () => {
    setSpeedIdx(i => (i + 1) % SPEEDS.length)
  }

  return (
    <div className="scrubber panel">
      <div className="scrubber-top">
        <div className="scrubber-label panel-label">
          SEASONAL PLAYBACK — {MONTHS[month - 1]} 2024
        </div>
        <div className="scrubber-controls">
          <button
            className={`play-btn ${playing ? 'playing' : ''}`}
            onClick={togglePlay}
            title={playing ? 'Pause' : 'Play'}
          >
            {playing ? '⏸' : '▶'}
          </button>
          <button
            className="speed-btn"
            onClick={cycleSpeed}
            title="Change speed"
          >
            {SPEEDS[speedIdx].label}
          </button>
        </div>
      </div>
      <div className="scrubber-months">
        {MONTHS.map((label, i) => {
          const m        = i + 1
          const isActive = m === month
          const hasSMA   = SMA_ACTIVE.includes(m)
          const hasData  = safeMonths.includes(m)
          return (
            <button
              key={m}
              className={`month-btn ${isActive ? 'active' : ''} ${!hasData ? 'no-data' : ''}`}
              onClick={() => { setPlaying(false); onChange(m) }}
              title={!hasData ? 'No AIS data for this month' : undefined}
            >
              {label}
              {hasSMA && <span className="sma-dot" title="SMA zone active" />}
              {isActive && playing && <span className="playing-dot" />}
            </button>
          )
        })}
      </div>
      {playing && (
        <div className="playback-bar">
          <div
            className="playback-progress"
            style={{
              width: `${(safeMonths.indexOf(month) / (safeMonths.length - 1)) * 100}%`
            }}
          />
        </div>
      )}
    </div>
  )
}
