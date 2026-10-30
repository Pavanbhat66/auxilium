import { useCallback, useEffect, useState } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";

function waypointFor(profile, start, destination) {
  if (profile === "general") return null;
  const [startLat, startLon] = start;
  const [destinationLat, destinationLon] = destination;
  const latDifference = destinationLat - startLat;
  const lonDifference = destinationLon - startLon;
  const length = Math.hypot(latDifference, lonDifference);
  if (!length) return null;
  const offset = 0.0015 * (profile === "wheelchair" ? 1 : -1);
  return [(startLat + destinationLat) / 2 + (-lonDifference / length) * offset, (startLon + destinationLon) / 2 + (latDifference / length) * offset];
}

function LocationSelector({ onLocationPick }) {
  useMapEvents({ click: (event) => onLocationPick([event.latlng.lat, event.latlng.lng]) });
  return null;
}

function MapView({ profile, onRouteChange }) {
  const [start, setStart] = useState(null);
  const [destination, setDestination] = useState(null);
  const [route, setRoute] = useState(null);
  const [mapillaryEvidence, setMapillaryEvidence] = useState([]);

  useEffect(() => {
    fetch("/data/mangalore_mapillary_accessibility.geojson")
      .then((response) => response.ok ? response.json() : null)
      .then((data) => setMapillaryEvidence(data?.features || []))
      .catch(() => setMapillaryEvidence([]));
  }, []);
  const fetchRoute = useCallback(async (startLocation, destinationLocation) => {
    const waypoint = waypointFor(profile, startLocation, destinationLocation);
    const points = waypoint ? [startLocation, waypoint, destinationLocation] : [startLocation, destinationLocation];
    const coordinates = points.map(([lat, lon]) => `${lon},${lat}`).join(";");
    try {
      const response = await fetch(`https://router.project-osrm.org/route/v1/foot/${coordinates}?overview=full&geometries=geojson`);
      const data = await response.json();
      if (data.code !== "Ok" || !data.routes?.length) return;
      const routeData = data.routes[0];
      setRoute(routeData.geometry.coordinates.map(([lon, lat]) => [lat, lon]));
      onRouteChange({ distance: routeData.distance, duration: routeData.duration });
    } catch {
      setRoute(null);
      onRouteChange(null);
    }
  }, [onRouteChange, profile]);

  useEffect(() => { if (start && destination) fetchRoute(start, destination); }, [destination, fetchRoute, start]);
  function handleLocationPick(location) {
    if (!start || destination) {
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
}

export default MapView;
