'''
Spatial Join (Assigning GEDI Points to Counties)You will need a shapefile or GeoJSON of Virginia counties. You can download this directly using Python via geopandas and USCensus resources, filter it for your specific jurisdictions, and perform a spatial join (sjoin).
'''

import geopandas as gpd
import pandas as pd

# 1. Load your raw extracted GEDI points (with the 'year' column added via filename parse)
df_gedi = pd.read_parquet("virginia_gedi_canopy_multiyear.parquet")
gdf_gedi = gpd.GeoDataFrame(
    df_gedi, 
    geometry=gpd.points_from_xy(df_gedi.longitude, df_gedi.latitude),
    crs="EPSG:4326"
)

# 2. Fetch Virginia County boundaries directly from US Census Tigerweb
va_counties_url = "https://census.gov"
va_counties = gpd.read_file(va_counties_url)

# Clean up names to match your SMAP dataset (e.g., "Albemarle County" -> "Albemarle")
va_counties['county'] = va_counties['NAME']

# Filter for your specific 8 study jurisdictions
target_jurisdictions = ['Albemarle', 'Augusta', 'Charlottesville', 'Fluvanna', 'Greene', 'Louisa', 'Nelson', 'Rockingham']
filtered_counties = va_counties[va_counties['county'].isin(target_jurisdictions)]

# 3. Spatial Join: Find which county each GEDI point falls into
gedi_with_county = gpd.sjoin(gdf_gedi, filtered_counties[['county', 'geometry']], how='inner', predicate='within')

# 4. Group by Year and County to get Mean Canopy Height
gedi_county_summary = gedi_with_county.groupby(['year', 'county'])['rh98'].mean().reset_index()
gedi_county_summary.rename(columns={'rh98': 'canopy_height_mean_m'}, inplace=True)

