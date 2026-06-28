import numpy as np
import pandas as pd

def evaluate_canopy_decline_probabilities(simulation_results, jurisdictions, init_canopy, future_years=[2024, 2025, 2026, 2027, 2028]):
    """
    Calculates the exact Bayesian probability that the canopy height in 2027 and 2028
    will fall below the initial baseline value recorded at the start of the projection.
    """
    idx_2027 = future_years.index(2027)
    idx_2028 = future_years.index(2028)
    
    rows = []
    
    # Iterate through each jurisdiction and scenario combination
    for j_name in jurisdictions:
        baseline_height = init_canopy[j_name]
        
        for scen_name, juris_data in simulation_results.items():
            # Extract the raw posterior vector arrays
            draws_2027 = juris_data[j_name][idx_2027, :]
            draws_2028 = juris_data[j_name][idx_2028, :]
            
            # Compute the exact risk frequency (draws < baseline) / total draws
            prob_decline_2027 = np.mean(draws_2027 < baseline_height) * 100
            prob_decline_2028 = np.mean(draws_2028 < baseline_height) * 100
            
            # Calculate the expected value shift (Mean Prediction - Baseline)
            drift_2028 = np.mean(draws_2028) - baseline_height
            
            rows.append({
                "Jurisdiction": j_name,
                "Scenario": scen_name,
                "Baseline Height (m)": round(float(baseline_height), 2),
                "2027 Decline Risk (%)": round(prob_decline_2027, 1),
                "2028 Decline Risk (%)": round(prob_decline_2028, 1),
                "Net Shift by 2028 (m)": round(drift_2028, 2)
            })
            
    # Convert findings into a scannable DataFrame structure
    summary_df = pd.DataFrame(rows)
    return summary_df

# Run the evaluation engine
risk_summary_table = evaluate_canopy_decline_probabilities(simulation_results, jurisdictions, init_canopy)

# Render the formatted breakdown
print("\n================== BAYESIAN CANOPY RISK ASSESSMENT REPORT ==================")
print(risk_summary_table.to_string(index=False))
