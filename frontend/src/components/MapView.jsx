import { useCallback, useEffect, useState } from "react";
<<<<<<< HEAD
import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";
=======
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMapEvents } from "react-leaflet";
>>>>>>> 78fa4a37380290c9a1fedf8473b1ef448bd84265
import "leaflet/dist/leaflet.css";

function LocationSelector({ onLocationPick }) {
  useMapEvents({ click: (event) => onLocationPick([event.latlng.lat, event.latlng.lng]) });
  return null;
}

function MapView({ onRouteChange }) {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
<<<<<<< HEAD
  const [routes, setRoutes] = useState([]);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);
  const [tracking, setTracking] = useState(false);
  const [currentLocation, setCurrentLocation] = useState(null);
  const [locationError, setLocationError] = useState("");
=======
  const [route, setRoute] = useState(null);
>>>>>>> 78fa4a37380290c9a1fedf8473b1ef448bd84265
  const [mapillaryEvidence, setMapillaryEvidence] = useState([]);

  useEffect(() => {
    fetch("/data/mangalore_mapillary_accessibility.geojson")
      .then((response) => response.ok ? response.json() : null)
      .then((data) => setMapillaryEvidence(data?.features || []))
      .catch(() => setMapillaryEvidence([]));
<<<<<<< HEAD
  }, []);

  const handleLocationUpdate = useCallback((location) => {
    setCurrentLocation(location);
    setLocationError("");
  }, []);
  const handleLocationError = useCallback((message) => {
    setLocationError(message);
    setTracking(false);
=======
>>>>>>> 78fa4a37380290c9a1fedf8473b1ef448bd84265
  }, []);
  const fetchRoute = useCallback(async (startLocation, destinationLocation) => {
    const coordinates = [startLocation, destinationLocation].map(([lat, lon]) => `${lon},${lat}`).join(";");
    try {
      const response = await fetch(`https://router.project-osrm.org/route/v1/foot/${coordinates}?overview=full&geometries=geojson`);
      const data = await response.json();
      if (!response.ok || data.code !== "Ok" || !data.routes?.length) {
        setRoute(null);
        onRouteChange(null);
        return;
      }
      const routeData = data.routes[0];
      setRoute(routeData.geometry.coordinates.map(([lon, lat]) => [lat, lon]));
      onRouteChange({ distance: routeData.distance, duration: routeData.duration });
    } catch {
      setRoute(null);
      onRouteChange(null);
    }
  }, [onRouteChange]);

  useEffect(() => {
    if (start && destination) fetchRoute(start, destination);
  }, [destination, fetchRoute, start]);

  function handleLocationPick(location) {
    if (!start || destination) {
<<<<<<< HEAD
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
=======
      setStart(location); setDestination(null); setRoute(null); onRouteChange(null);
    } else setDestination(location);
  }
  return <div className="map-canvas"><MapContainer center={[12.899738, 74.983481]} zoom={16} className="leaflet-map" zoomControl={false}>
    <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <LocationSelector onLocationPick={handleLocationPick} />
    {start && <Marker position={start}><Popup>Start location</Popup></Marker>}
    {destination && <Marker position={destination}><Popup>Destination</Popup></Marker>}
    {mapillaryEvidence.map((feature) => {
      const [longitude, latitude] = feature.geometry.coordinates;
      const properties = feature.properties;
      return <CircleMarker key={feature.id} center={[latitude, longitude]} radius={6} pathOptions={{ color: "#c47b00", fillColor: "#f2b84b", fillOpacity: 0.9 }}>
        <Popup><strong>Mapillary evidence: {properties.evidence_type}</strong><br />Status: needs review<br />Raw detection: {properties.raw_value || "unknown"}</Popup>
      </CircleMarker>;
    })}
    {route && <Polyline positions={route} pathOptions={{ color: "#2351d8", weight: 6, opacity: 0.86 }} />}
  </MapContainer></div>;
>>>>>>> 78fa4a37380290c9a1fedf8473b1ef448bd84265
}

export default MapView;
