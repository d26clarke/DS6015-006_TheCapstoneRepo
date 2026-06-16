import h5py
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

ALBEMARLE_BBOX = (-78.8389, 37.7226, -78.2094, 38.2779)

# Dataset name mapping per overpass group 
# AM datasets have plain names; PM datasets carry a '_pm' suffix.
OVERPASS_CONFIG = {
    "Soil_Moisture_Retrieval_Data_AM": {
        "sm":   "soil_moisture",
        "lat":  "latitude",
        "lon":  "longitude",
        "flag": "retrieval_qual_flag",
        "label": "AM",
    },
    "Soil_Moisture_Retrieval_Data_PM": {
        "sm":   "soil_moisture_pm",
        "lat":  "latitude_pm",
        "lon":  "longitude_pm",
        "flag": "retrieval_qual_flag_pm",
        "label": "PM",
    },
}

records = []

for filepath in sorted(Path("../data/smap_data/").glob("*.h5")):

    # Extract date from filename: SMAP_L3_SM_P_E_YYYYMMDD_...
    date_str = filepath.stem.split("_")[5]
    date = datetime.strptime(date_str, "%Y%m%d")

    with h5py.File(filepath, "r") as f:

        for group_name, keys in OVERPASS_CONFIG.items():

            # Skip if this overpass group is absent (some files omit PM)
            if group_name not in f:
                continue

            grp = f[group_name]

            # Guard: confirm all required datasets exist in this group
            missing = [v for v in (keys["sm"], keys["lat"], keys["lon"], keys["flag"])
                       if v not in grp]
            if missing:
                print(f"  WARNING: {filepath.name} / {group_name} missing datasets: {missing}")
                continue

            sm   = grp[keys["sm"]][:]
            lat  = grp[keys["lat"]][:]
            lon  = grp[keys["lon"]][:]
            flag = grp[keys["flag"]][:]

            # Apply fill value mask (-9999.0 is the documented _FillValue)
            sm = np.where(sm == -9999.0, np.nan, sm)

            # Spatial subset: keep only pixels within Albemarle bounding box
            mask = (
                (lat >= ALBEMARLE_BBOX[1]) & (lat <= ALBEMARLE_BBOX[3]) &
                (lon >= ALBEMARLE_BBOX[0]) & (lon <= ALBEMARLE_BBOX[2])
            )

            if not np.any(mask):
                continue

            lats_sub = lat[mask]
            lons_sub = lon[mask]
            sm_sub   = sm[mask]
            flag_sub = flag[mask]

            for i in range(len(lats_sub)):
                records.append({
                    "date":                date.strftime("%Y-%m-%d"),
                    "overpass":            keys["label"],
                    "latitude":            round(float(lats_sub[i]), 4),
                    "longitude":           round(float(lons_sub[i]), 4),
                    "soil_moisture_m3m3":  round(float(sm_sub[i]), 4)
                                           if not np.isnan(sm_sub[i]) else None,
                    "quality_flag":        int(flag_sub[i]),
                })

df = pd.DataFrame(records)

out_path = Path("../data/outputs/albemarle_smap_soil_moisture.csv")
out_path.parent.mkdir(parents=True, exist_ok=True)
df.to_csv("../data/outputs/albemarle_smap_soil_moisture.csv", index=False)

print(f"Extracted {len(df)} pixel-date records")
print(df.head())

