import os
import io
import re
import urllib.request
import boto3
import s3fs
import h5py
import numpy as np
import pandas as pd
import geopandas as gpd
import xarray as xr

# =============================================================================
# Configuration
# =============================================================================

S3_BUCKET = "central-virginia-tree-canopy-project"
GEDI02B_COUNTY_S3_PREFIX = "GEDI/"

OUTPUT_DIR = "./output"
OUTPUT_PARQUET = os.path.join(OUTPUT_DIR, "virginia_gedi_canopy_multiyear.parquet")
OUTPUT_NETCDF = os.path.join(OUTPUT_DIR, "virginia_gedi_canopy_grid.nc")
OUTPUT_COUNTY_CSV = os.path.join(OUTPUT_DIR, "virginia_gedi_county_summary.csv")

# Spatial bounds (Virginia study area)
MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = -79.1721, 37.3296, -77.6873, 38.4755

# SMAP grid resolution (~9km)
GRID_RES = 0.081

TARGET_JURISDICTIONS = [
    ("Albemarle", "51", "003", "county"),
    ("Augusta", "51", "015", "county"),
    ("Charlottesville", "51", "14968", "place"),
    ("Fluvanna", "51", "065", "county"),
    ("Greene", "51", "079", "county"),
    ("Louisa", "51", "109", "county"),
    ("Nelson", "51", "125", "county"),
    ("Rockingham", "51", "165", "county"),
]

# =============================================================================
# Helper Functions
# =============================================================================

def parse_year_from_filename(filename: str) -> int:
    """Extract the year from standard GEDI02_B filename (e.g., GEDI02_B_2022143...)."""
    year_match = re.search(r'GEDI02_B_(\d{4})', filename)
    if year_match:
        return int(year_match.group(1))
    return None

def fetch_boundary(name: str, state_fips: str, geo_id: str, geo_type: str) -> gpd.GeoDataFrame:
    """Fetch boundary GeoJSON directly from US Census TIGERweb API."""
    if geo_type == "place":
        url = (
            "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "Places_CouSub_ConCity_SubMCD/MapServer/4/query"
            f"?where=STATE='{state_fips}'+AND+PLACE='{geo_id}'"
            "&outFields=NAME,STATE,PLACE&f=geojson&outSR=4326"
        )
    else:
        url = (
            "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "State_County/MapServer/11/query"
            f"?where=STATE='{state_fips}'+AND+COUNTY='{geo_id}'"
            "&outFields=NAME,STATE,COUNTY&f=geojson&outSR=4326"
        )
    
    print(f"Fetching boundary for {name}...")
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            gdf = gpd.read_file(r)
        if gdf.empty:
            raise ValueError(f"No boundary found for {name}")
        gdf = gdf.set_crs("EPSG:4326")
        gdf['jurisdiction'] = name
        return gdf
    except Exception as e:
        print(f"Failed to fetch boundary for {name}: {e}")
        return gpd.GeoDataFrame()

# =============================================================================
# Main Processing Pipeline
# =============================================================================

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print(f"Scanning s3://{S3_BUCKET}/{S3_PREFIX} for GEDI02_B HDF5 files...")
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    
    h5_keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=S3_PREFIX):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith(".h5") and "GEDI02_B" in obj["Key"]:
                h5_keys.append(obj["Key"])
                
    print(f"Found {len(h5_keys)} GEDI02_B files to process.")
    if not h5_keys:
        return

    fs = s3fs.S3FileSystem(anon=False)
    all_dfs = []
    
    print("\n--- Starting Phase 1: Point Extraction (GEDI02_B) ---")
    for i, key in enumerate(h5_keys):
        file_name = os.path.basename(key)
        year = parse_year_from_filename(file_name)
        
        if not year:
            continue
            
        try:
            s3_path = f"s3://{S3_BUCKET}/{key}"
            with fs.open(s3_path, "rb") as f:
                raw_bytes = f.read()
                
            with h5py.File(io.BytesIO(raw_bytes), 'r') as hf:
                beams = [k for k in hf.keys() if k.startswith('BEAM')]
                
                for beam in beams:
                    # GEDI02_B houses geographic coordinates within a sub-group
                    if f"{beam}/geolocation/lat_lowestmode" not in hf:
                        continue
                        
                    lats = hf[f"{beam}/geolocation/lat_lowestmode"][:]
                    lons = hf[f"{beam}/geolocation/lon_lowestmode"][:]
                    
                    spatial_mask = (lons >= MIN_LON) & (lons <= MAX_LON) & (lats >= MIN_LAT) & (lats <= MAX_LAT)
                    if not np.any(spatial_mask):
                        continue
                        
                    # Extract L2B specific metrics and apply mask
                    quality = hf[f"{beam}/l2b_quality_flag"][:][spatial_mask]
                    sensitivity = hf[f"{beam}/sensitivity"][:][spatial_mask]
                    
                    # Target metric: Total Canopy Cover (values scale from 0.0 to 1.0)
                    canopy_cover = hf[f"{beam}/canopy_cover"][:][spatial_mask]
                    
                    beam_df = pd.DataFrame({
                        'longitude': lons[spatial_mask],
                        'latitude': lats[spatial_mask],
                        'l2b_quality_flag': quality,
                        'sensitivity': sensitivity,
                        'canopy_cover': canopy_cover,
                        'year': year,
                        'file_source': file_name,
                        'beam': beam
                    })
                    
                    # Quality filtering tailored for Canopy Cover
                    valid_df = beam_df[
                        (beam_df['l2b_quality_flag'] == 1) & 
                        (beam_df['sensitivity'] > 0.9) & 
                        (beam_df['canopy_cover'] >= 0.0) & 
                        (beam_df['canopy_cover'] <= 1.0)
                    ]
                    
                    if not valid_df.empty:
                        all_dfs.append(valid_df)
                        
        except Exception as e:
            print(f"Error reading {file_name}: {e}")
            
        if (i + 1) % 10 == 0:
            print(f"Processed {i + 1}/{len(h5_keys)} files...")

    if not all_dfs:
        print("No valid GEDI shots found inside the box.")
        return
        
    df_gedi = pd.concat(all_dfs, ignore_index=True)
    df_gedi.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"Extraction complete! Saved: {len(df_gedi)} rows")
    
    # -------------------------------------------------------------------------
    # Phase 1b: Grid Harmonization
    # -------------------------------------------------------------------------
    print("\n--- Starting Phase 1b: Grid Harmonization ---")
    lon_bins = np.arange(MIN_LON, MAX_LON + GRID_RES, GRID_RES)
    lat_bins = np.arange(MIN_LAT, MAX_LAT + GRID_RES, GRID_RES)
    
    df_gedi['lon_grid'] = pd.cut(df_gedi['longitude'], bins=lon_bins, labels=lon_bins[:-1]).astype(float)
    df_gedi['lat_grid'] = pd.cut(df_gedi['latitude'], bins=lat_bins, labels=lat_bins[:-1]).astype(float)
    
    gedi_grid = df_gedi.groupby(['year', 'lat_grid', 'lon_grid'])['canopy_cover'].mean().reset_index()
    
    ds_gedi = gedi_grid.set_index(['year', 'lat_grid', 'lon_grid']).to_xarray()
    ds_gedi.to_netcdf(OUTPUT_NETCDF)
    print(f"Grid harmonization complete. Saved to {OUTPUT_NETCDF}")

    # -------------------------------------------------------------------------
    # Phase 2: Zonal Stats Summary
    # -------------------------------------------------------------------------
    print("\n--- Starting Phase 2: Zonal Statistics Summary ---")
    gdf_boundaries = []
    for name, state, fips, g_type in TARGET_JURISDICTIONS:
        bound_df = fetch_boundary(name, state, fips, g_type)
        if not bound_df.empty:
            gdf_boundaries.append(bound_df)
            
    if not gdf_boundaries:
        print("No jurisdiction boundaries fetched. Stopping pipeline.")
        return
        
    gdf_regions = pd.concat(gdf_boundaries, ignore_index=True)
    gdf_points = gpd.GeoDataFrame(
        df_gedi, 
        geometry=gpd.points_from_xy(df_gedi.longitude, df_gedi.latitude), 
        crs="EPSG:4326"
    )
    
    # Spatial Join points to target boundaries
    joined = gpd.sjoin(gdf_points, gdf_regions, how="inner", predicate="within")
    
    summary = joined.groupby(['jurisdiction', 'year']).agg(
        mean_canopy_cover=('canopy_cover', 'mean'),
        total_valid_shots=('canopy_cover', 'count')
    ).reset_index()
    
    summary.to_csv(OUTPUT_COUNTY_CSV, index=False)
    print(f"Zonal summary saved to {OUTPUT_COUNTY_CSV}")

if __name__ == "__main__":
    main()
