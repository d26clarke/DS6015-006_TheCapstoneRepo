import numpy as np
import pandas as pd
import pymc as pm
import arviz as az

# 1. Load and parse the raw data array
raw_data = [
  {"year": 2019, "jurisdiction": "Albemarle", "canopy_height_mean_m": 19.675812, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2020, "jurisdiction": "Albemarle", "canopy_height_mean_m": 18.465603, "sm_mean_m3m3": 0.307442, "sm_min": 0.229515, "sm_max": 0.38936, "sm_std": 0.034866, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Albemarle", "canopy_height_mean_m": 18.793875, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.307442, "sm_mean_lag2": 0.379557},
  {"year": 2022, "jurisdiction": "Albemarle", "canopy_height_mean_m": 18.639362, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.307442},
  {"year": 2023, "jurisdiction": "Albemarle", "canopy_height_mean_m": 13.609988, "sm_mean_m3m3": 0.271359, "sm_min": 0.197718, "sm_max": 0.351615, "sm_std": 0.036388, "sm_mean_lag1": 0.28877, "sm_mean_lag2": 0.287135},
  {"year": 2019, "jurisdiction": "Augusta", "canopy_height_mean_m": 14.742975, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2020, "jurisdiction": "Augusta", "canopy_height_mean_m": 10.717906, "sm_mean_m3m3": 0.307442, "sm_min": 0.229515, "sm_max": 0.38936, "sm_std": 0.034866, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Augusta", "canopy_height_mean_m": 14.507577, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.307442, "sm_mean_lag2": 0.379557},
  {"year": 2022, "jurisdiction": "Augusta", "canopy_height_mean_m": 12.463281, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.307442},
  {"year": 2023, "jurisdiction": "Augusta", "canopy_height_mean_m": 8.282045, "sm_mean_m3m3": 0.271359, "sm_min": 0.197718, "sm_max": 0.351615, "sm_std": 0.036388, "sm_mean_lag1": 0.28877, "sm_mean_lag2": 0.287135},
  {"year": 2019, "jurisdiction": "Charlottesville", "canopy_height_mean_m": 16.58323, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Charlottesville", "canopy_height_mean_m": 12.467922, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2022, "jurisdiction": "Charlottesville", "canopy_height_mean_m": 16.108187, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.379557},
  {"year": 2019, "jurisdiction": "Fluvanna", "canopy_height_mean_m": 18.198132, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2020, "jurisdiction": "Fluvanna", "canopy_height_mean_m": 18.537386, "sm_mean_m3m3": 0.307442, "sm_min": 0.229515, "sm_max": 0.38936, "sm_std": 0.034866, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Fluvanna", "canopy_height_mean_m": 18.0978, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.307442, "sm_mean_lag2": 0.379557},
  {"year": 2022, "jurisdiction": "Fluvanna", "canopy_height_mean_m": 17.584047, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.307442},
  {"year": 2023, "jurisdiction": "Fluvanna", "canopy_height_mean_m": 12.527934, "sm_mean_m3m3": 0.271359, "sm_min": 0.197718, "sm_max": 0.351615, "sm_std": 0.036388, "sm_mean_lag1": 0.28877, "sm_mean_lag2": 0.287135},
  {"year": 2019, "jurisdiction": "Greene", "canopy_height_mean_m": 18.535742, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2020, "jurisdiction": "Greene", "canopy_height_mean_m": 21.557728, "sm_mean_m3m3": 0.307442, "sm_min": 0.229515, "sm_max": 0.38936, "sm_std": 0.034866, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Greene", "canopy_height_mean_m": 18.305456, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.307442, "sm_mean_lag2": 0.379557},
  {"year": 2022, "jurisdiction": "Greene", "canopy_height_mean_m": 16.128891, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.307442},
  {"year": 2023, "jurisdiction": "Greene", "canopy_height_mean_m": 15.663726, "sm_mean_m3m3": 0.271359, "sm_min": 0.197718, "sm_max": 0.351615, "sm_std": 0.036388, "sm_mean_lag1": 0.28877, "sm_mean_lag2": 0.287135},
  {"year": 2019, "jurisdiction": "Louisa", "canopy_height_mean_m": 17.528442, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2020, "jurisdiction": "Louisa", "canopy_height_mean_m": 17.728891, "sm_mean_m3m3": 0.307442, "sm_min": 0.229515, "sm_max": 0.38936, "sm_std": 0.034866, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Louisa", "canopy_height_mean_m": 17.248003, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.307442, "sm_mean_lag2": 0.379557},
  {"year": 2022, "jurisdiction": "Louisa", "canopy_height_mean_m": 15.880913, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.307442},
  {"year": 2023, "jurisdiction": "Louisa", "canopy_height_mean_m": 13.388947, "sm_mean_m3m3": 0.271359, "sm_min": 0.197718, "sm_max": 0.351615, "sm_std": 0.036388, "sm_mean_lag1": 0.28877, "sm_mean_lag2": 0.287135},
  {"year": 2019, "jurisdiction": "Nelson", "canopy_height_mean_m": 22.903877, "sm_mean_m3m3": 0.379557, "sm_min": 0.314088, "sm_max": 0.436462, "sm_std": 0.027698, "sm_mean_lag1": None, "sm_mean_lag2": None},
  {"year": 2020, "jurisdiction": "Nelson", "canopy_height_mean_m": 18.566174, "sm_mean_m3m3": 0.307442, "sm_min": 0.229515, "sm_max": 0.38936, "sm_std": 0.034866, "sm_mean_lag1": 0.379557, "sm_mean_lag2": None},
  {"year": 2021, "jurisdiction": "Nelson", "canopy_height_mean_m": 20.188175, "sm_mean_m3m3": 0.287135, "sm_min": 0.214029, "sm_max": 0.363267, "sm_std": 0.033156, "sm_mean_lag1": 0.307442, "sm_mean_lag2": 0.379557},
  {"year": 2022, "jurisdiction": "Nelson", "canopy_height_mean_m": 19.654766, "sm_mean_m3m3": 0.28877, "sm_min": 0.218431, "sm_max": 0.366198, "sm_std": 0.033531, "sm_mean_lag1": 0.287135, "sm_mean_lag2": 0.307442}
]

df = pd.DataFrame(raw_data)

# 2. Engineer an explicit temporal Lag-1 feature for Canopy Height per Jurisdiction
df = df.sort_values(by=["jurisdiction", "year"])
df["canopy_height_lag1"] = df.groupby("jurisdiction")["canopy_height_mean_m"].shift(1)

# Drop rows where lag is NaN (this clean handling strips year 2019 from the fitting engine)
df_clean = df.dropna(subset=["canopy_height_lag1"]).copy()

# 3. Factorize categorical index mappings for PyMC's random effects
jurisdiction_cats = df_clean["jurisdiction"].astype("category")
jurisdiction_idx = jurisdiction_cats.cat.codes.values
jurisdiction_names = jurisdiction_cats.cat.categories

# Extract NumPy data vectors
y_obs = df_clean["canopy_height_mean_m"].values
lagged_y = df_clean["canopy_height_lag1"].values
sm_mean = df_clean["sm_mean_m3m3"].values
sm_std = df_clean["sm_std"].values

# 4. Construct the PyMC Hierarchical Model architecture
coords = {"jurisdictions": jurisdiction_names}

with pm.Model(coords=coords) as hierarchical_ar_model:
    
    # --- PRIORS ---
    # Global hyperpriors for jurisdiction baseline distribution
    mu_alpha = pm.Normal("mu_alpha", mu=15.0, sigma=5.0)
    sigma_alpha = pm.HalfNormal("sigma_alpha", sigma=3.0)
    
    # Random intercepts (varying baseline height offset by location)
    alpha = pm.Normal("alpha", mu=mu_alpha, sigma=sigma_alpha, dims="jurisdictions")
    
    # Global fixed slope coefficients
    beta_sm_mean = pm.Normal("beta_sm_mean", mu=0.0, sigma=2.0)
    beta_sm_std = pm.Normal("beta_sm_std", mu=0.0, sigma=2.0)
    gamma_autoreg = pm.Normal("gamma_autoreg", mu=0.0, sigma=1.0) # Inertia dynamic
    
    # Model error (unexplained structural white noise variance)
    sigma_residual = pm.Exponential("sigma_residual", lam=1.0)
    
    # --- DETERMINISTIC STRUCTURAL LINK ---
    mu_t = (
        alpha[jurisdiction_idx] + 
        beta_sm_mean * sm_mean + 
        beta_sm_std * sm_std + 
        gamma_autoreg * lagged_y
    )
    
    # --- LIKELIHOOD FUNCTION ---
    y_likelihood = pm.Normal("y_likelihood", mu=mu_t, sigma=sigma_residual, observed=y_obs)
    
    # --- SAMPLING CONFIGURATION ---
    # Execute Hamiltonian Monte Carlo sampling
    trace = pm.sample(draws=1000, tune=1000, target_accept=0.95, random_seed=42)
    
    # Generate posterior predictive distributions
    posterior_predictive = pm.sample_posterior_predictive(trace)

# 5. Output summary metrics
print(az.summary(trace, var_names=["mu_alpha", "beta_sm_mean", "beta_sm_std", "gamma_autoreg"]))
