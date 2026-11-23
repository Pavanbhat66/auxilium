import { useCallback, useEffect, useState } from "react";
import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

function LocationSelector({ onLocationPick }) {
  useMapEvents({ click: (event) => onLocationPick([event.latlng.lat, event.latlng.lng]) });
  return null;
}

function LocationTracker({ enabled, onLocation, onError }) {
  useEffect(() => {
    if (!enabled || !navigator.geolocation) {
      if (enabled) onError("Location sharing is not supported by this browser.");
      return undefined;
    }
    const watchId = navigator.geolocation.watchPosition(
      ({ coords }) => onLocation({ point: [coords.latitude, coords.longitude], accuracy: coords.accuracy }),
      (error) => onError(error.message || "Unable to read your location."),
      { enableHighAccuracy: true, maximumAge: 10_000, timeout: 15_000 },
    );
    return () => navigator.geolocation.clearWatch(watchId);
  }, [enabled, onError, onLocation]);
  return null;
}

function MapView({ profile, onRouteChange }) {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);
  const [tracking, setTracking] = useState(false);
  const [currentLocation, setCurrentLocation] = useState(null);
  const [locationError, setLocationError] = useState("");
  const [routeError, setRouteError] = useState("");
  const [evidence, setEvidence] = useState([]);

  useEffect(() => {
    let active = true;
    fetch("/data/mangalore_mapillary_accessibility.geojson")
      .then((response) => response.ok ? response.json() : null)
      .then((data) => {
        if (!active) return;
        const unique = new Map();
        for (const feature of data?.features || []) {
          const coordinates = feature?.geometry?.coordinates;
          if (feature?.geometry?.type !== "Point" || !Array.isArray(coordinates) || coordinates.length !== 2) continue;
          const id = feature.id || `${coordinates[0]}:${coordinates[1]}`;
          if (!unique.has(id)) unique.set(id, feature);
        }
        setEvidence([...unique.values()]);
      })
      .catch(() => { if (active) setEvidence([]); });
    return () => { active = false; };
  }, []);

  const handleLocationUpdate = useCallback((location) => {
    setCurrentLocation(location);
    setLocationError("");
  }, []);
  const handleLocationError = useCallback((message) => {
    setLocationError(message);
    setTracking(false);
  }, []);

  const fetchRoute = useCallback(async (startLocation, destinationLocation, signal) => {
    try {
      const response = await fetch("/api/routes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        signal,
        body: JSON.stringify({
          start: { lat: startLocation[0], lon: startLocation[1] },
          destination: { lat: destinationLocation[0], lon: destinationLocation[1] },
          profile,
          alternatives: 3,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "No route was found.");
      const nextRoutes = (data.routes || []).map((route) => ({
        ...route,
        points: route.geometry.coordinates.map(([lon, lat]) => [lat, lon]),
      }));
      setRoutes(nextRoutes);
      setSelectedRouteIndex(0);
      onRouteChange(nextRoutes[0] || null);
    } catch (error) {
      if (error.name === "AbortError") return;
      setRoutes([]);
      setRouteError(error.message);
      onRouteChange(null);
    }
  }, [onRouteChange, profile]);

  useEffect(() => {
    if (!start || !destination) return undefined;
    const controller = new AbortController();
    fetchRoute(start, destination, controller.signal);
    return () => controller.abort();
  }, [destination, fetchRoute, start]);

  function handleLocationPick(location) {
    if (!start || destination) {
      setStart(location);
      setDestination(null);
      setRoutes([]);
      setRouteError("");
      onRouteChange(null);
    } else {
      setDestination(location);
    }
  }

  function selectRoute(index) {
    const selectedRoute = routes[index];
    if (!selectedRoute) return;
    setSelectedRouteIndex(index);
    onRouteChange(selectedRoute);
  }

  function useCurrentLocationAsStart() {
    if (!currentLocation) return;
    setStart(currentLocation.point);
    setDestination(null);
    setRoutes([]);
    onRouteChange(null);
  }

  return <div className="map-canvas">
    <MapContainer center={[12.899738, 74.983481]} zoom={16} className="leaflet-map" zoomControl={false}>
      <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <LocationSelector onLocationPick={handleLocationPick} />
      <LocationTracker enabled={tracking} onLocation={handleLocationUpdate} onError={handleLocationError} />
      {start && <Marker position={start}><Popup>Start location</Popup></Marker>}
      {destination && <Marker position={destination}><Popup>Destination</Popup></Marker>}
      {currentLocation && <>
        <Circle center={currentLocation.point} radius={currentLocation.accuracy} pathOptions={{ color: "#2351d8", fillColor: "#2351d8", fillOpacity: 0.12, weight: 1 }} />
        <CircleMarker center={currentLocation.point} radius={8} pathOptions={{ color: "#fff", weight: 3, fillColor: "#2351d8", fillOpacity: 1 }}><Popup>Your live location</Popup></CircleMarker>
      </>}
      {evidence.map((feature) => {
        const [longitude, latitude] = feature.geometry.coordinates;
        const properties = feature.properties || {};
        const isGemini = properties.source === "gemini_ai";
        return <CircleMarker key={feature.id} center={[latitude, longitude]} radius={isGemini ? 6 : 7} pathOptions={{ color: isGemini ? "#7046b8" : "#c47b00", fillColor: isGemini ? "#a884db" : "#f2b84b", fillOpacity: 0.9 }}>
          <Popup>
            <strong>{isGemini ? "Gemini visual observation" : "Mapillary detection"}</strong><br />
            Category: {properties.feature_name || properties.evidence_type || "unknown"}<br />
            Value: {properties.predicted_value || properties.raw_value || "unknown"}<br />
            {properties.confidence !== undefined && <>Confidence: {Math.round(Number(properties.confidence) * 100)}%<br /></>}
            {properties.mapillary_image_id && <>Image ID: {properties.mapillary_image_id}<br /></>}
            {properties.model && <>Model: {properties.model}<br /></>}
            OSM path: {properties.path_id || "not associated"}<br />
            Status: {properties.verification_status || "needs_review"}<br />
            <em>Evidence requires human verification; it is not a confirmed accessibility fact.</em>
          </Popup>
        </CircleMarker>;
      })}
      {routes.map((route, index) => <Polyline key={`${index}-${route.distance}`} positions={route.points} eventHandlers={{ click: () => selectRoute(index) }} pathOptions={{ color: index === selectedRouteIndex ? "#2351d8" : "#68758a", weight: index === selectedRouteIndex ? 7 : 4, opacity: index === selectedRouteIndex ? 0.9 : 0.52 }} />)}
    </MapContainer>
    <div className="location-controls">
      <button type="button" className={tracking ? "location-button tracking" : "location-button"} onClick={() => { setLocationError(""); setTracking((active) => !active); }} aria-pressed={tracking}>{tracking ? "Stop live location" : "Use live location"}</button>
      {currentLocation && <button type="button" className="location-button secondary" onClick={useCurrentLocationAsStart}>Set as route start</button>}
      <p className="location-status" aria-live="polite">{routeError || locationError || (tracking ? "Updating your location…" : currentLocation ? "Location available" : "Location sharing is off")}</p>
    </div>
    {routes.length > 1 && <section className="route-options" aria-label="Alternative routes">
      <p>Route options</p>
      {routes.map((route, index) => <button key={`${index}-${route.distance}`} type="button" className={index === selectedRouteIndex ? "route-option selected" : "route-option"} onClick={() => selectRoute(index)} aria-pressed={index === selectedRouteIndex}>
        <strong>Route {index + 1}</strong><span>{(route.distance / 1000).toFixed(2)} km · {Math.round(route.duration / 60)} min</span>
      </button>)}
    </section>}
    <p className="map-attribution">Map data © OpenStreetMap contributors · Evidence © Mapillary · Gemini observations are AI-generated and require human verification.</p>
  </div>;
}

export default MapView;
