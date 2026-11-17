import { useCallback, useEffect, useState } from "react";
import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

function LocationSelector({ onLocationPick }) {
  useMapEvents({ click: (event) => onLocationPick([event.latlng.lat, event.latlng.lng]) });
  return null;
}

function distanceMeters([latA, lonA], [latB, lonB]) {
  const earthRadius = 6371000;
  const latitudeDelta = (latB - latA) * Math.PI / 180;
  const longitudeDelta = (lonB - lonA) * Math.PI / 180;
  const a = Math.sin(latitudeDelta / 2) ** 2
    + Math.cos(latA * Math.PI / 180) * Math.cos(latB * Math.PI / 180) * Math.sin(longitudeDelta / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function evidenceNearRoute(routeCoordinates, evidence) {
  const nearby = evidence.filter((feature) => {
    const [longitude, latitude] = feature.geometry.coordinates;
    return routeCoordinates.some((point) => distanceMeters(point, [latitude, longitude]) <= 50);
  });
  return [...new Map(nearby.map((feature) => [feature.properties.evidence_type, feature])).values()];
}

function MapView({ profile, onRouteChange }) {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);
  const [tracking, setTracking] = useState(false);
  const [currentLocation, setCurrentLocation] = useState(null);
  const [locationError, setLocationError] = useState("");
  const [mapillaryEvidence, setMapillaryEvidence] = useState([]);

  useEffect(() => {
    fetch("/data/mangalore_mapillary_accessibility.geojson")
      .then((response) => response.ok ? response.json() : null)
      .then((data) => setMapillaryEvidence(data?.features || []))
      .catch(() => setMapillaryEvidence([]));
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
    const coordinates = [startLocation, destinationLocation].map(([lat, lon]) => `${lon},${lat}`).join(";");
    try {
      const response = await fetch(`https://router.project-osrm.org/route/v1/foot/${coordinates}?alternatives=3&overview=full&geometries=geojson`, { signal });
      const data = await response.json();
      if (data.code !== "Ok" || !data.routes?.length) return;
      const routeData = data.routes[0];
      const routeCoordinates = routeData.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
      const nearbyEvidence = evidenceNearRoute(routeCoordinates, mapillaryEvidence);
      const actionableEvidence = nearbyEvidence.filter((feature) => {
        const properties = feature.properties || {};
        return properties.source !== "gemini_ai" || properties.predicted_value !== "unknown";
      });
      const warnings = profile === "general" ? [] : actionableEvidence.map((feature) => `Potential ${feature.properties.evidence_type} near this route`);
      const penalty = profile === "wheelchair" ? 20 : 10;
      setRoute(routeCoordinates);
      onRouteChange({
        distance: routeData.distance,
        duration: routeData.duration,
        accessibilityScore: Math.max(0, 100 - warnings.length * penalty),
        warnings,
      });
    } catch {
      setRoute(null);
      onRouteChange(null);
    }
  }, [mapillaryEvidence, onRouteChange, profile]);

  function handleLocationPick(location) {
    if (!start || destination) {
      setStart(location);
      setDestination(null);
      setRoutes([]);
      onRouteChange(null);
    } else {
      setDestination(location);
    }
  }

  function selectRoute(index) {
    const selectedRoute = routes[index];
    if (!selectedRoute) return;
    setSelectedRouteIndex(index);
    onRouteChange({ distance: selectedRoute.distance, duration: selectedRoute.duration });
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
      {mapillaryEvidence.map((feature) => {
        const [longitude, latitude] = feature.geometry.coordinates;
        const properties = feature.properties;
        return <CircleMarker key={feature.id} center={[latitude, longitude]} radius={6} pathOptions={{ color: "#c47b00", fillColor: "#f2b84b", fillOpacity: 0.9 }}>
          <Popup><strong>Mapillary evidence: {properties.evidence_type}</strong><br />Status: needs review<br />Raw detection: {properties.raw_value || "unknown"}</Popup>
        </CircleMarker>;
      })}
      {routes.map((route, index) => <Polyline key={`${index}-${route.distance}`} positions={route.points} eventHandlers={{ click: () => selectRoute(index) }} pathOptions={{ color: index === selectedRouteIndex ? "#2351d8" : "#68758a", weight: index === selectedRouteIndex ? 7 : 4, opacity: index === selectedRouteIndex ? 0.9 : 0.52 }} />)}
    </MapContainer>
    <div className="location-controls">
      <button type="button" className={tracking ? "location-button tracking" : "location-button"} onClick={() => { setLocationError(""); setTracking((active) => !active); }} aria-pressed={tracking}>{tracking ? "Stop live location" : "Use live location"}</button>
      {currentLocation && <button type="button" className="location-button secondary" onClick={useCurrentLocationAsStart}>Set as route start</button>}
      <p className="location-status" aria-live="polite">{locationError || (tracking ? "Updating your location…" : currentLocation ? "Location available" : "Location sharing is off")}</p>
    </div>
    {routes.length > 1 && <section className="route-options" aria-label="Alternative routes">
      <p>Route options</p>
      {routes.map((route, index) => <button key={`${index}-${route.distance}`} type="button" className={index === selectedRouteIndex ? "route-option selected" : "route-option"} onClick={() => selectRoute(index)} aria-pressed={index === selectedRouteIndex}>
        <strong>Route {index + 1}</strong><span>{(route.distance / 1000).toFixed(2)} km · {Math.round(route.duration / 60)} min</span>
      </button>)}
    </section>}
  </div>;
}

export default MapView;
