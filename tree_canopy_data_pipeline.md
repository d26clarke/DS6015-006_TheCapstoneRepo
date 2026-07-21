# Central Virginia Tree Canopy Study — Data Pipeline Documentation

## Overview

This document describes the end-to-end data acquisition and processing pipeline for
the Central Virginia Tree Canopy Study, which integrates three NASA/USGS remote
sensing data sources to assess tree canopy structure, canopy change, and the
environmental conditions (soil moisture) that influence canopy health across nine
Central Virginia jurisdictions plus the City of Charlottesville.

| Data Source | Provider | Native Resolution | Primary Role |
|---|---|---|---|
| VGIN/USGS 3DEP LiDAR (`.laz`) | Virginia Geographic Information Network | 1 m | High-resolution canopy structure, CHM, canopy cover |
| GEDI Level 2A (`GEDI02_A`) | NASA (spaceborne LiDAR) | ~25 m footprint | Direct canopy height validation |
| GEDI Level 2B (`GEDI02_B`) | NASA (spaceborne LiDAR) | ~25 m footprint | Canopy cover fraction, plant area index |
| SMAP Enhanced L3 (`SPL3SMP_E`) | NASA/NSIDC | 9 km | Soil moisture as a tree-stress indicator |

### Relevance of the GEDI HDF5 products to canopy change detection

For tree canopy change detection over Charlottesville, the most relevant NASA HDF5
datasets are:

| Dataset | Short Name | Description | Relevance |
|---|---|---|---|
| GEDI Level 2A | `GEDI02_A` | Spaceborne LiDAR canopy height (`.h5`) | Direct canopy height validation |
| GEDI Level 2B | `GEDI02_B` | Canopy cover, plant area index (`.h5`) | Canopy cover metrics |

GEDI's spaceborne footprints act as an independent, satellite-based cross-check
against the much higher-resolution VGIN airborne LiDAR — useful both for validating
the VGIN-derived Canopy Height Model (CHM) and for filling temporal gaps between
VGIN acquisition epochs (VGIN LiDAR is flown periodically per county; GEDI has been
continuously collecting since April 2019).

---

## 1. VGIN LiDAR Data Download Pipeline

VGIN (Virginia Geographic Information Network) LiDAR `.laz` data is the primary
high-resolution data source for this project. This highly accurate 3D point cloud
data meets USGS 3DEP specification, making it the industry standard for analyzing
vegetation structure, creating Canopy Height Models (CHM), and calculating canopy
cover percentages. The Virginia LiDAR Inventory Web Mapping Application provides
access to Virginia's most recent LiDAR point cloud, bare-earth Digital Elevation
Models (DEMs), and individual project metadata collected in the Commonwealth of
Virginia according to the USGS 3DEP specification, linking to resources and data
from NOAA and USGS data portals.

### Step 1 — Tile query per jurisdiction

Execute the county-specific tile query notebook in AWS SageMaker:

```
1_CentralVA_LiDAR_TileQuery-<COUNTY>.ipynb
```

where `<COUNTY>` is one of:

```
albemarle, augusta, buckingham, cville, fluvanna,
greene, louisa, nelson, orange, rockingham
```

This notebook queries the VGIN tile inventory for each jurisdiction and produces a
tile-list CSV (`CentralVA_LiDAR_<County>.csv`) identifying the `.laz`/DEM source
URLs to be processed.

### Step 2 — Submit LiDAR processing jobs

From an AWS SageMaker JupyterLab session:

```
launch_lidar_sagemaker_job.py
```

County and year are derived automatically from the S3 input path:

```
s3://central-virginia-tree-canopy-project/data/outputs/<County>/CentralVA_LiDAR_<County>.csv
```

The processing script receives the full S3 input path as an environment variable
(`SM_INPUT_CSV_S3`) and parses county and year from it at runtime.

**Usage — single county:**
```bash
python launch_lidar_sagemaker_job.py --county Albemarle --csv-file CentralVA_LiDAR_Albemarle.csv
```

**Usage — all nine counties in parallel:**
```bash
python launch_lidar_sagemaker_job.py --all
```

**Usage — override instance type:**
```bash
python launch_lidar_sagemaker_job.py --county Nelson --csv-file CentralVA_LiDAR_Albemarle.csv --instance-type ml.c5.2xlarge
```

---

## 2. SMAP Data Download Pipeline

### What SMAP is and what it measures

The Soil Moisture Active Passive (SMAP) satellite, operated by NASA since April
2015, measures surface soil moisture in the top 5 cm of the soil column using an
L-band radiometer. It covers the entire globe every 2–3 days. Data is archived and
distributed by NSIDC at [nsidc.org/data/smap](https://nsidc.org/data/smap).

### Resolution consideration for Central Virginia counties

This is the most important practical constraint to understand. At 36 km
resolution (the standard L3 product), a single SMAP pixel covers approximately
1,296 km². For reference:

- Albemarle County is approximately 1,875 km² — covered by roughly 1–2 pixels.
- Fluvanna and Greene counties are each under 700 km².

At **9 km resolution** (the Enhanced L3 product, `SPL3SMP_E`), each pixel covers
approximately 81 km², which provides meaningful spatial differentiation across our
selected county study area. This project uses `SPL3SMP_E` for that reason.

### What SMAP data provides for the Tree Canopy Project

| Application | How SMAP Helps |
|---|---|
| Soil moisture as a tree-stress indicator | Low soil moisture periods correlate with canopy dieback and reduced tree health |
| Seasonal analysis | Identify drought stress periods (summer) vs. recovery periods (spring/fall) |
| Complement to LiDAR | LiDAR captures canopy structure; SMAP captures soil moisture conditions that drive canopy health |
| Root zone moisture (L4) | The L4 product estimates moisture in the top 1 m of soil — more relevant to tree root systems than surface-only measurements |

### Download procedure

Using the `earthaccess_download-SMAP.py` script and Earthdata Login credentials,
SMAP data was downloaded to a UVA HPC account, batched temporally within the
Central Virginia Tree Canopy Study bounding box:

```python
import earthaccess

# 1. Authenticate (will prompt for your Earthdata username and password)
auth = earthaccess.login()

# 2. Search for SMAP data using a shortname and temporal/spatial bounds
results = earthaccess.search_data(
    short_name   = "SPL3SMP_E",
    version      = "006",
    bounding_box = (-79.1721, 37.3296, -77.6873, 38.4755),
    temporal     = ("2023-01-01", "2023-12-31")
)
print(f"Granules found: {len(results)}")

files = earthaccess.download(
    results,
    local_path = "/scratch/thq3hn/smap_h5/"
)
```

Each calendar year (2015–2023, with 2015 starting at the SMAP mission's April 2015
launch) was pulled as a separate temporal batch.

### Upload to S3

Upon completion, SMAP `.h5` files were uploaded to S3:

```bash
aws s3 cp . s3://central-virginia-tree-canopy-project/SMAP/ \
    --recursive --exclude "*" --include "SMAP_L3_SM_P_E_*.h5"
```

```
aws s3 ls s3://central-virginia-tree-canopy-project/SMAP/ | head -n 10
2026-06-07 20:11:08          0
2026-06-07 20:17:12  664413999 SMAP_L3_SM_P_E_20150401_R19240_001.h5
2026-06-07 20:17:15  687231081 SMAP_L3_SM_P_E_20150402_R19240_001.h5
2026-06-07 20:17:17  568766935 SMAP_L3_SM_P_E_20150403_R19240_001.h5
2026-06-07 20:17:19  677967098 SMAP_L3_SM_P_E_20150404_R19240_001.h5
2026-06-07 20:17:21  681731580 SMAP_L3_SM_P_E_20150405_R19240_001.h5
2026-06-07 20:17:24  675664783 SMAP_L3_SM_P_E_20150406_R19240_001.h5
2026-06-07 20:17:26  687749462 SMAP_L3_SM_P_E_20150407_R19240_001.h5
2026-06-07 20:17:29  671183019 SMAP_L3_SM_P_E_20150408_R19240_001.h5
2026-06-07 20:17:32  683420481 SMAP_L3_SM_P_E_20150409_R19240_001.h5
```

---

## 3. GEDI Level 2A / Level 2B Data Download Pipeline

### Download procedure

Using the `earthaccess_download-GEDI.py` script and Earthdata Login credentials,
GEDI data was downloaded to a UVA HPC account using the same temporal-batching
approach as the SMAP pipeline:

```python
import earthaccess

# 1. Authenticate (will prompt for your Earthdata username and password)
auth = earthaccess.login()

# 2. Search for GEDI data using a shortname and temporal/spatial bounds
results = earthaccess.search_data(
    short_name   = "GEDI02_A",   # or "GEDI02_B"
    version      = "002",
    bounding_box = (-79.1721, 37.3296, -77.6873, 38.4755),
    temporal     = ("2019-04-04", "2025-07-10")
)
print(f"Granules found: {len(results)}")

files = earthaccess.download(
    results,
    local_path = "/scratch/thq3hn/gedi_h5/"
)
```

This search spans the full GEDI mission-to-date record (April 2019 onward) within
the Central Virginia Tree Canopy Study bounding box, rather than being split into
strict calendar-year batches the way the SMAP download was.

### Upload to S3

```bash
aws s3 cp . s3://central-virginia-tree-canopy-project/GEDI/GEDI02_A/002/ \
    --recursive --exclude "*" --include "GEDI02_A_*.h5"

aws s3 cp . s3://central-virginia-tree-canopy-project/GEDI/GEDI02_B/002/ \
    --recursive --exclude "*" --include "GEDI02_B_*.h5"
```

```
aws s3 ls s3://central-virginia-tree-canopy-project/GEDI/GEDI02_A/002/ | head -n 5
2026-06-16 15:44:51          0
2026-06-23 10:00:01 1898806843 GEDI02_A_2019113174925_O02048_03_T02621_02_003_01_V002.h5
2026-06-23 10:00:01 1633190866 GEDI02_A_2019114104858_O02059_02_T02479_02_003_01_V002.h5
2026-06-23 10:00:01 1631062985 GEDI02_A_2019120150653_O02155_03_T00892_02_003_01_V002.h5
2026-06-23 10:00:01 2469629403 GEDI02_A_2019121080625_O02166_02_T05019_02_003_01_V002.h5

aws s3 ls s3://central-virginia-tree-canopy-project/GEDI/GEDI02_B/002/ | head -n 5
2026-06-16 15:47:02          0
2026-06-16 21:15:05  416704125 GEDI02_B_2019113174925_O02048_03_T02621_02_003_01_V002.h5
2026-06-16 21:15:05  306558748 GEDI02_B_2019114104858_O02059_02_T02479_02_003_01_V002.h5
2026-06-16 21:15:05  334727765 GEDI02_B_2019120150653_O02155_03_T00892_02_003_01_V002.h5
2026-06-16 21:15:05  577550109 GEDI02_B_2019121080625_O02166_02_T05019_02_003_01_V002.h5
```

### Processing GEDI via S3

```
launch_gedi_sagemaker_job.py
```

Submits GEDI Level 2A (canopy height) and/or Level 2B (canopy cover) processing
jobs to AWS SageMaker Processing.

> Unlike the LiDAR pipeline's launcher, no `ProcessingInput` is needed here —
> `process_gedi02A_from_s3.py` / `process_gedi02B_from_s3.py` each discover their
> own input `.h5` files directly from S3 via boto3's `list_objects_v2` paginator
> at runtime, rather than reading a pre-built tile-list CSV.
>
> A `ProcessingOutput` channel **is** still needed, though: the scripts explicitly
> upload the county-summary and detailed CSVs to S3 themselves via boto3, but the
> Parquet (multi-year point extract) and NetCDF (SMAP-grid) outputs are only ever
> written to local disk — without a `ProcessingOutput` syncing
> `/opt/ml/processing/output` back to S3, those two files would be silently lost
> when the container tears down at job end.

**Usage — canopy height (GEDI L2A) only:**
```bash
python launch_gedi_sagemaker_job.py --product 02A
```

**Usage — canopy cover (GEDI L2B) only:**
```bash
python launch_gedi_sagemaker_job.py --product 02B
```

**Usage — both, submitted in parallel:**
```bash
python launch_gedi_sagemaker_job.py --product both
```

**Usage — override instance type or worker count:**
```bash
python launch_gedi_sagemaker_job.py --product 02A --instance-type ml.r5.4xlarge --workers 24
```

---

## 4. Integrating LiDAR Canopy Structure with SMAP Soil Moisture

### Conceptual framework

The integration works by combining two fundamentally different data types at
compatible spatial scales. LiDAR provides high-resolution (sub-meter to 1 m)
structural measurements of the tree canopy — height, density, and cover fraction.
SMAP provides coarser-resolution (9 km) soil moisture measurements that drive
physiological tree stress. The analytical workflow resamples and spatially joins
these datasets so that each canopy unit carries an associated soil moisture value,
enabling correlation and stress classification.

| Data Layer | Source | Native Resolution | Key Variable |
|---|---|---|---|
| LiDAR Canopy Height Model (CHM) | VGIN / USGS 3DEP | 1 m | Tree height, canopy structure |
| LiDAR Canopy Cover Fraction | Derived from CHM | 1 m | Percent canopy cover per unit area |
| SMAP Enhanced L3 Soil Moisture | NSIDC `SPL3SMP_E` | 9 km | Volumetric surface soil moisture (m³/m³) |

### Key limitation to document

The fundamental resolution mismatch — 1 m LiDAR versus 9 km SMAP — means that SMAP
cannot resolve individual tree stress at the stand or parcel level. Each 9 km SMAP
pixel covers approximately 81 km² and averages soil moisture across many land cover
types (forest, agriculture, impervious surface). The integration is therefore most
valid at the **landscape and county scale** rather than for individual trees or
small forest patches. For finer-scale soil moisture, the SMAP/Sentinel-1 3 km
product (`SPL3SMP_SP`) or ground-based sensor networks would be needed to
complement the analysis.

### Important caveat for Charlottesville

At 9 km spatial resolution, each SMAP pixel covers ~81 km² — roughly **3× the area
of Charlottesville (26.5 km²)**. The entire city falls within 1–2 SMAP pixels. This
means `SPL3SMP_E` is **not** suitable for spatially resolved intra-city analysis,
but it is well-suited for:

- Time-series analysis of soil moisture conditions over Charlottesville across
  2015–present.
- Seasonal and drought context for interpreting canopy health and tree stress in
  the CHM.
- Pre/post event analysis — correlating soil moisture anomalies with canopy change
  between LiDAR epochs (e.g. 2015 vs. 2020).

---

## Pipeline Summary Diagram

```
                     ┌───────────────────────────┐
                     │   Earthdata Login (NASA)   │
                     └─────────────┬─────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                     │
     VGIN Web Mapping App     earthaccess (SMAP)   earthaccess (GEDI 02A/02B)
   (per-county tile query)     → UVA HPC scratch    → UVA HPC scratch
              │                    │                     │
              ▼                    ▼                     ▼
   1_CentralVA_LiDAR_        aws s3 cp --recursive   aws s3 cp --recursive
   TileQuery-<COUNTY>.ipynb  (SMAP/*.h5)              (GEDI/GEDI02_A|B/002/*.h5)
              │                    │                     │
              ▼                    │                     ▼
  launch_lidar_sagemaker_job.py    │          launch_gedi_sagemaker_job.py
   (per county / --all)           │           (--product 02A | 02B | both)
              │                    │                     │
              ▼                    │                     ▼
  sagemaker_process_lidar.py       │          process_gedi02A_from_s3.py
   → CHM, canopy mask,             │          process_gedi02B_from_s3.py
     centroids, cover CSV          │           → canopy height / cover
     per tile, per county          │             county summaries
              │                    │                     │
              └────────────────────┴─────────────────────┘
                                   │
                                   ▼
                  Central Virginia Tree Canopy Dashboard
              (SplitPanelDashboard, LidarCanopyPanel, etc.)
```
