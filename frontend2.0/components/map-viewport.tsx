"use client"

import { useEffect, useRef } from "react"
import mapboxgl from "mapbox-gl"
import "mapbox-gl/dist/mapbox-gl.css"
import { ACTIVITY_LABELS, type ActivityType, type Alert, type Region } from "@/lib/sentinel-data"
import type { RegionFilter } from "@/components/region-select"

interface Props {
  alerts: Alert[]
  region: RegionFilter
  selected: Alert | null
  onSelect: (alert: Alert) => void
  onClosePopup: () => void
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000"

const REGION_VIEW: Record<RegionFilter, { center: [number, number]; zoom: number }> = {
  all:    { center: [-72.0, -20.0], zoom: 4 },
  peru:   { center: [-74.5,  -5.0], zoom: 6 },
  biobio: { center: [-72.0, -37.5], zoom: 7 },
}

const ACTIVITY_COLORS: Record<ActivityType, string> = {
  mineria:   "#f97316",
  incendios: "#eab308",
}

const METERS_PER_PIXEL_AT_ZOOM: mapboxgl.ExpressionSpecification = [
  "interpolate", ["exponential", 2], ["zoom"],
  0,  ["/", ["get", "radius_m"], 156543],
  22, ["/", ["get", "radius_m"], 0.037],
]

function toFireGeoJSON(alerts: Alert[]): GeoJSON.FeatureCollection {
  const fires = alerts.filter((a) => a.type === "incendios" && a.tier === "confirmed")
  return {
    type: "FeatureCollection",
    features: fires.map((a) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [a.lon, a.lat] },
      properties: {
        radius_m: (((a as unknown as Record<string, unknown>).threat_radius_km as number | undefined) ?? 2) * 1000,
      },
    })),
  }
}

function toGeoJSON(alerts: Alert[]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: alerts.map((a) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [a.lon, a.lat] },
      properties: {
        id: a.id,
        color: ACTIVITY_COLORS[a.type],
        type: a.type,
        severity: a.severity,
        confidence: a.confidence,
        verdict: a.verdict,
        date: a.date,
        area_ha: a.area_ha ?? null,
        wdpaName: a.wdpaName ?? null,
      },
    })),
  }
}

function fetchThumbnail(thumbId: string, lat: unknown, lon: unknown, date: unknown, type: unknown) {
  setTimeout(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/alert/thumbnail?lat=${lat}&lon=${lon}&date=${date}&actividad=${type}`
      )
      const data = (await res.json()) as { url?: string | null }
      const img = document.getElementById(thumbId) as HTMLImageElement | null
      if (img) {
        if (data.url) img.src = data.url
        else img.style.display = "none"
      }
    } catch {
      const img = document.getElementById(thumbId) as HTMLImageElement | null
      if (img) img.style.display = "none"
    }
  }, 100)
}

function buildFirePopupHTML(p: Record<string, unknown>): string {
  const id = String(p.id)
  const thumbId = `sat-thumb-${id}`

  const tier = String(p.tier ?? "")
  const tierLabel = tier === "confirmed" ? "CONFIRMADO" : tier === "preliminary" ? "PRELIMINAR" : "SIN CONFIRMAR"
  const tierColor = tier === "confirmed" ? "#ef4444" : tier === "preliminary" ? "#f97316" : "#6b7280"

  const iScore = p.intentionality_score != null ? Number(p.intentionality_score) : null
  const iLevel = p.intentionality_level ? String(p.intentionality_level) : null
  const iColor = iLevel === "ALTO" || iLevel === "EXTREMO" ? "#ef4444" : iLevel === "MEDIO" ? "#f97316" : "#22c55e"

  const fwi = p.fire_weather_index ? String(p.fire_weather_index) : null
  const fwiColor = fwi === "ALTO" || fwi === "EXTREMO" ? "#ef4444" : fwi === "MEDIO" ? "#f97316" : "#22c55e"

  const legalRisk = p.legal_risk_score != null ? Number(p.legal_risk_score) : null

  fetchThumbnail(thumbId, p.lat, p.lon, p.date, "incendios")

  return `
    <div style="font-family:ui-monospace,monospace;font-size:12.5px;line-height:1.65;color:#c9d1d9;background:#161b22;border-radius:8px;min-width:380px;max-width:460px;border:1px solid #30363d;overflow:hidden;max-height:600px;overflow-y:auto">
      <div style="background:#1c0d0d;padding:12px 16px;border-bottom:1px solid #30363d">
        <div style="color:#ef4444;font-weight:700;font-size:14px;letter-spacing:0.04em">🔥 ALERTA INCENDIO</div>
        <div style="color:#6e7681;font-size:11px;margin-top:3px;letter-spacing:0.06em">${id}</div>
      </div>
      <div style="padding:10px 16px;border-bottom:1px solid #21262d">
        <table style="border-collapse:collapse;width:100%">
          <tr><td style="color:#8b949e;padding-right:14px;padding-bottom:4px;white-space:nowrap">Estado</td><td style="color:${tierColor};font-weight:600">${tierLabel}</td></tr>
          ${p.max_frp != null ? `<tr><td style="color:#8b949e;padding-right:14px;padding-bottom:4px;white-space:nowrap">FRP máx</td><td>${Number(p.max_frp).toFixed(1)} MW</td></tr>` : ""}
          ${p.duration_hours != null ? `<tr><td style="color:#8b949e;padding-right:14px;padding-bottom:4px;white-space:nowrap">Activo</td><td>${Number(p.duration_hours).toFixed(1)} horas</td></tr>` : ""}
          ${p.detection_count != null ? `<tr><td style="color:#8b949e;padding-right:14px;white-space:nowrap">Detecciones</td><td>${p.detection_count}</td></tr>` : ""}
        </table>
      </div>
      ${p.spread_summary || fwi ? `
      <div style="padding:10px 16px;border-bottom:1px solid #21262d">
        <div style="color:#ef4444;font-size:10.5px;font-weight:700;letter-spacing:0.08em;margin-bottom:6px">PROPAGACIÓN</div>
        ${p.spread_summary ? `<div style="color:#c9d1d9;margin-bottom:5px">${String(p.spread_summary)}</div>` : ""}
        ${fwi ? `<div>FWI: <span style="color:${fwiColor};font-weight:600">${fwi}</span></div>` : ""}
      </div>` : ""}
      ${iScore != null || iLevel ? `
      <div style="padding:10px 16px;border-bottom:1px solid #21262d">
        <div style="color:#ef4444;font-size:10.5px;font-weight:700;letter-spacing:0.08em;margin-bottom:6px">INTENCIONALIDAD</div>
        <div>Score: <span style="font-weight:600">${iScore ?? "—"}/100</span>${iLevel ? ` — <span style="color:${iColor};font-weight:600">${iLevel}</span>` : ""}</div>
      </div>` : ""}
      ${legalRisk != null || p.wdpaName ? `
      <div style="padding:10px 16px;border-bottom:1px solid #21262d">
        <div style="color:#ef4444;font-size:10.5px;font-weight:700;letter-spacing:0.08em;margin-bottom:6px">CONTEXTO LEGAL</div>
        ${legalRisk != null ? `<div>Riesgo: <span style="font-weight:600">${legalRisk}/100</span></div>` : ""}
        ${p.wdpaName ? `<div style="color:#f85149;margin-top:4px">WDPA: ${String(p.wdpaName)}</div>` : ""}
      </div>` : ""}
      <div style="padding:10px 16px">
        <img id="${thumbId}"
          src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
          style="width:100%;height:256px;object-fit:cover;border-radius:4px;background:#0d1117;display:block"
          alt="Imagen satelital"
        />
      </div>
    </div>`
}

function buildPopupHTML(p: Record<string, unknown>): string {
  if (p.type === "incendios") return buildFirePopupHTML(p)

  const color = ACTIVITY_COLORS[p.type as ActivityType] ?? "#fff"
  const label = ACTIVITY_LABELS[p.type as ActivityType] ?? String(p.type)
  const thumbId = `sat-thumb-${String(p.id)}`
  const rows: [string, string][] = [
    ["Severidad", `<span style="color:${color}">${p.severity}</span>`],
    ["Confianza", `${p.confidence}%`],
    ["Veredicto", String(p.verdict)],
    ["Fecha", String(p.date)],
    ...(p.area_ha != null ? [["Área", `${Number(p.area_ha).toFixed(1)} ha`] as [string, string]] : []),
    ...(p.wdpaName ? [["WDPA", `<span style="color:#f85149">${p.wdpaName}</span>`] as [string, string]] : []),
  ]

  fetchThumbnail(thumbId, p.lat, p.lon, p.date, p.type)

  return `
    <div style="font-family:ui-monospace,monospace;font-size:12.5px;line-height:1.65;
                color:#c9d1d9;background:#161b22;padding:12px 16px;
                border-radius:8px;min-width:380px;max-width:460px;max-height:600px;overflow-y:auto;border:1px solid #30363d">
      <div style="color:${color};font-weight:700;font-size:14px;margin-bottom:8px">${label}</div>
      <table style="border-collapse:collapse;width:100%">
        ${rows.map(([k, v]) => `
          <tr>
            <td style="color:#8b949e;padding-right:14px;padding-bottom:4px;white-space:nowrap">${k}</td>
            <td>${v}</td>
          </tr>`).join("")}
      </table>
      <img
        id="${thumbId}"
        src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
        style="width:100%;height:256px;object-fit:cover;border-radius:4px;background:#1a1a2e;margin-top:10px;display:block"
        alt="Imagen satelital"
      />
    </div>`
}

const PULSE_STYLE_ID = "sw-fire-pulse-style"

function injectPulseCSS() {
  if (document.getElementById(PULSE_STYLE_ID)) return
  const style = document.createElement("style")
  style.id = PULSE_STYLE_ID
  style.textContent = `
    @keyframes sw-fire-pulse {
      0%   { transform: scale(1); opacity: 0.8; }
      70%  { transform: scale(2.8); opacity: 0; }
      100% { transform: scale(2.8); opacity: 0; }
    }
    .sw-fire-marker { position: relative; width: 14px; height: 14px; cursor: pointer; }
    .sw-fire-marker::before {
      content: '';
      position: absolute;
      inset: 0;
      border-radius: 50%;
      background: rgba(239,68,68,0.55);
      animation: sw-fire-pulse 2s ease-out infinite;
    }
    .sw-fire-marker::after {
      content: '';
      position: absolute;
      inset: 3px;
      border-radius: 50%;
      background: #ef4444;
      border: 1.5px solid rgba(255,255,255,0.9);
    }
  `
  document.head.appendChild(style)
}

export function MapViewport({ alerts, region, selected, onSelect, onClosePopup }: Props) {
  const containerRef     = useRef<HTMLDivElement>(null)
  const mapRef           = useRef<mapboxgl.Map | null>(null)
  const popupRef         = useRef<mapboxgl.Popup | null>(null)
  const alertsRef        = useRef<Map<string, Alert>>(new Map())
  const mapLoadedRef     = useRef(false)
  const onSelectRef      = useRef(onSelect)
  const onCloseRef       = useRef(onClosePopup)
  const fireMarkersRef   = useRef<mapboxgl.Marker[]>([])

  useEffect(() => { onSelectRef.current = onSelect }, [onSelect])
  useEffect(() => { onCloseRef.current = onClosePopup }, [onClosePopup])

  // Inject pulse CSS once
  useEffect(() => { injectPulseCSS() }, [])

  // Init map once
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return

    mapboxgl.accessToken = process.env.NEXT_PUBLIC_MAPBOX_TOKEN!

    const { center, zoom } = REGION_VIEW[region]
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/satellite-streets-v12",
      center,
      zoom,
      pitch: 40,
      bearing: 0,
      attributionControl: false,
    })

    map.addControl(new mapboxgl.NavigationControl({ showCompass: true }), "bottom-right")
    map.addControl(new mapboxgl.AttributionControl({ compact: true }), "bottom-left")

    map.on("load", () => {
      mapLoadedRef.current = true

      map.addSource("alerts", {
        type: "geojson",
        data: toGeoJSON([]),
        cluster: true,
        clusterMaxZoom: 14,
        clusterRadius: 50,
      })

      // Cluster background circle
      map.addLayer({
        id: "clusters",
        type: "circle",
        source: "alerts",
        filter: ["has", "point_count"],
        paint: {
          "circle-color": "rgba(255,255,255,0.88)",
          "circle-radius": ["step", ["get", "point_count"], 18, 10, 28, 100, 40, 500, 54],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.3)",
        },
      })

      // Cluster count label
      map.addLayer({
        id: "cluster-count",
        type: "symbol",
        source: "alerts",
        filter: ["has", "point_count"],
        layout: {
          "text-field": "{point_count_abbreviated}",
          "text-font": ["DIN Offc Pro Medium", "Arial Unicode MS Bold"],
          "text-size": 13,
        },
        paint: { "text-color": "#111" },
      })

      // Individual point
      map.addLayer({
        id: "unclustered-point",
        type: "circle",
        source: "alerts",
        filter: ["!", ["has", "point_count"]],
        paint: {
          "circle-radius": 7,
          "circle-color": ["get", "color"],
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "rgba(255,255,255,0.9)",
        },
      })

      // Fire area circles (incendios confirmed only)
      map.addSource("fire-areas", {
        type: "geojson",
        data: toFireGeoJSON([]),
      })

      map.addLayer({
        id: "fire-areas-fill",
        type: "circle",
        source: "fire-areas",
        paint: {
          "circle-radius": METERS_PER_PIXEL_AT_ZOOM,
          "circle-color": "#ef4444",
          "circle-opacity": 0.25,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#dc2626",
          "circle-stroke-opacity": 0.8,
        },
      })

      // Cursor
      const setCursor = (layer: string, cursor: string) => {
        map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = cursor })
        map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = "" })
      }
      setCursor("clusters", "pointer")
      setCursor("unclustered-point", "pointer")

      // Click cluster → zoom in
      map.on("click", "clusters", (e) => {
        const features = map.queryRenderedFeatures(e.point, { layers: ["clusters"] })
        if (!features.length) return
        const clusterId = features[0].properties!.cluster_id as number
        const coords = (features[0].geometry as GeoJSON.Point).coordinates as [number, number]
        ;(map.getSource("alerts") as mapboxgl.GeoJSONSource)
          .getClusterExpansionZoom(clusterId, (err, zoom) => {
            if (err || zoom == null) return
            map.easeTo({ center: coords, zoom })
          })
      })

      // Click point → select
      map.on("click", "unclustered-point", (e) => {
        const props = e.features?.[0]?.properties
        if (!props) return
        const alert = alertsRef.current.get(props.id)
        if (alert) onSelectRef.current(alert)
      })

      // Load initial data if already available
      if (alertsRef.current.size > 0) {
        const src = map.getSource("alerts") as mapboxgl.GeoJSONSource
        src.setData(toGeoJSON([...alertsRef.current.values()]))
      }
    })

    mapRef.current = map

    return () => {
      mapLoadedRef.current = false
      fireMarkersRef.current.forEach((m) => m.remove())
      fireMarkersRef.current = []
      map.remove()
      mapRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fly to region
  useEffect(() => {
    if (!mapRef.current) return
    const { center, zoom } = REGION_VIEW[region]
    mapRef.current.flyTo({ center, zoom, duration: 1200, essential: true })
  }, [region])

  // Sync alerts + fire areas in one effect to avoid two back-to-back setData calls
  useEffect(() => {
    alertsRef.current = new Map(alerts.map((a) => [a.id, a]))
    if (!mapRef.current || !mapLoadedRef.current) return
    ;(mapRef.current.getSource("alerts") as mapboxgl.GeoJSONSource)?.setData(toGeoJSON(alerts))
    ;(mapRef.current.getSource("fire-areas") as mapboxgl.GeoJSONSource)?.setData(toFireGeoJSON(alerts))
  }, [alerts])

  // Pulse markers for confirmed fire alerts
  useEffect(() => {
    fireMarkersRef.current.forEach((m) => m.remove())
    fireMarkersRef.current = []
    if (!mapRef.current) return
    alerts
      .filter((a) => a.type === "incendios" && a.tier === "confirmed")
      .forEach((a) => {
        const el = document.createElement("div")
        el.className = "sw-fire-marker"
        el.addEventListener("click", () => onSelectRef.current(a))
        const marker = new mapboxgl.Marker({ element: el, anchor: "center" })
          .setLngLat([a.lon, a.lat])
          .addTo(mapRef.current!)
        fireMarkersRef.current.push(marker)
      })
  }, [alerts])

  // Popup for selected alert
  useEffect(() => {
    popupRef.current?.remove()
    popupRef.current = null
    if (!selected || !mapRef.current) return

    const popup = new mapboxgl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: "460px",
      offset: 12,
    })
      .setLngLat([selected.lon, selected.lat])
      .setHTML(buildPopupHTML(selected as unknown as Record<string, unknown>))
      .addTo(mapRef.current)

    popup.on("close", () => onCloseRef.current())
    popupRef.current = popup
    mapRef.current.easeTo({ center: [selected.lon, selected.lat], duration: 600 })
  }, [selected])

  return (
    <div className="relative flex-1 h-full overflow-hidden min-w-0">
      <div ref={containerRef} style={{ position: "absolute", inset: 0 }} />

      {/* Legend */}
      <div className="absolute top-3 left-3 z-10 rounded-xl bg-black/55 backdrop-blur-md px-3 py-2.5 text-white shadow-lg">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-white/50 mb-2">
          Leyenda
        </div>
        {(Object.entries(ACTIVITY_COLORS) as [ActivityType, string][]).map(([type, color]) => (
          <div key={type} className="flex items-center gap-2 py-[3px]">
            <span
              className="inline-block w-2.5 h-2.5 rounded-full flex-shrink-0"
              style={{ background: color }}
            />
            <span className="text-[11px] text-white/90">{ACTIVITY_LABELS[type]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
