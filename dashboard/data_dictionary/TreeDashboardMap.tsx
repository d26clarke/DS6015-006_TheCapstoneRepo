import React from 'react';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import { TreeInventoryRecord } from '../types/tree_inventory_schema';
import 'leaflet/dist/leaflet.css';

// Fix for default Leaflet icon paths in compiled web frameworks
import markerIcon from 'leaflet/dist/images/marker-icon.png';
import markerShadow from 'leaflet/dist/images/marker-shadow.png';

const DefaultIcon = L.icon({
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
  iconSize:,
  iconAnchor:,
});
L.Marker.prototype.options.icon = DefaultIcon;

interface MapProps {
  trees: TreeInventoryRecord[];
}

// Mapbox Access Token and custom Style URL (e.g., Satellite Streets or Outdoors)
const MAPBOX_ACCESS_TOKEN = "your_mapbox_access_token_here";
const MAPBOX_STYLE_ID = "mapbox/streets-v12"; // alternative: mapbox/satellite-streets-v12
const MAPBOX_TILE_URL = `https://mapbox.com{MAPBOX_STYLE_ID}/tiles/{z}/{x}/{y}?access_token=${MAPBOX_ACCESS_TOKEN}`;

export const TreeDashboardMap: React.FC<MapProps> = ({ trees }) => {
  // Center map view on Central Virginia coordinates (Charlottesville/Albemarle)
  const centralVirginiaCenter: [number, number] = [38.0293, -78.4767];

  // Helper utility to safely parse "Lat, Long" database strings
  const parseCoordinates = (coordString: string): [number, number] | null => {
    try {
      const parts = coordString.split(',');
      if (parts.length !== 2) return null;
      const lat = parseFloat(parts[0].trim());
      const lng = parseFloat(parts[1].trim());
      return isNaN(lat) || isNaN(lng) ? null : [lat, lng];
    } catch {
      return null;
    }
  };

  return (
    <div className="w-full h-[600px] rounded-xl overflow-hidden shadow-lg border border-gray-200">
      <MapContainer 
        center={centralVirginiaCenter} 
        zoom={12} 
        className="w-full h-full"
      >
        {/* Mapbox Vector High-Resolution Layer integration */}
        <TileLayer
          attribution='© <a href="https://mapbox.com">Mapbox</a> © <a href="http://openstreetmap.org">OpenStreetMap</a>'
          url={MAPBOX_TILE_URL}
          tileSize={512}
          zoomOffset={-1}
        />

        {/* Dynamic Tree Spatial Markers mapping */}
        {trees.map((tree) => {
          const position = parseCoordinates(tree.gpsCoordinates);
          if (!position) return null; // Skip records with corrupt geospatial formatting

          return (
            <Marker key={tree.treeId} position={position}>
              <Popup className="custom-leaflet-popup">
                <div className="w-64 p-1">
                  {tree.photoUrl ? (
                    <img 
                      src={tree.photoUrl} 
                      alt={tree.commonName} 
                      className="w-full h-32 object-cover rounded-md mb-2 shadow-sm"
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-full h-32 bg-gray-100 flex items-center justify-center rounded-md mb-2 text-xs text-gray-400 border border-dashed">
                      No Photo Available
                    </div>
                  )}
                  <h4 className="font-bold text-sm text-gray-900">{tree.commonName}</h4>
                  <p className="text-xs text-gray-500 italic mb-1">{tree.scientificName}</p>
                  
                  <div className="text-xs space-y-1 text-gray-700 border-t pt-1 mt-1">
                    <div><strong>ID:</strong> {tree.treeId}</div>
                    <div><strong>DBH:</strong> {tree.dbhInches} in</div>
                    <div><strong>Soil Moisture:</strong> {tree.soilMoistureRegime || 'N/A'}</div>
                    <div><strong>Condition:</strong> {tree.conditionClass || 'N/A'}</div>
                  </div>
                </div>
              </Popup>
            </Marker>
          );
        })}
      </MapContainer>
    </div>
  );
};

