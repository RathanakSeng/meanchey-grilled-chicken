import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef } from 'react'

export interface MapPoint {
  latitude: number
  longitude: number
}

interface MapViewProps {
  /** The workplace pin and its check-in radius (metres). */
  workplace: (MapPoint & { radius: number }) | null
  /** The person's position and its accuracy circle (metres). */
  user?: (MapPoint & { accuracy: number }) | null
  /** Tap the map to place the workplace pin (Settings → Workplace). */
  onPick?(point: MapPoint): void
  /** Where to look when there is nothing to show yet. */
  fallbackCenter?: MapPoint
  className?: string
}

const BRAND = '#ea580c'
const USER = '#0284c7'
// Phnom Penh, when nothing is known yet.
const DEFAULT_CENTER: MapPoint = { latitude: 11.5564, longitude: 104.9282 }

/**
 * OpenStreetMap through Leaflet: the workplace pin with its radius, the person's position with its
 * accuracy. Pins are circle markers (no image assets to bundle). Loaded only by the lazy
 * attendance chunks.
 */
export function MapView({ workplace, user, onPick, fallbackCenter, className }: MapViewProps) {
  const element = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layers = useRef<L.LayerGroup | null>(null)
  const pick = useRef(onPick)
  pick.current = onPick
  const fitted = useRef(false)

  useEffect(() => {
    if (!element.current) return
    const m = L.map(element.current, { zoomControl: true, attributionControl: true })
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(m)
    const center = fallbackCenter ?? DEFAULT_CENTER
    m.setView([center.latitude, center.longitude], 15)
    m.on('click', (e: L.LeafletMouseEvent) => pick.current?.({ latitude: e.latlng.lat, longitude: e.latlng.lng }))
    layers.current = L.layerGroup().addTo(m)
    map.current = m
    // A new map (also React's dev double mount) starts unfitted.
    fitted.current = false
    // The container may get its size after mount (sheets, tabs).
    const resize = new ResizeObserver(() => m.invalidateSize())
    resize.observe(element.current)
    return () => {
      resize.disconnect()
      m.remove()
      map.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    const m = map.current
    const group = layers.current
    if (!m || !group) return
    group.clearLayers()
    const bounds: L.LatLngBounds[] = []
    if (workplace) {
      const at = L.latLng(workplace.latitude, workplace.longitude)
      const circle = L.circle(at, {
        radius: workplace.radius,
        color: BRAND,
        weight: 2,
        fillColor: BRAND,
        fillOpacity: 0.12,
      }).addTo(group)
      L.circleMarker(at, { radius: 8, color: '#fff', weight: 3, fillColor: BRAND, fillOpacity: 1 }).addTo(group)
      bounds.push(circle.getBounds())
    }
    if (user) {
      const at = L.latLng(user.latitude, user.longitude)
      const circle = L.circle(at, {
        radius: Math.max(user.accuracy, 1),
        color: USER,
        weight: 1,
        fillColor: USER,
        fillOpacity: 0.15,
      }).addTo(group)
      L.circleMarker(at, { radius: 7, color: '#fff', weight: 3, fillColor: USER, fillOpacity: 1 }).addTo(group)
      bounds.push(circle.getBounds())
    }
    if (bounds.length && (!fitted.current || !onPick)) {
      const all = bounds.reduce((acc, b) => acc.extend(b), L.latLngBounds(bounds[0].getSouthWest(), bounds[0].getNorthEast()))
      m.fitBounds(all, { padding: [24, 24], maxZoom: 18 })
      // The picker keeps the user's zoom after the first fit.
      fitted.current = true
    }
  }, [workplace, user, onPick])

  // `isolate`: Leaflet's panes use z-index 400+; keep them under the sticky header and bottom nav.
  return (
    <div
      ref={element}
      className={className ?? 'isolate z-0 h-64 w-full overflow-hidden rounded-xl ring-1 ring-stone-200'}
    />
  )
}
