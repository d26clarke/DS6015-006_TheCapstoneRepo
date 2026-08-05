// ─── VisualizationGallery.tsx ────────────────────────────────────────────────
// Gallery for the ~40 standalone HTML visualization exports under
// s3://central-va-tree-canopy-dashboard/data/html-files/visualizations/.
//
// Each file is a full nbconvert/Plotly-style standalone HTML document (own
// <html>/<head>/<body>, embedded CSS, external scripts) -- rendered via
// <iframe>, never injected into the page directly, since that would collide
// with the dashboard's own styles and scripts.

import { useMemo, useState } from "react";
import {
  GALLERY_ENTRIES,
  PRODUCT_LABELS,
  SUB_AREA_LABELS,
  galleryEntryUrl,
} from "../htmlGalleryData";
import type { Product, VisualEntry } from "../htmlGalleryData";

const PRODUCTS: Product[] = ["canopy_height", "canopy_cover"];

export default function VisualizationGallery() {
  const [product, setProduct] = useState<Product>("canopy_height");
  const entries = useMemo(
    () => GALLERY_ENTRIES.filter((e) => e.product === product),
    [product]
  );

  const grouped = useMemo(() => {
    const byVisual = new Map<number, VisualEntry[]>();
    for (const e of entries) {
      const list = byVisual.get(e.visualNumber) ?? [];
      list.push(e);
      byVisual.set(e.visualNumber, list);
    }
    return [...byVisual.entries()].sort((a, b) => a[0] - b[0]);
  }, [entries]);

  const [selected, setSelected] = useState<VisualEntry | null>(entries[0] ?? null);

  function handleProductChange(p: Product) {
    setProduct(p);
    const first = GALLERY_ENTRIES.find((e) => e.product === p) ?? null;
    setSelected(first);
  }

  return (
    <section style={{ padding: "1.5rem 2rem", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem", flexWrap: "wrap", gap: "0.5rem" }}>
        <h2 style={{ color: "#1b4332", margin: 0 }}>Visualization Gallery</h2>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          {PRODUCTS.map((p) => (
            <button
              key={p}
              onClick={() => handleProductChange(p)}
              style={{
                padding: "0.4rem 0.9rem",
                borderRadius: "4px",
                border: p === product ? "2px solid #1b4332" : "1px solid #ccc",
                background: p === product ? "#d8f3dc" : "#fff",
                fontWeight: p === product ? 700 : 400,
                cursor: "pointer",
              }}
            >
              {PRODUCT_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: "1.5rem" }}>
        {/* ── Left: grid of visual types, grouped ────────────────────────── */}
        <div>
          {grouped.map(([visualNumber, group]) => (
            <div key={visualNumber} style={{ marginBottom: "1rem", border: "1px solid #e0e0e0", borderRadius: "6px", padding: "0.6rem" }}>
              <div style={{ fontWeight: 700, fontSize: "0.85rem", color: "#1b4332", marginBottom: "0.4rem" }}>
                {group[0].label.replace(/ \([AB]\)$/, "")}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
                {group.map((entry) => {
                  const pillLabel = entry.subArea
                    ? (SUB_AREA_LABELS[entry.subArea] ?? entry.subArea)
                    : entry.label.match(/\(([AB])\)$/)?.[1]
                    ? `Version ${entry.label.match(/\(([AB])\)$/)![1]}`
                    : "Region-wide";
                  const isActive = selected?.filename === entry.filename;
                  return (
                    <button
                      key={entry.filename}
                      onClick={() => setSelected(entry)}
                      style={{
                        fontSize: "0.72rem",
                        padding: "0.25rem 0.55rem",
                        borderRadius: "12px",
                        border: isActive ? "1px solid #1b4332" : "1px solid #ccc",
                        background: isActive ? "#1b4332" : "#f8faf8",
                        color: isActive ? "#fff" : "#333",
                        cursor: "pointer",
                      }}
                    >
                      {pillLabel}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* ── Right: preview of selected visualization ────────────────────── */}
        <div>
          {selected ? (
            <>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.5rem" }}>
                <h3 style={{ margin: 0, fontSize: "1rem", color: "#1b4332" }}>
                  {selected.label.replace(/ \([AB]\)$/, "")}
                  {selected.subArea && ` — ${SUB_AREA_LABELS[selected.subArea] ?? selected.subArea}`}
                </h3>
                <a
                  href={galleryEntryUrl(selected)}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ fontSize: "0.8rem", color: "#1b4332", fontWeight: 600 }}
                >
                  Open in new tab ↗
                </a>
              </div>
              <iframe
                src={galleryEntryUrl(selected)}
                title={selected.filename}
                style={{ width: "100%", height: "70vh", border: "1px solid #ccc", borderRadius: "6px" }}
              />
            </>
          ) : (
            <p style={{ color: "#666" }}>Select a visualization from the left.</p>
          )}
        </div>
      </div>
    </section>
  );
}
