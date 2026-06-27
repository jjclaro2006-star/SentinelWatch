"use client"

import { useEffect, useRef } from "react"
import mapboxgl from "mapbox-gl"
import "mapbox-gl/dist/mapbox-gl.css"
import { ACTIVITY_LABELS, type ActivityType, type Alert, type Region } from "@/lib/sentinel-data"

interface Props {
  alerts: Alert[]
  region: Region
  selected: Alert | null
  onSelect: (alert: Alert) => void
  onClosePopup: () => void
}

const REGION_VIEW: Record<Region, { center: [number, number]; zoom: number }> = {
  colombia: { center: [-72.5, -0.5], zoom: 6 },
  peru:     { center: [-74.5, -5.0], zoom: 6 },
  brasil:   { center: [-62.0, -10.0], zoom: 5 },
  bolivia:  { center: [-65.0, -15.0], zoom: 6 },
}

const ACTIVITY_COLORS: Record<ActivityType, string> = {
  mineria:       "#f97316",
  deforestacion: "#22c55e",
  incendios:     "#eab308",
  cultivos:      "#a855f7",
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

function buildPopupHTML(p: Record<string, unknown>): string {
  const color = ACTIVITY_COLORS[p.type as ActivityType] ?? "#fff"
  const label = ACTIVITY_LABELS[p.type as ActivityType] ?? String(p.type)
  const rows: [string, string][] = [
    ["Severidad", `<span style="color:${color}">${p.severity}</span>`],
    ["Confianza", `${p.confidence}%`],
    ["Veredicto", String(p.verdict)],
    ["Fecha", String(p.date)],
    ...(p.area_ha != null ? [["Área", `${Number(p.area_ha).toFixed(1)} ha`] as [string, string]] : []),
    ...(p.wdpaName ? [["WDPA", `<span style="color:#f85149">${p.wdpaName}</span>`] as [string, string]] : []),
  ]
  return `
    <div style="font-family:ui-monospace,monospace;font-size:11px;line-height:1.6;
                color:#c9d1d9;background:#161b22;padding:10px 12px;
                border-radius:6px;min-width:200px;border:1px solid #30363d">
      <div style="color:${color};font-weight:700;font-size:12px;margin-bottom:6px">${label}</div>
      <table style="border-collapse:collapse;width:100%">
        ${rows.map(([k, v]) => `
          <tr>
            <td style="color:#8b949e;padding-right:8px;white-space:nowrap">${k}</td>
            <td>${v}</td>
          </tr>`).join("")}
      </table>
    </div>`
}

export function MapViewport({ alerts, region, selected, onSelect, onClosePopup }: Props) {
  const containerRef  = useRef<HTMLDivElement>(null)
  const mapRef        = useRef<mapboxgl.Map | null>(null)
  const popupRef      = useRef<mapboxgl.Popup | null>(null)
  const alertsRef     = useRef<Map<string, Alert>>(new Map())
  const mapLoadedRef  = useRef(false)
  const onSelectRef   = useRef(onSelect)
  const onCloseRef    = useRef(onClosePopup)

  useEffect(() => { onSelectRef.current = onSelect }, [onSelect])
  useEffect(() => { onCloseRef.current = onClosePopup }, [onClosePopup])

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

  // Sync alerts to GeoJSON source
  useEffect(() => {
    alertsRef.current = new Map(alerts.map((a) => [a.id, a]))
    if (!mapRef.current || !mapLoadedRef.current) return
    const src = mapRef.current.getSource("alerts") as mapboxgl.GeoJSONSource
    src?.setData(toGeoJSON(alerts))
  }, [alerts])

  // Popup for selected alert
  useEffect(() => {
    popupRef.current?.remove()
    popupRef.current = null
    if (!selected || !mapRef.current) return

    const popup = new mapboxgl.Popup({
      closeButton: true,
      closeOnClick: false,
      maxWidth: "280px",
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
