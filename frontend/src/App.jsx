import { useEffect, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Popup } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import './App.css'

const UK_CENTER = [54.5, -3]
const POLL_INTERVAL_MS = 30000

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
  if (!camera) return null

  return (
    <aside className="panel">
      <button className="panel-close" onClick={onClose} aria-label="Close">
        &times;
      </button>

      <img
        className="panel-image"
        src={camera.image_url}
        alt={camera.description || `Camera ${camera.id}`}
      />

      <h2>{camera.description || `Camera ${camera.id}`}</h2>

      <dl>
        <dt>Road</dt>
        <dd>{camera.national_highways_link?.roadname || '—'}</dd>

        <dt>Carriageway</dt>
        <dd>{camera.carriageway || camera.national_highways_link?.carriageway || '—'}</dd>

        <dt>Status</dt>
        <dd>{camera.available ? 'Available' : 'Unavailable'}</dd>

        <dt>Vehicles</dt>
        <dd>{camera.vehicles ?? '—'}</dd>
      </dl>

      <h3>Traffic history</h3>
      <TrafficHistory cameraId={camera.id} />
    </aside>
  )
}

function App() {
  const [cameras, setCameras] = useState([])
  const [selected, setSelected] = useState(null)
  const [refreshing, setRefreshing] = useState(false)

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

      <MapContainer
        center={UK_CENTER}
        zoom={6}
        className="map"
      >
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />

        {cameras.map((camera) => (
          <CircleMarker
            key={camera.id}
            center={[camera.latitude, camera.longitude]}
            radius={9}
            weight={2}
            color="#2b2b2b"
            fillColor={camera.available ? trafficColor(camera.vehicles) : UNAVAILABLE_COLOR}
            fillOpacity={0.9}
            eventHandlers={{
              click: () => setSelected(camera),
            }}
          >
            <Popup>{camera.description || camera.id}</Popup>
          </CircleMarker>
        ))}
      </MapContainer>

      <CameraPanel camera={selected} onClose={() => setSelected(null)} />
    </div>
  )
}

export default App

