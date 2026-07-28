import DATA_BASE_URL from "../config";

export default function Header() {
  return (
    <header style={{
      background: "#1b4332", color: "#fff",
      padding: "1rem 2rem", display: "flex",
      alignItems: "center", justifyContent: "space-between"
    }}>
      <div>
        <h1 style={{ margin: 0, fontSize: "1.4rem" }}>
          Central Virginia Tree Canopy Study
        </h1>
        <p style={{ margin: 0, fontSize: "0.85rem", opacity: 0.8 }}>
          City of Charlottesville + 6 Counties
          USGS 3DEP LiDAR 2015–2020 
          SMAP SPL3SMP_E  2019 - 2023 
          GEDI Level 2A 2019 - 2025 
          GEDI Level 2B 2019 - 2025 
        </p>
      </div>
      <a
        href={`${DATA_BASE_URL}/methodology.html`}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          color: "#d8f3dc", fontWeight: 600, fontSize: "0.9rem",
          textDecoration: "none", border: "1px solid #d8f3dc",
          padding: "0.4rem 0.9rem", borderRadius: "4px"
        }}
      >
        View Methodology Notebook →
      </a>
    </header>
  );
}