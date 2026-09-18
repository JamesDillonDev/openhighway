import { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup, ZoomControl } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'

const UK_CENTER = [54.5, -3]
const POLL_INTERVAL_MS = 30000
const IMAGE_REFRESH_MS = 5000

// Friendlier labels for known sources - falls back to the raw name for any
// source the frontend doesn't recognise yet.
const SOURCE_LABELS = {
  national_highways: 'National Highways',
  tfl: 'TfL',
  traffic_scotland: 'Traffic Scotland',
  traffic_wales: 'Traffic Wales',
}

// Small colour-coded badge shown next to a camera's name so its source is
// identifiable at a glance - initials rather than each organisation's
// actual (trademarked) logo artwork.
const SOURCE_BADGES = {
  national_highways: { label: 'NH', color: '#00549f' },
  tfl: { label: 'TfL', color: '#dc241f' },
  traffic_scotland: { label: 'TS', color: '#0f7b43' },
  traffic_wales: { label: 'TW', color: '#a3122a' },
}

function SourceBadge({ source }) {
  const badge = SOURCE_BADGES[source]

  const label = badge?.label || source?.slice(0, 2).toUpperCase()
  const color = badge?.color || '#666'

  return (
    <span className="source-badge" style={{ backgroundColor: color }} title={SOURCE_LABELS[source] || source}>
      {label}
    </span>
  )
}

// Traffic-level colour scale: few/no vehicles reads as blue, heavy traffic
// as red. Anything at or above this count is treated as "full red".
const MAX_VEHICLES_FOR_COLOR = 12
const LOW_TRAFFIC_COLOR = [43, 108, 176] // blue
const HIGH_TRAFFIC_COLOR = [220, 38, 38] // red
const UNAVAILABLE_COLOR = '#a0a0a0'

function trafficColor(vehicles) {
  if (vehicles === undefined || vehicles === null) return UNAVAILABLE_COLOR

  const t = Math.min(vehicles / MAX_VEHICLES_FOR_COLOR, 1)

  const rgb = LOW_TRAFFIC_COLOR.map((from, i) =>
    Math.round(from + (HIGH_TRAFFIC_COLOR[i] - from) * t)
  )

  return `rgb(${rgb.join(',')})`
}

function TrafficHistory({ cameraId }) {
  const [points, setPoints] = useState([])

  useEffect(() => {
    let cancelled = false

    const load = () => {
      fetch(`/api/cameras/${cameraId}/history`)
        .then((response) => response.json())
        .then((data) => {
          if (!cancelled) setPoints(data)
        })
        .catch(() => {})
    }

    load()

    const timer = setInterval(load, POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [cameraId])

  if (points.length < 2) {
    return <p className="history-empty">Not enough history yet.</p>
  }

  const width = 260
  const height = 60
  const values = points.map((point) => point.v)
  const max = Math.max(...values, 1)

  const coords = points.map((point, i) => {
    const x = (i / (points.length - 1)) * width
    const y = height - (point.v / max) * height
    return `${x.toFixed(1)},${y.toFixed(1)}`
  })

  return (
    <div className="history">
      <svg viewBox={`0 0 ${width} ${height}`} className="history-graph">
        <polyline points={coords.join(' ')} />
      </svg>
      <div className="history-caption">
        <span>{points[0].t.slice(11, 16)}</span>
        <span>peak {max}</span>
        <span>{points[points.length - 1].t.slice(11, 16)}</span>
      </div>
    </div>
  )
}

function CameraPanel({ camera, onClose }) {
  const [imageExpanded, setImageExpanded] = useState(false)

  useEffect(() => {
    setImageExpanded(false)
  }, [camera?.id])

  // Camera feeds are single static images at a fixed URL - re-fetch on a
  // timer via a cache-busting query param rather than relying on the
  // browser to notice the source has changed.
  const [refreshedAt, setRefreshedAt] = useState(() => Date.now())

  useEffect(() => {
    if (!camera) return

    const timer = setInterval(() => setRefreshedAt(Date.now()), IMAGE_REFRESH_MS)

    return () => clearInterval(timer)
  }, [camera?.id])

  if (!camera) return null

  const imageSrc = camera.image_url
    ? `${camera.image_url}${camera.image_url.includes('?') ? '&' : '?'}t=${refreshedAt}`
    : camera.image_url

  return (
    <aside className="panel">
      <button className="panel-close" onClick={onClose} aria-label="Close">
        &times;
      </button>

      <img
        className="panel-image"
        src={imageSrc}
        alt={camera.name || `Camera ${camera.id}`}
        onClick={() => setImageExpanded(true)}
      />

      <h2 className="panel-title">
        {camera.name || `Camera ${camera.id}`}
        <SourceBadge source={camera.source} />
      </h2>

      <dl>
        <dt>Road</dt>
        <dd>{camera.road || '—'}</dd>

        <dt>Direction</dt>
        <dd>{camera.direction || '—'}</dd>

        <dt>Source</dt>
        <dd>{camera.source}</dd>

        <dt>Vehicles</dt>
        <dd>{camera.vehicles ?? '—'}</dd>
      </dl>

      <h3>Traffic history</h3>
      <TrafficHistory cameraId={camera.id} />

      {imageExpanded && (
        <div className="image-lightbox" onClick={() => setImageExpanded(false)}>
          <button
            className="lightbox-close"
            onClick={() => setImageExpanded(false)}
            aria-label="Close"
          >
            &times;
          </button>
          <img src={imageSrc} alt={camera.name || `Camera ${camera.id}`} />
        </div>
      )}
    </aside>
  )
}

function App() {
  const [cameras, setCameras] = useState([])
  const [selected, setSelected] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [hiddenSources, setHiddenSources] = useState(() => new Set())

  const sources = useMemo(
    () => [...new Set(cameras.map((camera) => camera.source))].sort(),
    [cameras]
  )

  const visibleCameras = useMemo(
    () => cameras.filter((camera) => !hiddenSources.has(camera.source)),
    [cameras, hiddenSources]
  )

  const toggleSource = (source) => {
    setHiddenSources((prev) => {
      const next = new Set(prev)

      if (next.has(source)) {
        next.delete(source)
      } else {
        next.add(source)
      }

      return next
    })
  }

  const loadCameras = () => {
    setRefreshing(true)

    return fetch('/api/cameras')
      .then((response) => response.json())
      .then(setCameras)
      .catch(() => {})
      .finally(() => setRefreshing(false))
  }

  useEffect(() => {
    loadCameras()

    const timer = setInterval(loadCameras, POLL_INTERVAL_MS)

    return () => clearInterval(timer)
  }, [])

  // Keep the open panel's data (e.g. vehicle count) fresh as polls come in
  useEffect(() => {
    if (!selected) return

    const updated = cameras.find((camera) => camera.id === selected.id)

    if (updated) setSelected(updated)
  }, [cameras])

  return (
    <div className="app">
      <button
        className="refresh-button"
        onClick={loadCameras}
        disabled={refreshing}
      >
        {refreshing ? 'Refreshing…' : 'Refresh'}
      </button>

      {sources.length > 0 && (
        <div className="source-filter">
          {sources.map((source) => (
            <label key={source} className="source-filter-item">
              <input
                type="checkbox"
                checked={!hiddenSources.has(source)}
                onChange={() => toggleSource(source)}
              />
              {SOURCE_LABELS[source] || source}
            </label>
          ))}
        </div>
      )}

      <MapContainer
        center={UK_CENTER}
        zoom={6}
        zoomControl={false}
        className="map"
      >
        <ZoomControl position="topright" />
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {visibleCameras.map((camera) => (
          <CircleMarker
            key={camera.id}
            center={[camera.latitude, camera.longitude]}
            radius={9}
            weight={2}
            color="#2b2b2b"
            fillColor={trafficColor(camera.vehicles)}
            fillOpacity={0.9}
            eventHandlers={{
              click: () => setSelected(camera),
            }}
          >
            <Popup>{camera.name || camera.id}</Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      <CameraPanel camera={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

export default App

