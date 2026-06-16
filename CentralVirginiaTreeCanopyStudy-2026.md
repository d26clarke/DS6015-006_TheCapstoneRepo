# Central Virginia Tree Canopy Study — 2026

> A NASA Earth observation analysis of the relationship between surface soil moisture and forest canopy structural height across eight jurisdictions in Central Virginia, using SMAP and GEDI satellite data.

---

## Overview

This repository contains all data processing pipelines, analysis notebooks, and visualization code for the **2026 Central Virginia Tree Canopy Study**. The study investigates how multi-year variability in surface soil moisture — as measured by NASA's Soil Moisture Active Passive (SMAP) satellite — relates to forest canopy height — as measured by NASA's Global Ecosystem Dynamics Investigation (GEDI) lidar instrument — across the Central Virginia study area from 2019 to 2023.

The analysis supports the capstone report submitted to [Institution Name] and provides evidence-based findings relevant to regional forest management, drought monitoring, and tree canopy conservation policy.

---

## Study Area

The study covers eight jurisdictions in Central Virginia:

| Jurisdiction | Type |
|---|---|
| Albemarle County | County |
| Augusta County | County |
| City of Charlottesville | Independent City |
| Fluvanna County | County |
| Greene County | County |
| Louisa County | County |
| Nelson County | County |
| Rockingham County | County |

---

## Data Sources

| Dataset | Product | Version | Temporal Coverage | Resolution | Provider |
|---|---|---|---|---|---|
| SMAP Surface Soil Moisture | `SPL3SMP_E` | `006` | 2015–2023 | 9 km (enhanced) | NASA NSIDC |
| GEDI Canopy Height | `GEDI02_A` | `002` | 2019–2025 | ~25 m footprint | NASA LPDAAC |

### Raw Data Storage (AWS S3)

| File | S3 URI |
|---|---|
| SMAP annual summary | `s3://central-virginia-tree-canopy-project/smap-annual-means/smap_annual_summary.csv` |
| GEDI county summary | `s3://central-virginia-tree-canopy-project/gedi-county-summary/virginia_gedi_county_summary.csv` |

> **Note:** Raw data files are not committed to this repository. See [Data Access](#data-access) below for retrieval instructions.

---

## Repository Structure

```
central-virginia-tree-canopy/
│
├── notebooks/
│   ├── merge_smap_gedi_visuals.ipynb   # Main analysis: merge, lag analysis, all 7 visuals
│   └── using_gedi_data_visuals.ipynb   # Reference notebook for GEDI visualization patterns
│
├── scripts/
│   ├── fix_cloudfront_s3_policy.sh     # CloudFront OAC / S3 bucket policy fix script
│   └── pipeline_user_policy_patch.json # IAM policy patch for tree-canopy-pipeline-user
│
├── data/                               # Local data cache (git-ignored; populated at runtime)
│   ├── smap_annual_summary.csv
│   └── virginia_gedi_county_summary.csv
│
├── outputs/                            # Generated JSON exports (git-ignored; uploaded to S3)
│   ├── smap_timeseries.json
│   ├── gedi_county_summary.json
│   ├── merged_smap_gedi.json
│   └── pearson_r_matrix.json
│
├── visuals/                            # Exported HTML visuals (git-ignored; uploaded to S3)
│   ├── visual1_smap_timeseries.html
│   ├── visual2_gedi_canopy_bars.html
│   ├── visual3_dual_axis_facet.html
│   ├── visual4_scatter_correlation.html
│   ├── visual5_lag_regression_panels.html
│   ├── visual6_pearson_heatmap.html
│   └── visual7_regional_dual_axis.html
│
├── .env.example                        # Environment variable template (tracked)
├── .gitignore                          # Git ignore rules
└── README.md                           # This file
```

---

## Analysis Notebooks

### `merge_smap_gedi_visuals.ipynb`

The primary analysis notebook. It performs the following steps in sequence:

1. **Environment setup** — installs `plotly`, `nbformat`, `ipywidgets`, and `scipy` if not present.
2. **Configuration** — defines S3 bucket paths, color palettes, and output directories.
3. **Data loading** — reads SMAP and GEDI CSVs directly from S3 using `pandas`.
4. **Data merging** — performs an inner join on `year`, broadcasting the region-wide SMAP value across all counties for each year. The overlap window is 2019–2023 (38 observations across 8 jurisdictions).
5. **Temporal lag construction** — creates 1-year and 2-year lagged soil moisture columns within each jurisdiction group using `.shift()`.
6. **Visual generation** — produces all seven interactive Plotly visuals described below.
7. **JSON export** — serializes all outputs to JSON using a NaN-safe helper and uploads to three S3 destinations.

### Visuals Generated

| Visual | File | Description |
|---|---|---|
| 1 | `visual1_smap_timeseries.html` | SMAP annual soil moisture time series (2015–2023) with ±1 std band and GEDI overlap window |
| 2 | `visual2_gedi_canopy_bars.html` | GEDI mean canopy height (rh98) by jurisdiction and year, faceted bar chart (2019–2025) |
| 3 | `visual3_dual_axis_facet.html` | County-level dual-axis facet: soil moisture (left) and canopy height (right) per jurisdiction |
| 4 | `visual4_scatter_correlation.html` | Eco-hydrological scatter with OLS trend line (r = 0.351, p = 0.031) |
| 5 | `visual5_lag_regression_panels.html` | Lagged cross-correlation regression: same-year, 1-year lag, 2-year lag panels |
| 6 | `visual6_pearson_heatmap.html` | Pearson r heatmap by jurisdiction and lag configuration |
| 7 | `visual7_regional_dual_axis.html` | Regional dual-axis eco-hydrological trend (SMAP full record + GEDI regional average) |

---

## Key Findings

**1. Statistically significant positive correlation.** Across the 2019–2023 overlap window, higher surface soil moisture is associated with taller forest canopy (Pearson r = 0.351, p = 0.031), consistent with established forest eco-hydrological theory.

**2. Dominant 2-year hydrological lag.** Per-jurisdiction lagged correlation analysis reveals that the strongest soil moisture–canopy height relationships occur with a two-year delay. Greene County shows r = 0.999 at 2-year lag; Louisa County shows r = 0.887; Augusta County shows r = 0.873. This suggests that canopy structural response to hydrological stress manifests approximately two growing seasons after the moisture deficit event.

**3. Spatial heterogeneity.** Rockingham County shows near-zero or negative correlations across all lag configurations, diverging markedly from the other seven jurisdictions. This likely reflects its higher proportion of agricultural land use and distinct topographic profile, and argues against uniform regional canopy management policies.

**4. Regional decline 2019–2023.** Regional mean canopy height declined from approximately 17.4 m in 2019 to 14.1 m in 2023 (−19%), coinciding with a decline in regional mean soil moisture from 0.380 to 0.271 m³/m³ (−29%).

> **Critical Data Quality Note:** The 2019 SMAP annual mean (0.380 m³/m³) is derived from only **32 valid observation days** (January–February 2019), compared to 273–366 days for all other years in the record. Winter soil moisture is systematically elevated due to near-zero evapotranspiration. This value should be interpreted as a winter mean, not a true annual mean, and must be disclosed in any report or policy document that references the 2019 SMAP value.

---

## S3 Output Destinations

All JSON exports and HTML visuals are uploaded to the following three S3 locations at the end of the notebook run:

| Bucket | Prefix | Purpose |
|---|---|---|
| `central-virginia-tree-canopy-project` | `dashboard-data/` | Project data archive |
| `central-va-tree-canopy-dashboard` | `dashboard-data/` | Dashboard data feed |
| `central-va-tree-canopy-dashboard` | `data/` | Dashboard legacy data path |

---

## Data Access

### Prerequisites

- AWS CLI configured with credentials that have `s3:GetObject` access to `central-virginia-tree-canopy-project`.
- Python 3.9 or later.
- An active Amazon SageMaker environment, or a local Jupyter installation.

### Retrieving Data Locally

```bash
# SMAP annual summary
aws s3 cp s3://central-virginia-tree-canopy-project/smap-annual-means/smap_annual_summary.csv \
    data/smap_annual_summary.csv

# GEDI county summary
aws s3 cp s3://central-virginia-tree-canopy-project/gedi-county-summary/virginia_gedi_county_summary.csv \
    data/virginia_gedi_county_summary.csv
```

### Running the Notebook in SageMaker

```bash
# Upload notebook to S3
aws s3 cp notebooks/merge_smap_gedi_visuals.ipynb \
    s3://central-virginia-tree-canopy-project/scripts/notebooks/merge_smap_gedi_visuals.ipynb

# Pull into SageMaker JupyterLab terminal
aws s3 cp s3://central-virginia-tree-canopy-project/scripts/notebooks/merge_smap_gedi_visuals.ipynb \
    /home/ec2-user/SageMaker/merge_smap_gedi_visuals.ipynb
```

Open the notebook in JupyterLab, select the **`conda_python3`** kernel, and run **Run → Run All Cells**.

---

## Environment Setup

Copy the environment template and populate with your credentials:

```bash
cp .env.example .env.local
```

The `.env.example` file contains the following keys (values intentionally blank):

```
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_DEFAULT_REGION=
S3_BUCKET_PROJECT=
S3_BUCKET_DASHBOARD=
```

> **Never commit `.env.local` or any file containing real credentials.** The `.gitignore` in this repository excludes all `.env*` variants except `.env.example`.

---

## Infrastructure Notes

### CloudFront + S3 Bucket Policy

The dashboard bucket (`central-va-tree-canopy-dashboard`) is served via Amazon CloudFront using an Origin Access Control (OAC) configuration. If the CloudFront distribution returns 403 errors after a bucket policy change, run the fix script:

```bash
chmod +x scripts/fix_cloudfront_s3_policy.sh
./scripts/fix_cloudfront_s3_policy.sh
```

The script automatically detects whether the distribution uses OAC or OAI, writes the correct bucket policy, and submits a `/*` cache invalidation.

---

## Contributing

This repository is maintained as part of an academic capstone project. If you are onboarding as a collaborator:

1. Clone the repository and copy `.env.example` to `.env.local`.
2. Populate `.env.local` with your AWS credentials (obtain from the project administrator).
3. Run `pip install -r requirements.txt` (or use the SageMaker `conda_python3` kernel, which includes all required packages).
4. Never commit data files, build outputs, or environment files. Refer to `.gitignore` for the full exclusion list.

---

## License

This project is developed for academic research purposes. Data products are sourced from NASA's open-access Earth observation archives. All analysis code in this repository is released under the [MIT License](LICENSE).

---

## Contact

For questions about this study, please contact the project team through the repository issue tracker.

---

*Last updated: June 2026*
*Data sources: NASA SMAP SPL3SMP_E v006 | NASA GEDI GEDI02_A v002*
*Study area: Central Virginia, United States*
