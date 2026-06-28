import matplotlib.pyplot as plt
import seaborn as sns  # Optional, but makes probability density curves smoother

def plot_bayesian_forecasts(simulation_results, jurisdictions, future_years=[2024, 2025, 2026, 2027, 2028]):
    """
    Generates side-by-side probability density plots comparing 2027 and 2028 
    canopy height forecasts across all scenarios for each jurisdiction.
    """
    # Identify index offsets for target prediction horizons
    idx_2027 = future_years.index(2027)
    idx_2028 = future_years.index(2028)
    
    # Define distinct visual style elements
    colors = {"Severe Drought": "#e66101", "Climate Recovery": "#5e3c99"}
    
    # Create a dynamic plotting canvas grid (1 row per jurisdiction, 2 columns for years)
    n_jurisdictions = len(jurisdictions)
    fig, axes = plt.subplots(nrows=n_jurisdictions, ncols=2, figsize=(14, 3.5 * n_jurisdictions), sharey='row')
    
    # Handle single-jurisdiction edge-case array flattening
    if n_jurisdictions == 1:
        axes = np.expand_dims(axes, axis=0)
        
    for j_idx, j_name in enumerate(jurisdictions):
        ax_2027 = axes[j_idx, 0]
        ax_2028 = axes[j_idx, 1]
        
        # 1. Plot distributions across both simulated scenario runs
        for scen_name, color in colors.items():
            # Extract raw MCMC posterior predictive draws
            draws_2027 = simulation_results[scen_name][j_name][idx_2027, :]
            draws_2028 = simulation_results[scen_name][j_name][idx_2028, :]
            
            # --- YEAR 2027 PLOTTING ---
            sns.kdeplot(draws_2027, ax=ax_2027, color=color, fill=True, alpha=0.25, 
                        linewidth=2, label=scen_name)
            # Add vertical dashed baseline marker for the distribution average
            ax_2027.axvline(np.mean(draws_2027), color=color, linestyle="--", alpha=0.8)
            
            # --- YEAR 2028 PLOTTING ---
            sns.kdeplot(draws_2028, ax=ax_2028, color=color, fill=True, alpha=0.25, 
                        linewidth=2, label=scen_name)
            ax_2028.axvline(np.mean(draws_2028), color=color, linestyle="--", alpha=0.8)
            
        # 2. Add structural visual indicators and labels to charts
        ax_2027.set_title(f"{j_name} Canopy Height - 2027 Projection", fontsize=11, weight='bold')
        ax_2028.set_title(f"{j_name} Canopy Height - 2028 Projection", fontsize=11, weight='bold')
        
        ax_2027.set_ylabel("Probability Density", fontsize=10)
        ax_2028.set_ylabel("") # Suppress shared axis clutter
        
        ax_2027.set_xlabel("Mean Canopy Height (meters)", fontsize=10)
        ax_2028.set_xlabel("Mean Canopy Height (meters)", fontsize=10)
        
        # Gridlines help identify shifts between the mean values easily
        ax_2027.grid(True, linestyle=":", alpha=0.6)
        ax_2028.grid(True, linestyle=":", alpha=0.6)
        
        # Position a single clean legend bounding box over the first column plot
        if j_idx == 0:
            ax_2027.legend(title="Scenarios", loc="upper left", frameon=True)

    # Prevent label overlaps across multi-plot rows
    plt.tight_layout()
    plt.show()

# Run the visualization pipeline using the outputs generated from the scenario loop
plot_bayesian_forecasts(simulation_results, jurisdictions)
