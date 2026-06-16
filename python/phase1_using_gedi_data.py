'''
Phase 1: High-Performance Batch Extraction
To handle 390 files efficiently:

Coordinate Check First: Extract only the lat/lon arrays initially to check if any points fall in your bounding box before reading the heavier rh attributes.Batch Save to Parquet: Do not append everything to a giant in-memory list. Process file-by-file and write to a fast, compressed Apache Parquet format.

'''

import os
import glob
import h5py
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point

# Define study area bounds (Virginia)
MIN_LON, MIN_LAT, MAX_LON, MAX_LAT = -79.1721, 37.3296, -77.6873, 38.4755
H5_FOLDER = "./gedi_data"  # Change to your local path
OUTPUT_PARQUET = "virginia_gedi_canopy.parquet"

all_dfs = []

# Find all GEDI HDF5 files
h5_files = glob.glob(os.path.join(H5_FOLDER, "*.h5"))
print(f"Found {len(h5_files)} files to process.")

for i, file_path in enumerate(h5_files):
    file_name = os.path.basename(file_path)
    
    try:
        with h5py.File(file_path, 'r') as f:
            # GEDI has 8 operational science beams
            beams = [k for k in f.keys() if k.startswith('BEAM')]
            
            for beam in beams:
                # Check group keys to verify expected data exists
                if 'lat_lowestmode' not in f[beam]:
                    continue
                
                # Step 1: Extract coordinates first for rapid spatial masking
                lats = f[f"{beam}/lat_lowestmode"][:]
                lons = f[f"{beam}/lon_lowestmode"][:]
                
                # Create a spatial mask for the Virginia bounding box
                spatial_mask = (lons >= MIN_LON) & (lons <= MAX_LON) & (lats >= MIN_LAT) & (lats <= MAX_LAT)
                
                # If no points from this beam fall in Virginia, skip heavy reads
                if not np.any(spatial_mask):
                    continue
                
                # Step 2: Extract attributes only for points inside your box
                quality = f[f"{beam}/quality_flag"][:][spatial_mask]
                sensitivity = f[f"{beam}/sensitivity"][:][spatial_mask]
                
                # GEDI RH array is shape (N, 101). Row-index 98 corresponds to rh98
                rh98 = f[f"{beam}/rh"][:, 98][spatial_mask]
                
                beam_df = pd.DataFrame({
                    'longitude': lons[spatial_mask],
                    'latitude': lats[spatial_mask],
                    'quality_flag': quality,
                    'sensitivity': sensitivity,
                    'rh98': rh98,
                    'file_source': file_name,
                    'beam': beam
                })
                
                # Step 3: Strict Quality Filtering
                valid_df = beam_df[
                    (beam_df['quality_flag'] == 1) & 
                    (beam_df['sensitivity'] > 0.9) & 
                    (beam_df['rh98'] > 0) & 
                    (beam_df['rh98'] < 100) # Remove erratic artifacts
                ]
                
                if not valid_df.empty:
                    all_dfs.append(valid_df)
                    
    except Exception as e:
        print(f"Error reading {file_name}: {e}")
    
    # Periodically report progress
    if (i + 1) % 50 == 0:
        print(f"Processed {i + 1}/{len(h5_files)} files...")

# Combine all extracted points and save out
if all_dfs:
    final_df = pd.concat(all_dfs, ignore_index=True)
    final_df.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"Extraction complete! Total valid points saved: {len(final_df)}")
else:
    print("No valid GEDI shots found within the bounding box.")

