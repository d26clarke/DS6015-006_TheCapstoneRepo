'''
Harmonizing GEDI to the SMAP 9km GridSince SMAP has a static 9km grid, you should aggregate the thousands of fine GEDI laser shots falling inside each 9km grid cell into a single yearly mean canopy height.
'''

import pandas as pd
import numpy as np
import xarray as xr
import matplotlib.pyplot as plt

# 1. Load your multi-year GEDI points
df_gedi = pd.read_parquet("virginia_gedi_canopy_multiyear.parquet") # includes 'year' column

# 2. Define the spatial grid matching your SMAP resolution (~0.081 degrees for 9km)
grid_res = 0.081 
min_lon, min_lat, max_lon, max_lat = -79.1721, 37.3296, -77.6873, 38.4755

lon_bins = np.arange(min_lon, max_lon, grid_res)
lat_bins = np.arange(min_lat, max_lat, grid_res)

# 3. Assign each GEDI point to a grid cell coordinate
df_gedi['lon_grid'] = pd.cut(df_gedi['longitude'], bins=lon_bins, labels=lon_bins[:-1]).astype(float)
df_gedi['lat_grid'] = pd.cut(df_gedi['latitude'], bins=lat_bins, labels=lat_bins[:-1]).astype(float)

# 4. Group by Year and Grid Cell to get the Mean Yearly Canopy Height
gedi_grid = df_gedi.groupby(['year', 'lat_grid', 'lon_grid'])['rh98'].mean().reset_index()

# 5. Convert to an Xarray Dataset for easy multi-year matrix operations
ds_gedi = gedi_grid.set_index(['year', 'lat_grid', 'lon_grid']).to_xarray()

