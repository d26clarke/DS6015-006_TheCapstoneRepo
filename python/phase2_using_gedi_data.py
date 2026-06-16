'''
    Phase 2 - Using GEDI Data
    Visualize the canopy height profile of Virginia using hexagonal bins.
    This script uses the previously processed Parquet file to create a hexagonal bin plot.
    The Parquet file is created in Phase 1.
    The Parquet file is a fast, compressed format that can be easily read and processed.
    This script uses pandas and matplotlib to read the Parquet file and create the hexagonal bin plot.
    '''
import matplotlib.pyplot as plt
import pandas as pd

df = pd.read_parquet("virginia_gedi_canopy.parquet")

fig, ax = plt.subplots(figsize=(12, 10))
# Gridsize controls resolution of hexagons; C='rh98' averages the height in each hexagon
hb = ax.hexbin(df['longitude'], df['latitude'], C=df['rh98'], gridsize=150, cmap='YlGn', mincnt=1)

cb = fig.colorbar(hb, ax=ax, orientation='horizontal', pad=0.05)
cb.set_label('Mean Canopy Height (rh98) in Meters')
ax.set_title('Virginia Canopy Height Profile (Aggregated Hexbins)')
plt.show()
