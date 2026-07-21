// CanopyMaskLayer.tsx
//
// Overlays a binary canopy mask GeoTIFF (*_canopy_mask.tif) -- a stark
// "is there canopy here, yes/no" view, as opposed to ChmRasterLayer's
// graduated height coloring. Same loading/CRS approach as ChmRasterLayer,
// just a simpler two-color pixelValuesToColorFn.
//
// Intended as an alternate view, toggled instead of alongside the CHM
// height layer (showing both at once for the same tile is redundant --
// the mask conveys strictly less information than the height raster).

import { useEffect, useRef, useState } from "react";
import { useMap } from "react-leaflet";
import type L from "leaflet";
import axios from "axios";
// @ts-expect-error -- georaster ships without types
import parseGeoraster from "georaster";
import GeoRasterLayer from "georaster-layer-for-leaflet";

import DATA_BASE_URL from "../config";

const CANOPY_FILL = "#40916c";

interface CanopyMaskLayerProps {
  s3Key: string;
  opacity?: number;
  onError?: (message: string) => void;
}

export function CanopyMaskLayer({ s3Key, opacity = 0.6, onError }: CanopyMaskLayerProps) {
  const map = useMap();
  const layerRef = useRef<L.Layer | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function addLayer() {
      try {
        const res = await axios.get(`${DATA_BASE_URL}/${s3Key}`, {
          responseType: "arraybuffer",
        });
        if (cancelled) return;

        const georaster = await parseGeoraster(res.data);

        const layer = new GeoRasterLayer({
          georaster,
          opacity,
          resolution: 128,
          pixelValuesToColorFn: (values: number[]) => {
            const v = values[0];
            if (v === undefined || v === null || Number.isNaN(v) || v === 0) {
              return null; // transparent -- no canopy
            }
            return CANOPY_FILL;
          },
        });

        layer.addTo(map);
        layerRef.current = layer;
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setError(message);
        onError?.(message);
      }
    }

    addLayer();
    return () => {
      cancelled = true;
      if (layerRef.current) {
        map.removeLayer(layerRef.current);
        layerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s3Key]);

  if (error) {
    return (
      <div className="raster-error-banner">
        Couldn't load canopy mask: {error}
      </div>
    );
  }
  return null;
}
