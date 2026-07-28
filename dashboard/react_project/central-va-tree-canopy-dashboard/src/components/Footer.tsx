import { useEffect, useState } from "react";
import axios from "axios";
import DATA_BASE_URL from "../config";

interface Metadata {
  project_title: string;
  last_updated: string;
}

export default function Footer() {
  const [meta, setMeta] = useState<Metadata | null>(null);

  useEffect(() => {
    axios.get<Metadata>(`${DATA_BASE_URL}/metadata.json`)
      .then(res => setMeta(res.data));
  }, []);

  return (
    <footer style={{
      background: "#f1f8f4", borderTop: "1px solid #b7e4c7",
      padding: "1rem 2rem", fontSize: "0.8rem", color: "#555",
      display: "flex", justifyContent: "space-between"
    }}>
      <span>
        University of Virginia · 2026 Data Science Capstone · Project ·{" "}
        {meta ? meta.project_title : "Central Virginia Tree Canopy Study"}
      </span>
      <span>Last updated: {meta ? meta.last_updated : "—"}</span>
    </footer>
  );
}