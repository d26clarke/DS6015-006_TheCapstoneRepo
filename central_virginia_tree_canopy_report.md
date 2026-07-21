# Central Virginia Tree Canopy Policy and Benefits

## Draft Capstone Report — UVA School of Data Science, 2026

## Executive Summary

This report responds to the sponsor's request for data science support across three study areas: tree canopy and ecosystem services, invasive species management, and policy decision-making and impact modeling for Central Virginia. The project team designed and implemented an end-to-end data pipeline integrating airborne LiDAR (VGIN/USGS 3DEP), NASA GEDI spaceborne LiDAR (Level 2A canopy height, Level 2B canopy cover), NASA SMAP soil moisture, and county-level administrative data (education, crime, health, demographic) across nine Central Virginia jurisdictions plus the City of Charlottesville. The team built production SageMaker processing pipelines, a hierarchical Bayesian forecasting model, a multivariate regression framework with built-in statistical review diagnostics, and an interactive React dashboard for sponsor and stakeholder use.

A central finding of this work is methodological as much as substantive: with only 9–10 jurisdictions in the study area, standard regression and even Bayesian techniques are highly sensitive to sample size, and several apparently "significant" results were found — on closer diagnostic inspection — to be statistical artifacts rather than real policy signals. Rather than treat this as a limitation to hide, the team built the sensitivity/robustness checking directly into the analysis pipeline, producing machine-readable "review artifacts" that flag exactly which findings should and should not be trusted, and why, in plain language. This is intended to let internal team members and the sponsor jointly approve or deny each finding before it reaches a policy recommendation.

## 1. Project Objective (per sponsor request)

The primary objective, per the sponsor's proposal, is to enhance the flow of natural and economic benefits to Central Virginia citizens by supporting public decision-making of local county, city, and planning organizations, and the missions of multiple tree-related organizations, through studies and analyses in three subject areas:

*   Tree canopy and related topics
*   Invasive species
*   Policy decision-making

The sponsor requested that deliverables apply the full spectrum of data science to the tree/ecosystem/public-policy domains, leveraging open-source remote sensing databases (LiDAR and satellite imagery), existing administrative databases, and selected policy-relevant model(s), completed during 2026.

## 2. Study Area

**Jurisdictions:** Albemarle, Augusta, Buckingham, Charlottesville (independent city), Fluvanna, Greene, Louisa, Nelson, Orange, and Rockingham.

**Bounding box (WGS84):** approximately 37.33°N to 38.85°N latitude, -79.53°W to -77.69°W longitude — computed directly from each jurisdiction's actual Census TIGER boundary polygon (not estimated), and cross-validated against published land area for each county.

**FIPS reference table:**

| Jurisdiction    | State FIPS | County/Place FIPS | Type                  |
| :-------------- | :--------- | :---------------- | :-------------------- |
| Albemarle       | 51         | 003               | County                |
| Augusta         | 51         | 015               | County                |
| Buckingham      | 51         | 029               | County                |
| Charlottesville | 51         | 14968             | Place (independent city) |
| Fluvanna        | 51         | 065               | County                |
| Greene          | 51         | 079               | County                |
| Louisa          | 51         | 109               | County                |
| Nelson          | 51         | 125               | County                |
| Orange          | 51         | 137               | County                |
| Rockingham      | 51         | 165               | County                |

**Note:** many of these localities — particularly Albemarle, Fluvanna, Greene, and Nelson — comprise the Charlottesville Metropolitan Area or fall within Virginia Planning District 10, giving the study area natural geographic and administrative coherence.

## 3. Data Sources and Acquisition Pipeline

### 3.1 VGIN / USGS 3DEP LiDAR (1 m resolution)

The Virginia Geographic Information Network's LiDAR Inventory Web Mapping Application provides access to Virginia's most recent LiDAR point cloud and bare-earth DEMs, meeting USGS 3DEP specification. This is the project's primary high-resolution data source for canopy height and canopy cover derivation.

**Pipeline (built and iteratively debugged over the course of this project):**

*   Per-county tile query notebook (1_CentralVA_LiDAR_TileQuery-<COUNTY>.ipynb) identifies relevant .laz tiles from the VGIN inventory.
*   `launch_lidar_sagemaker_job.py` submits SageMaker Processing Jobs (`sagemaker_process_lidar.py`) that download, decompress, spatially mask, and quality-filter each tile, computing per-tile Canopy Height Models (CHM), binary canopy masks, tree crown centroids (via local-maxima detection), and per-tile/county canopy cover statistics (first-return ratio and CHM cell-fraction methods).
*   Outputs are written to S3 and consumed by the dashboard.

**Notable data-quality findings from this pipeline's development, worth documenting for methodological transparency:**

*   A meaningful fraction of VGIN tiles — particularly older (2015-vintage) deliveries — were produced under an earlier USGS Lidar Base Specification whose minimum required classification scheme only mandated ground-point classification; vegetation classes were an optional add-on some vendors never populated. The pipeline was extended with a height-above-ground-derived vegetation fallback (derived_hag) to recover canopy detection for these tiles rather than silently skipping them — this affected a substantial share of processed tiles across the study counties.
*   A tile-supersession bug was found and fixed in the source-CSV parsing logic: newer LiDAR deliveries that explicitly note "Replaced VLPID##" in their metadata comment were being incorrectly excluded in favor of the older tile they were meant to replace, due to an inverted filter condition. This is now corrected and validated against real Albemarle County data.
*   Coordinate system unit-conversion bugs (Virginia State Plane US Survey Feet vs. meters) were identified and fixed; all raster/vector outputs are now confirmed to be in true meters, consistent with the project's meters-based output CRS.

### 3.2 NASA GEDI Level 2A / Level 2B (spaceborne LiDAR)

GEDI provides an independent, satellite-based cross-check against the higher-resolution VGIN data, and fills temporal gaps between VGIN acquisition epochs (GEDI has collected continuously since April 2019; VGIN flights are periodic per county).

| Dataset           | Short Name | Description                                | Relevance                      |
| :---------------- | :--------- | :----------------------------------------- | :----------------------------- |
| GEDI Level 2A     | GEDI02_A   | Spaceborne LiDAR canopy height (.h5)       | Direct canopy height validation |
| GEDI Level 2B     | GEDI02_B   | Canopy cover, plant area index (.h5)       | Canopy cover metrics           |

**Pipeline:** earthaccess-based bulk download from NASA Earthdata (bounding-box + full mission-to-date temporal query, April 2019 – July 2025) → S3 → SageMaker Processing Jobs (process_gedi02A_from_s3.py, process_gedi02B_from_s3.py) performing concurrent HDF5 extraction with spatial masking, quality filtering (quality_flag/l2b_quality_flag == 1, sensitivity > 0.9), SMAP-grid harmonization, and spatial join to jurisdiction boundaries.

**Notable findings from this pipeline's development:**

*   A prior version of the GEDI Level 2B processing notebook had a critical, previously undetected defect: a core extraction function (process_one_file) was referenced but never actually defined in the saved notebook — meaning it only ever worked in a single interactive kernel session that was never restarted, and would fail with NameError on any fresh run. This has been rebuilt as a standalone, tested script.
*   The correct GEDI Level 2B field name for canopy cover is `cover` (nested under each beam's geolocation group for lat/lon), not `canopy_cover` as an earlier version of the extraction code assumed.

### 3.3 NASA SMAP Enhanced L3 Soil Moisture (SPL3SMP_E, 9 km resolution)

The Soil Moisture Active Passive satellite (operating since April 2015) measures surface soil moisture (top 5 cm) via L-band radiometer, globally, every 2–3 days. Data is archived by NSIDC.

**Resolution constraint (documented explicitly, per sponsor/audience expectations):** at the standard 36 km L3 resolution, a single SMAP pixel (~1,296 km²) would barely resolve individual counties in this study area (Albemarle ≈ 1,875 km²; Fluvanna and Greene are each under 700 km²). The project therefore uses the Enhanced L3 product (SPL3SMP_E, 9 km resolution, ~81 km² per pixel), which provides meaningful spatial differentiation across the county study area — though this still means each SMAP pixel averages across multiple land-cover types (forest, agriculture, impervious surface) and the entire City of Charlottesville (26.5 km²) falls within only 1–2 SMAP pixels. SMAP is therefore appropriate for landscape- and county-scale time-series and drought-context analysis, not intra-city spatial resolution.

### 3.4 Administrative and Contextual Data

*   U.S. Census ACS 5-year estimates (median household income, population, educational attainment) and the Census GEOINFO dataset (land area, for population density) — 2019–2024.
*   VDOE (Virginia Department of Education) K-12 assessment/SOL pass-rate statistics.
*   CDC PLACES county-level health estimates (obesity, diabetes, poor mental health prevalence, age-adjusted, 2023 vintage — cross-sectional, not longitudinal at the county level for this study period).
*   Virginia crime statistics (UCR/NIBRS-derived county-year crime counts).

## 4. Analytical Framework

### 4.1 Tree Canopy Extraction and Change Detection

Canopy height and canopy cover fraction are computed per tile via two independent, cross-validated methods: (1) first-return ratio (vegetation-classified first laser returns ÷ total first returns — directly comparable to GEDI cover fraction) and (2) CHM cell-fraction (share of raster cells exceeding the canopy height threshold). Both methods are reported side by side in all outputs so discrepancies are visible rather than hidden behind a single number.

### 4.2 Multivariate Regression — Policy Impact Modeling

Following the sponsor's hypothesized framework —

> Higher Tree Canopy ⇒ {Higher K-12 Test Scores, Lower Crime Rates, Improved Public Health Outcomes}

— the team implemented a fixed-effects and cross-sectional regression framework:

$Y_{it} = \beta_0 + \beta_1 C_{it} + \beta_2 X_{it} + \alpha_i + \gamma_t + \epsilon_{it}$

where Y is the outcome (SOL pass rate, violent crime total, obesity/diabetes/mental-health prevalence), C is canopy cover or canopy height, and X are controls (median household income, population density, percent bachelor's-degree-or-higher). Two model specifications are used depending on whether the outcome varies over time within the panel:

*   Two-way fixed-effects panel regression (entity + time effects, clustered standard errors) for genuinely time-varying outcomes (SOL pass rate, violent crime).
*   Cross-sectional OLS for CDC PLACES health outcomes, which are single-year estimates broadcast across the panel and therefore have no within-jurisdiction time variation for a fixed-effects specification to exploit.

**Critical methodological caveat, disclosed prominently rather than buried:** with only 8–9 jurisdictions in the cross-sectional models, and only ~9 clusters in the panel models, several apparently significant findings were investigated in depth and found to be statistically fragile:

*   A canopy-cover/diabetes-prevalence relationship that initially appeared highly significant (p < 0.0001, R² = 0.967) was traced to a single jurisdiction (Charlottesville) sitting at essentially the maximum possible leverage value (hat statistic = 0.9994) in a model with only 4 residual degrees of freedom. Removing that jurisdiction did not reverse the finding's significance — but the underlying model remains near-saturated (too few observations relative to parameters) regardless, and the team's recommendation is that this result not be used for policy decisions without additional data collection.
*   A canopy-cover/violent-crime relationship (p = 0.027, two-way fixed effects) was found to be sensitive to the choice of standard error estimator: clustering by jurisdiction with only ~9 clusters is known to produce anti-conservative (artificially small) standard errors; the same model without clustering shows a p-value close to or above the conventional 0.05 threshold.

To make this kind of scrutiny a standing feature of the analysis rather than a one-time manual exercise, the team built an automated diagnostic layer (leverage/Cook's distance/VIF for cross-sectional models; clustered-vs-robust standard error sensitivity for panel models) that attaches a plain-language "confidence flag" list and a one-line recommendation to every regression result before it is presented to internal reviewers — e.g., "Do NOT use for policy decisions without further data collection — statistical result is fragile" versus "Statistically significant and passes basic robustness checks — still treat as hypothesis-generating given small N." This produces a machine-readable review artifact (JSON) intended specifically to support the internal team's approve/deny workflow for any finding before it is cited externally.

### 4.3 Bayesian Hierarchical Forecasting

A hierarchical autoregressive Bayesian model (PyMC) estimates jurisdiction-level canopy trajectories as a function of SMAP soil moisture (mean and volatility) and the prior year's canopy value, with partial pooling of jurisdiction-level intercepts:

$\text{value}_{it} = \alpha_i + \beta_{\bar{sm}} \cdot \overline{sm}_{it} + \beta_{sm,\sigma} \cdot \sigma_{sm,it} + \gamma \cdot \text{value}_{i,t-1} + \epsilon_{it}$

This model is used to run forward scenario simulations (2024–2028) under two illustrative soil-moisture trajectories — Severe Drought and Climate Recovery — producing full posterior predictive distributions (not point forecasts) per jurisdiction and scenario, from which the probability of canopy decline below each jurisdiction's current baseline can be directly computed. Both canopy height (GEDI Level 2A) and canopy cover (GEDI Level 2B) are modeled as parallel, independently-fit metrics.

**Methodological note carried forward from the underlying data:** because Charlottesville's GEDI record lacks certain years relative to the other jurisdictions, its forecast horizon effectively starts one year further from its last real observation than other jurisdictions' forecasts do. This is explicitly logged and flagged in the pipeline output rather than silently absorbed, pending a team decision on whether a different treatment (e.g., a uniform years-ahead convention) would better serve the policy audience.

### 4.4 Sensitivity of Canopy Cover Estimates to the GEDI Height Filter Threshold

This question — whether a 2-meter minimum canopy height filter meaningfully changes the cover estimate relative to a 1-meter or no filter — was raised as an anticipated audience/reviewer question, given the observed pattern of small ornamental shrub plantings replacing mature trees in developed areas. The team's assessment, intended for the report's Limitations and Assumptions section:

The 2-meter minimum height threshold applied to GEDI footprints represents a deliberate policy choice, not merely a technical one. Vegetation below 2 meters — ornamental shrubs, groundcover, newly transplanted stock — provides limited shade, stormwater interception, or urban heat island mitigation relative to mature canopy; excluding it measures functional canopy rather than total vegetative cover.

**Based on patterns reported in the literature for comparable settings:**

| Filter threshold | Effect on cover fraction                          | Vegetation excluded                                       |
| :--------------- | :------------------------------------------------ | :-------------------------------------------------------- |
| No filter (≥ 0 m) | Highest estimate                                  | All green vegetation including grass, groundcover, low shrubs |
| ≥ 1 m            | Modest reduction (~2–5 pp in suburban settings)   | Groundcover, turf, very low shrubs                        |
| ≥ 2 m (used in this study) | Moderate reduction (~5–12 pp in suburban/mixed settings) | Low shrubs, young transplants, ornamental hedges under 2 m |
| ≥ 5 m            | Substantial reduction (~15–25 pp)                 | All sub-canopy understory and young trees                 |

In predominantly forested rural jurisdictions (e.g., Nelson, Rockingham), the 1 m vs. 2 m difference matters directly for interpreting the "small shrubs replacing mature trees" substitution pattern raised in this project's stakeholder conversations: under a no-filter or 1-meter threshold, new low plantings partially offset a mature-tree removal in the cover metric; under the 2-meter threshold used here, they do not. A stable or modestly declining 2-meter cover estimate, combined with anecdotal evidence of increased low-height planting, is therefore consistent with a net loss of functional canopy even if total vegetative cover appears stable — a distinction with direct implications for tree canopy ordinances and development mitigation requirements.

Since GEDI Level 2A retains the raw per-footprint height value, a post-hoc sensitivity table comparing cover fractions at 0 m / 1 m / 2 m / 5 m thresholds per jurisdiction can be computed from data already collected, without any new data acquisition — recommended as a follow-on analysis for the final report's appendix, pending team/advisor confirmation of scope.

## 5. Stakeholder-Specific Decision Support

### 5.1 Soil and Water Conservation Districts (SWCDs)

Integrated SMAP soil moisture + LiDAR canopy data supports several concrete SWCD operational decisions (e.g., for the Albemarle SWCD):

*   **Drought stress alerting:** soil moisture thresholds (e.g., < 0.10 m³/m³ sustained over 2+ weeks) trigger canopy stress advisories and prioritized field inspection, ranked by co-occurring low soil moisture and low canopy height.
*   **Distinguishing drought stress from pest/disease damage:** a canopy height decline between LiDAR epochs, cross-referenced against SMAP moisture during the same period, narrows the differential diagnosis (drought vs. emerald ash borer, sudden oak death, or clearing) before committing to pesticide or removal interventions.
*   **Reforestation site selection and species matching:** SMAP time-series characterizes planting sites as persistently dry, seasonally wet, or mesic, directly informing species selection (e.g., Virginia pine/post oak on dry sites vs. red maple/sycamore/swamp white oak on wetter sites) and optimal planting windows.
*   **Riparian buffer program management (Chesapeake Bay Preservation Act, Virginia Agricultural BMP Program):** buffers with adequate canopy (per LiDAR) but chronically low soil moisture may have reduced nutrient/sediment filtering capacity, flagging them for amendment; buffer installation funding can be prioritized toward reaches with high seasonal soil-moisture variability, where hydrological benefit is greatest.
*   **Wildfire and forest health risk:** SMAP supplements sparse weather-station networks as an input to fire-danger indices (e.g., Keetch-Byram Drought Index) and prescribed-burn window scheduling; post-drought canopy mortality mapping (SMAP deficit × LiDAR change detection) supports salvage harvest and replanting prioritization before invasive species establish in canopy gaps.
*   **Development permit review and urban heat/canopy equity:** parcels with high soil moisture (indicating active evapotranspiration/stormwater interception) can be flagged for stronger canopy-preservation mitigation conditions during grading/clearing permit review; combined SMAP + LiDAR + Census demographic overlays identify environmental-justice priority areas (low canopy + low moisture + heat exposure) for targeted urban tree planting investment.

### 5.2 Rivanna Conservation Alliance (RCA)

This study's combined canopy height, canopy cover, and soil moisture datasets directly support RCA's riparian restoration, stormwater management, and invasive species removal work in the Charlottesville/Rivanna basin:

*   **Optimizing tree plantings:** precise canopy cover + soil moisture data pinpoints where native tree plantings are most needed to stabilize riverbanks and prevent erosion.
*   **Invasive species triage:** soil moisture data helps prioritize which degraded riparian zones require immediate clearing and replanting, extending prior work such as at Darden Towe Park.
*   **Stream health correlation:** combining canopy and soil moisture metrics with RCA's existing water quality/stream habitat monitoring supports correlating upland tree health with runoff mitigation and in-stream conditions.

**Recommended framing for RCA engagement:** identify specific sub-watersheds within Charlottesville/Albemarle County showing the greatest canopy decline, and connect this study's metrics directly to RCA's ongoing buffer-planting and restoration frameworks as a basis for a formal collaboration proposal.

## 6. Technical Infrastructure and Reproducibility

All data acquisition and processing runs as versioned, parameterized AWS SageMaker Processing Jobs (not ad hoc notebook execution), specifically to avoid a class of failure encountered repeatedly during development: notebooks whose cells depend on a specific, never-restarted kernel session losing critical in-memory state (fitted models, computed variables) on any restart, silently producing incomplete or incorrect results on rerun. Each pipeline stage (LiDAR, GEDI Level 2A, GEDI Level 2B, Bayesian forecasting, multivariate regression + review diagnostics) is a standalone script with explicit inputs/outputs, independently testable, and where applicable, persists intermediate model state (e.g., fitted Bayesian traces) to allow later stages to run as genuinely separate jobs.

**Interactive dashboard:** a React/TypeScript dashboard (Leaflet + Recharts) provides the sponsor and stakeholders with an interactive choropleth map (canopy height, canopy cover, soil moisture, and lag metrics, selectable by year and jurisdiction), per-tile canopy height/mask raster viewing, tree-crown centroid visualization, canopy cover and vegetation-source-quality summaries, Bayesian forecast trend charts with credible intervals, and the regression review artifacts described above.

## 7. Deliverables (2026)

### Core outputs:

*   Tree canopy height and cover estimates (city + all nine counties), cross-validated between VGIN airborne LiDAR and NASA GEDI spaceborne LiDAR.
*   Spatial datasets, rasters (CHM, canopy mask), and tree-crown centroid point data, per tile and county.
*   Statistical analysis report, including the fixed-effects/cross-sectional regression results with attached robustness diagnostics and reviewer recommendations for each finding.
*   Bayesian scenario-based canopy forecast (2024–2028) under Severe Drought / Climate Recovery soil-moisture scenarios.
*   Interactive web dashboard for sponsor and stakeholder use.

### Intermediate outputs:

*   Documented, tested data pipelines (LiDAR, GEDI, SMAP, administrative data integration).
*   Data quality/coverage audit trail (e.g., per-tile vegetation-classification-source tracking, distinguishing vendor-classified from height-derived canopy detections).
*   Workshop summaries (per sponsor's proposed bi-weekly cadence).

## 8. Limitations and Assumptions

*   **Small jurisdiction count (N=9–10):** Nearly every statistical model in this study operates at or near the boundary of what is estimable given available degrees of freedom. Findings are labeled, throughout, as hypothesis-generating rather than confirmatory, and each carries an explicit robustness assessment rather than a bare p-value.
*   **GEDI 2-meter canopy height filter (see Section 4.4):** This is a deliberate, disclosed choice favoring functional canopy over total vegetative cover; sensitivity to this threshold is expected to be larger in urbanizing areas than in rural forested jurisdictions.
*   **CDC PLACES health data is single-year (2023) and cross-sectional:** This is not a true time series at the county level for this study's window — this is why health-outcome regressions use a cross-sectional rather than panel specification, and why they cannot support the same kind of within-jurisdiction change analysis as canopy or crime data.
*   **SMAP's 9 km resolution:** This is appropriate for county/landscape-scale time-series analysis, not intra-city spatial resolution — the entire City of Charlottesville falls within 1–2 SMAP pixels.
*   **Vendor LiDAR classification quality varies by acquisition vintage:** Where vendor vegetation classification was absent (common in some 2015-era deliveries), this study substitutes a height-above-ground-derived classification, tracked and reported per tile so results relying on this fallback are distinguishable from vendor-classified results.
*   **Jurisdiction data coverage is not fully uniform:** Not every jurisdiction has data for every year/metric combination (e.g., Buckingham lacks GEDI Level 2B cover data in the current extraction; Charlottesville's GEDI record has gap years). These gaps are handled explicitly (calendar-aware, not positional) rather than silently interpolated.

## 9. Next Steps

*   Confirm scope/timing with the sponsor and faculty advisor for the recommended GEDI height-filter sensitivity table (Section 4.4) as a report appendix — no new data acquisition required.
*   Complete SageMaker processing runs for all nine counties (in progress at time of writing) and finalize dashboard rollout.
*   Formal internal review pass over all flagged/fragile regression findings (Section 4.2) before any are cited in sponsor-facing materials.
*   Engage RCA and relevant SWCDs directly with sub-watershed-level canopy decline findings, per Section 5.

**Draft prepared for internal team review.** Sections 4.2 (statistical robustness framework), 4.3 (Bayesian forecasting), and the technical infrastructure described in Section 6 reflect implementation work completed and tested as part of this capstone; all other sections reflect the sponsor's original proposal scope and the team's response framework.
