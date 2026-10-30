import { useCallback, useEffect, useState } from "react";
import { Circle, CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

function LocationSelector({ onLocationPick }) {
  useMapEvents({ click: (event) => onLocationPick([event.latlng.lat, event.latlng.lng]) });
  return null;
}

function LocationTracker({ enabled, onLocation, onError }) {
  const map = useMap();

  useEffect(() => {
    if (!enabled) return undefined;

    const handleFound = (event) => onLocation({ point: [event.latlng.lat, event.latlng.lng], accuracy: event.accuracy });
    const handleError = (event) => onError(event.message || "Your location could not be determined.");
    map.on("locationfound", handleFound);
    map.on("locationerror", handleError);
    map.locate({ watch: true, enableHighAccuracy: true, setView: true, maxZoom: 18, timeout: 15000, maximumAge: 5000 });

    return () => {
      map.stopLocate();
      map.off("locationfound", handleFound);
      map.off("locationerror", handleError);
    };
  }, [enabled, map, onError, onLocation]);

  return null;
}

function MapView({ onRouteChange }) {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [routes, setRoutes] = useState([]);
  const [selectedRouteIndex, setSelectedRouteIndex] = useState(0);
  const [tracking, setTracking] = useState(false);
  const [currentLocation, setCurrentLocation] = useState(null);
  const [locationError, setLocationError] = useState("");
  const handleLocationUpdate = useCallback((location) => {
    setCurrentLocation(location);
    setLocationError("");
  }, []);
  const handleLocationError = useCallback((message) => {
    setLocationError(message);
    setTracking(false);
  }, []);
  const fetchRoute = useCallback(async (startLocation, destinationLocation) => {
    const points = [startLocation, destinationLocation];
    const coordinates = points.map(([lat, lon]) => `${lon},${lat}`).join(";");
    try {
      const response = await fetch(`https://router.project-osrm.org/route/v1/foot/${coordinates}?alternatives=3&overview=full&geometries=geojson`);
      const data = await response.json();
      if (!response.ok || data.code !== "Ok" || !data.routes?.length) {
        setRoutes([]);
        onRouteChange(null);
        return;
      }
      const routeOptions = data.routes.map((routeData) => ({
        points: routeData.geometry.coordinates.map(([lon, lat]) => [lat, lon]),
        distance: routeData.distance,
        duration: routeData.duration,
      }));
      setRoutes(routeOptions);
      setSelectedRouteIndex(0);
      onRouteChange({ distance: routeOptions[0].distance, duration: routeOptions[0].duration });
    } catch {
      setRoutes([]);
      onRouteChange(null);
    }
  }, [onRouteChange]);

  useEffect(() => { if (start && destination) fetchRoute(start, destination); }, [destination, fetchRoute, start]);
  function handleLocationPick(location) {
    if (!start || destination) {
      setStart(location); setDestination(null); setRoutes([]); onRouteChange(null);
    } else setDestination(location);
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
  return <div className="map-canvas"><MapContainer center={[12.899738, 74.983481]} zoom={16} className="leaflet-map" zoomControl={false}>
    <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
    <LocationSelector onLocationPick={handleLocationPick} />
    <LocationTracker enabled={tracking} onLocation={handleLocationUpdate} onError={handleLocationError} />
    {start && <Marker position={start}><Popup>Start location</Popup></Marker>}
    {destination && <Marker position={destination}><Popup>Destination</Popup></Marker>}
    {currentLocation && <><Circle center={currentLocation.point} radius={currentLocation.accuracy} pathOptions={{ color: "#2351d8", fillColor: "#2351d8", fillOpacity: 0.12, weight: 1 }} /><CircleMarker center={currentLocation.point} radius={8} pathOptions={{ color: "#fff", weight: 3, fillColor: "#2351d8", fillOpacity: 1 }}><Popup>Your live location</Popup></CircleMarker></>}
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
