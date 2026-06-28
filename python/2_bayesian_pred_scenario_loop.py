import numpy as np
import pandas as pd
import pymc as pm

# 1. Define your future soil moisture scenarios (2024 to 2028)
# These represent assumptions about regional weather trends
scenarios = {
    "Severe Drought": {
        "sm_mean": [0.26, 0.24, 0.23, 0.22, 0.21],  # Steady decline through 2028
        "sm_std":  [0.038, 0.040, 0.042, 0.045, 0.045] # Higher volatility
    },
    "Climate Recovery": {
        "sm_mean": [0.29, 0.32, 0.34, 0.35, 0.36],  # Steady wet recovery
        "sm_std":  [0.033, 0.031, 0.029, 0.028, 0.028] # Lower, stable volatility
    }
}

future_years = [2024, 2025, 2026, 2027, 2028]
jurisdictions = list(jurisdiction_names)  # Inherited from previous training setup
n_chains_draws = 4000  # Total trace samples from your model (e.g., 4 chains x 1000 draws)

# Extract posterior parameter samples from your trained MCMC trace
posterior_alpha = trace.posterior["alpha"].values.reshape(n_chains_draws, len(jurisdictions))
posterior_beta_mean = trace.posterior["beta_sm_mean"].values.flatten()
posterior_beta_std = trace.posterior["beta_sm_std"].values.flatten()
posterior_gamma = trace.posterior["gamma_autoreg"].values.flatten()
posterior_sigma = trace.posterior["sigma_residual"].values.flatten()

# 2. Get the baseline initialization state (Year 2023 actual values)
# For Charlottesville, which lacks 2023 data, we default back to its 2022 state
init_canopy = {}
for j in jurisdictions:
    j_data = df[df["jurisdiction"] == j]
    if 2023 in j_data["year"].values:
        init_canopy[j] = j_data[j_data["year"] == 2023]["canopy_height_mean_m"].values[0]
    else:
        init_canopy[j] = j_data[j_data["year"] == 2022]["canopy_height_mean_m"].values[0]

# Dictionary to hold the final forecast outputs
simulation_results = {}

# 3. Main Iterative Scenario Loop
for scen_name, vectors in scenarios.items():
    print(f"Running forecast loop for scenario: {scen_name}...")
    
    # Store matrix arrays for each jurisdiction
    # Shape: (Years, Posterior Samples) -> tracks entire distribution shapes over time
    juris_forecasts = {}
    
    for j_idx, j_name in enumerate(jurisdictions):
        # Initialize an empty array for years 2024-2028
        canopy_sim = np.zeros((len(future_years), n_chains_draws))
        
        # Pull baseline year tracking vector
        last_canopy_height = np.full(n_chains_draws, init_canopy[j_name])
        
        # Step sequentially through future time to preserve autoregressive memory
        for t_idx, year in enumerate(future_years):
            # Pull scenario metrics for the given year
            curr_sm_mean = vectors["sm_mean"][t_idx]
            curr_sm_std = vectors["sm_std"][t_idx]
            
            # Vectorized Bayesian Calculation across all posterior MCMC draws
            # This applies the exact regression equation defined in the likelihood function
            mu_pred = (
                posterior_alpha[:, j_idx] +
                posterior_beta_mean * curr_sm_mean +
                posterior_beta_std * curr_sm_std +
                posterior_gamma * last_canopy_height
            )
            
            # Incorporate environmental white noise residual variance
            simulated_heights = np.random.normal(mu_pred, posterior_sigma)
            
            # Save predictions and set up the lag input for the next cycle loop
            canopy_sim[t_idx, :] = simulated_heights
            last_canopy_height = simulated_heights
            
        juris_forecasts[j_name] = canopy_sim
        
    simulation_results[scen_name] = j_forecasts

# 4. Extract and analyze 2027 and 2028 credible distributions
for scen_name, juris_data in simulation_results.items():
    print(f"\n=== SCENARIO: {scen_name} ===")
    for j_name in jurisdictions:
        # Index 3 corresponds to 2027, Index 4 corresponds to 2028
        canopy_2027 = juris_data[j_name][3, :]
        canopy_2028 = juris_data[j_name][4, :]
        
        print(f"\nJurisdiction: {j_name}")
        print(f"  2027 Height (95% Credible Interval): {np.percentile(canopy_2027, 2.5):.2f}m to {np.percentile(canopy_2027, 97.5):.2f}m [Mean: {np.mean(canopy_2027):.2f}m]")
        print(f"  2028 Height (95% Credible Interval): {np.percentile(canopy_2028, 2.5):.2f}m to {np.percentile(canopy_2028, 97.5):.2f}m [Mean: {np.mean(canopy_2028):.2f}m]")
