'''
Phase 1a: Using GEDI Data
This script uses regular expressions to extract the year from a GEDI file name.
'''

import re

# Standard GEDI naming: GEDI02_A_2022143... (YYYYDDD)
file_name = "GEDI02_A_2022143123456_O19345_02_T05643_02_002_01_V002.h5"

# Match 4 digits following the second underscore
year_match = re.search(r'GEDI02_A_(\d{4})', file_name)
if year_match:
    year = int(year_match.group(1)) # Returns: 2022

