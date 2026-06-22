import { FC, useEffect, useRef } from 'react'
import * as Cesium from 'cesium'
import { AlertProperties, ViewMode } from '../../types'
import { sevColor, normSev } from '../../utils'

interface CesiumGlobeProps {
  alerts: AlertProperties[]
  selected: AlertProperties | null
  mode: ViewMode
  onSelectAlert: (alert: AlertProperties) => void
  onModeChange?: (mode: ViewMode) => void
  onCursorLL?: (lat: number, lon: number) => void
}

export const CesiumGlobe: FC<CesiumGlobeProps> = ({
  alerts,
  selected,
  mode,
  onSelectAlert,
  onModeChange,
  onCursorLL,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<Cesium.Viewer | null>(null)
  const entitiesRef = useRef<Map<string, Cesium.Entity>>(new Map())

  // Initialize Cesium viewer
  useEffect(() => {
    if (!containerRef.current || viewerRef.current) return

    Cesium.Ion.defaultAccessToken = import.meta.env.VITE_CESIUM_TOKEN ?? ''

    const viewer = new Cesium.Viewer(containerRef.current, {
      animation: false,
      baseLayerPicker: false,
      fullscreenButton: false,
      vrButton: false,
      geocoder: false,
      homeButton: false,
      infoBox: false,
      sceneModePicker: false,
      selectionIndicator: false,
      timeline: false,
      navigationHelpButton: false,
      creditContainer: document.createElement('div'),
      baseLayer: false,
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    })

    // Add satellite imagery
    viewer.imageryLayers.add(
      new Cesium.ImageryLayer(
        new Cesium.UrlTemplateImageryProvider({
          url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
          tilingScheme: new Cesium.WebMercatorTilingScheme(),
          maximumLevel: 19,
        })
      )
    )

    // Set initial view centered on Chile
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(-71, -35, 4500000),
    })

    if (viewer.scene.skyAtmosphere) viewer.scene.skyAtmosphere.show = true
    viewer.scene.fog.enabled = false

    viewerRef.current = viewer

    // Click handler
    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
    handler.setInputAction((e: { position: Cesium.Cartesian2 }) => {
      const picked = viewer.scene.pick(e.position)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if (Cesium.defined(picked) && (picked.id as any)?._alertData) {
        onSelectAlert((picked.id as any)._alertData as AlertProperties)
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK)

    return () => {
      handler.destroy()
      viewer.destroy()
      viewerRef.current = null
    }
  }, [onSelectAlert])

  // Update markers when alerts change
  useEffect(() => {
    if (!viewerRef.current) return

    const viewer = viewerRef.current
    const currentIds = new Set(alerts.map((a) => a.id))
    const existingIds = entitiesRef.current.keys()

    // Remove entities for deleted alerts
    for (const id of existingIds) {
      if (!currentIds.has(id)) {
        const entity = entitiesRef.current.get(id)
        if (entity) viewer.entities.remove(entity)
        entitiesRef.current.delete(id)
      }
    }

    // Add or update entities for alerts
    for (const alert of alerts) {
      const lat = typeof alert.lat === 'string' ? parseFloat(alert.lat) : alert.lat
      const lon = typeof alert.lon === 'string' ? parseFloat(alert.lon) : alert.lon
      const sev = normSev(alert.severity)
      const color = sevColor(sev)

      let entity = entitiesRef.current.get(alert.id)
      if (!entity) {
        entity = viewer.entities.add({
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          point: {
            pixelSize: 8,
            color: Cesium.Color.fromCssColorString(color),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 1,
          },
        })
          // Store alert data as a custom property for click handling
          ; (entity as any)._alertData = alert
        entitiesRef.current.set(alert.id, entity)
      }
    }
  }, [alerts])

  // Handle mode changes
  useEffect(() => {
    if (!viewerRef.current) return

    const viewer = viewerRef.current
    const targetHeights: Record<ViewMode, number> = {
      globe: 8000000,
      map: 1500000,
      satellite: 150000,
      list: 1500000,
    }

    const center = viewer.camera.position
    const cartographic = Cesium.Ellipsoid.WGS84.cartesianToCartographic(center)

    viewer.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(
        Cesium.Math.toDegrees(cartographic.longitude),
        Cesium.Math.toDegrees(cartographic.latitude),
        targetHeights[mode]
      ),
      duration: 2.0,
      easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
    })
  }, [mode])

  // Fly to selected alert
  useEffect(() => {
    if (!selected || !viewerRef.current) return

    const lat = typeof selected.lat === 'string' ? parseFloat(selected.lat) : selected.lat
    const lon = typeof selected.lon === 'string' ? parseFloat(selected.lon) : selected.lon

    viewerRef.current.camera.flyTo({
      destination: Cesium.Cartesian3.fromDegrees(lon, lat, 50000),
      duration: 2.0,
      easingFunction: Cesium.EasingFunction.CUBIC_IN_OUT,
    })
  }, [selected])

  return (
    <div
      ref={containerRef}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
      }}
    />
  )
}
