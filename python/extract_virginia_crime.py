#!/usr/bin/env python3
"""
extract_virginia_crime.py
─────────────────────────────────────────────────────────────────────────────
Extracts Tier 1 and Tier 2 crime descriptors from Virginia NIBRS Agency Crime
Overview PDFs (one page per jurisdiction) and writes a tidy county-year CSV.

Usage
-----
    python3 extract_virginia_crime.py \
        --pdfs Crime_In_Virginia_2019a.pdf \
                Crime_In_Virginia_2020a.pdf \
                Crime_In_Virginia_2021a.pdf \
        --output virginia_crime_county_year.csv

Requirements
------------
    pip install pdfplumber

Output columns
--------------
Tier 1 (high-level county-year outcomes):
    year, jurisdiction, agency_name, agency_code,
    population_estimate, incident_total, offense_total,
    group_a_crimes_per_100k, total_arrests, adult_arrests,
    juvenile_arrests, arrests_per_100k,
    total_group_a_offenses, total_group_b_adult_arrests,
    total_group_b_juvenile_arrests

Tier 2 (offense-specific reported counts):
    aggravated_assault_reported, simple_assault_reported,
    burglary_breaking_entering_reported,
    destruction_damage_vandalism_reported,
    motor_vehicle_theft_reported, shoplifting_reported,
    theft_from_motor_vehicle_reported, all_other_larceny_reported,
    drug_narcotic_violations_reported, drug_equipment_violations_reported,
    weapon_law_violations_reported,
    dui_group_b_adult, drunkenness_group_b_adult,
    disorderly_conduct_group_b_adult, trespass_real_property_group_b_adult
─────────────────────────────────────────────────────────────────────────────
"""

import argparse
import csv
import logging
import re
import sys
from pathlib import Path
from typing import Optional

import pdfplumber

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Jurisdiction name normalisation ───────────────────────────────────────────
NAME_TO_JURIS: dict[str, str] = {
    "albemarle county police department":   "Albemarle",
    "albemarle county":                     "Albemarle",
    "augusta county sheriff":               "Augusta",
    "augusta county sheriff's office":      "Augusta",
    "augusta county":                       "Augusta",
    "buckingham county sheriff":            "Buckingham",
    "buckingham county sheriff's office":   "Buckingham",
    "buckingham county":                    "Buckingham",
    "charlottesville police department":    "Charlottesville",
    "charlottesville":                      "Charlottesville",
    "fluvanna county sheriff":              "Fluvanna",
    "fluvanna county sheriff's office":     "Fluvanna",
    "fluvanna county":                      "Fluvanna",
    "greene county sheriff":                "Greene",
    "greene county sheriff's office":       "Greene",
    "greene county":                        "Greene",
    "louisa co. sheriff office":            "Louisa",
    "louisa co. sheriff's office":          "Louisa",
    "louisa county sheriff":                "Louisa",
    "louisa county":                        "Louisa",
    "nelson county sheriff":                "Nelson",
    "nelson county sheriff's office":       "Nelson",
    "nelson county":                        "Nelson",
    "orange county sheriffs office":        "Orange",
    "orange county sheriff's office":       "Orange",
    "orange county":                        "Orange",
    "rockingham co sheriff":                "Rockingham",
    "rockingham co sheriff's dept":         "Rockingham",
    "rockingham co sheriff's office":       "Rockingham",
    "rockingham county":                    "Rockingham",
}

# ── Output column order ───────────────────────────────────────────────────────
FIELDNAMES = [
    # identifiers
    "year", "jurisdiction", "agency_name", "agency_code",
    # Tier 1 — high-level
    "population_estimate",
    "incident_total", "offense_total", "group_a_crimes_per_100k",
    "total_arrests", "adult_arrests", "juvenile_arrests", "arrests_per_100k",
    "total_group_a_offenses",
    "total_group_b_adult_arrests", "total_group_b_juvenile_arrests",
    # Tier 2 — Group A offense-specific (reported count)
    "aggravated_assault_reported",
    "simple_assault_reported",
    "burglary_breaking_entering_reported",
    "destruction_damage_vandalism_reported",
    "motor_vehicle_theft_reported",
    "shoplifting_reported",
    "theft_from_motor_vehicle_reported",
    "all_other_larceny_reported",
    "drug_narcotic_violations_reported",
    "drug_equipment_violations_reported",
    "weapon_law_violations_reported",
    # Tier 2 — Group B arrest-specific (adult count)
    "dui_group_b_adult",
    "drunkenness_group_b_adult",
    "disorderly_conduct_group_b_adult",
    "trespass_real_property_group_b_adult",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _num(text: str) -> Optional[float]:
    """Parse a number string, stripping commas and whitespace.  Returns None if
    the value cannot be converted."""
    if text is None:
        return None
    cleaned = text.replace(",", "").strip()
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _norm(text: str) -> str:
    """Lower-case, collapse whitespace, strip punctuation noise."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _match_line(lines: list[str], *patterns: str) -> Optional[re.Match]:
    """Return the first line that matches any of the supplied regex patterns."""
    for pat in patterns:
        rx = re.compile(pat, re.IGNORECASE)
        for line in lines:
            m = rx.search(line)
            if m:
                return m
    return None


def _extract_right_numbers(line: str) -> list[str]:
    """Extract all numeric tokens from a line (handles commas in numbers)."""
    return re.findall(r"[\d,]+\.?\d*", line)


# ── Per-page extraction ───────────────────────────────────────────────────────

def parse_page(text: str) -> Optional[dict]:
    """Parse one page of extracted text into a flat descriptor dict.

    Returns None if the page cannot be identified as a valid jurisdiction page.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rec: dict[str, object] = {f: None for f in FIELDNAMES}

    # ── Header: agency name, agency code, year ─────────────────────────────
    # Pattern: "Albemarle County Police Department - VA0020300 - NIBRS Agency Crime Overview - 2019"
    header_rx = re.compile(
        r"^(.+?)\s*-\s*(VA\d+)\s*-\s*NIBRS Agency Crime Overview\s*-\s*(\d{4})",
        re.IGNORECASE,
    )
    header_match = None
    for line in lines[:5]:
        header_match = header_rx.match(line)
        if header_match:
            break

    if not header_match:
        log.debug("  Skipping page — no NIBRS header found")
        return None

    raw_agency = header_match.group(1).strip()
    rec["agency_name"] = raw_agency
    rec["agency_code"] = header_match.group(2).strip()
    rec["year"] = int(header_match.group(3))

    # Normalise agency name to study jurisdiction
    agency_lower = _norm(raw_agency)
    jurisdiction = None
    for key, val in NAME_TO_JURIS.items():
        if key in agency_lower or agency_lower in key:
            jurisdiction = val
            break
    if jurisdiction is None:
        # Fallback: try matching first two words of agency name against county names
        for key, val in NAME_TO_JURIS.items():
            if agency_lower.startswith(key.split()[0]):
                jurisdiction = val
                break
    rec["jurisdiction"] = jurisdiction

    # ── Population estimate ────────────────────────────────────────────────
    for line in lines:
        m = re.search(r"Population Estimate\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            rec["population_estimate"] = _num(m.group(1))
            break

    # ── Offense Overview ───────────────────────────────────────────────────
    for line in lines:
        m = re.search(r"Incident Total\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            rec["incident_total"] = _num(m.group(1))
        m = re.search(r"Offense Total\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            rec["offense_total"] = _num(m.group(1))
        m = re.search(r"Group A Crimes per 100,?000\s+population\s+([\d,]+\.?\d*)", line, re.IGNORECASE)
        if m:
            rec["group_a_crimes_per_100k"] = _num(m.group(1))
        # Sometimes the rate is on the same line as the label but split across two lines
        m = re.search(r"Group A Crimes per 100,?000\s+([\d,]+\.?\d*)", line, re.IGNORECASE)
        if m and rec["group_a_crimes_per_100k"] is None:
            rec["group_a_crimes_per_100k"] = _num(m.group(1))

    # ── Arrest Overview ────────────────────────────────────────────────────
    for line in lines:
        m = re.search(r"^Total Arrests\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            rec["total_arrests"] = _num(m.group(1))
        m = re.search(r"^Adult Arrests\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            rec["adult_arrests"] = _num(m.group(1))
        m = re.search(r"^Juvenile Arrests\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            rec["juvenile_arrests"] = _num(m.group(1))
        m = re.search(r"Arrests per 100,?000 population\s+([\d,]+\.?\d*)", line, re.IGNORECASE)
        if m:
            rec["arrests_per_100k"] = _num(m.group(1))

    # ── Total Group A Offenses (bottom row of Group A table) ──────────────
    for line in lines:
        m = re.search(r"Total Group A Offenses\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            nums = _extract_right_numbers(line)
            if nums:
                rec["total_group_a_offenses"] = _num(nums[0])
            break

    # ── Total Group B Arrests (bottom row of Group B table) ───────────────
    for line in lines:
        m = re.search(r"Total Group B\s+([\d,]+)", line, re.IGNORECASE)
        if m:
            nums = _extract_right_numbers(line)
            if len(nums) >= 2:
                rec["total_group_b_adult_arrests"]    = _num(nums[0])
                rec["total_group_b_juvenile_arrests"] = _num(nums[1])
            elif len(nums) == 1:
                rec["total_group_b_adult_arrests"] = _num(nums[0])
            break

    # ── Group A offense-specific rows ─────────────────────────────────────
    # The PDF is two-column; pdfplumber merges both columns into one line.
    # A line may look like:
    #   "Offense Total 4,042 Aggravated Assault 72 32 0"   ← left col + right col
    #   "Aggravated Assault 72 32 0"                       ← right col only
    # Strategy: split the line on the offense name pattern and take numbers
    # from the RIGHT side of the split (i.e., after the offense label).
    GROUP_A_MAP = {
        "aggravated_assault_reported":            r"Aggravated Assault\b",
        "simple_assault_reported":                r"Simple Assault\b",
        "burglary_breaking_entering_reported":    r"Burglary/Breaking\s*&\s*Entering",
        "destruction_damage_vandalism_reported":  r"Destruction/Damage/Vandalism",
        "motor_vehicle_theft_reported":           r"Motor Vehicle Theft\b",
        "shoplifting_reported":                   r"Shoplifting\b",
        "theft_from_motor_vehicle_reported":      r"Theft From Motor Vehicle\b",
        "all_other_larceny_reported":             r"All Other Larceny\b",
        "drug_narcotic_violations_reported":      r"Drug/Narcotic Violations\b",
        "drug_equipment_violations_reported":     r"Drug Equipment Violations\b",
        "weapon_law_violations_reported":         r"Weapon Law Violations\b",
    }
    for field, pattern in GROUP_A_MAP.items():
        rx = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            m = rx.search(line)
            if m:
                # Take the substring AFTER the matched offense name
                right_part = line[m.end():]
                nums = _extract_right_numbers(right_part)
                if nums:
                    rec[field] = _num(nums[0])
                break

    # ── Group B arrest-specific rows ───────────────────────────────────────
    # Group B table columns: Offense | Adult | Juvenile
    # Same two-column merge issue — split on offense name, take numbers from right.
    GROUP_B_MAP = {
        "dui_group_b_adult":                    r"Driving Under the Influence(?!\s*-\s*Marijuana)",
        "drunkenness_group_b_adult":            r"Drunkenness\b",
        "disorderly_conduct_group_b_adult":     r"Disorderly Conduct\b",
        "trespass_real_property_group_b_adult": r"Trespass of Real Property\b",
    }
    for field, pattern in GROUP_B_MAP.items():
        rx = re.compile(pattern, re.IGNORECASE)
        for line in lines:
            m = rx.search(line)
            if m:
                right_part = line[m.end():]
                nums = _extract_right_numbers(right_part)
                if nums:
                    rec[field] = _num(nums[0])
                break

    return rec


# ── PDF-level extraction ──────────────────────────────────────────────────────

def extract_pdf(pdf_path: Path) -> list[dict]:
    """Extract all jurisdiction pages from a single PDF."""
    results = []
    log.info(f"Processing {pdf_path.name} …")
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                log.debug(f"  Page {i}: no text extracted, skipping")
                continue
            rec = parse_page(text)
            if rec is None:
                log.debug(f"  Page {i}: not a jurisdiction page, skipping")
                continue
            juris = rec.get("jurisdiction") or rec.get("agency_name", "UNKNOWN")
            year  = rec.get("year", "?")
            log.info(f"  Page {i}: {juris} ({year})")
            results.append(rec)
    return results


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract county-year crime descriptors from Virginia NIBRS PDFs."
    )
    parser.add_argument(
        "--pdfs", nargs="+", required=True,
        help="One or more Crime_In_Virginia_<YEAR>a.pdf files",
    )
    parser.add_argument(
        "--output", default="virginia_crime_county_year.csv",
        help="Output CSV file path (default: virginia_crime_county_year.csv)",
    )
    args = parser.parse_args()

    all_records: list[dict] = []
    for pdf_arg in args.pdfs:
        pdf_path = Path(pdf_arg)
        if not pdf_path.exists():
            log.error(f"File not found: {pdf_path}")
            sys.exit(1)
        all_records.extend(extract_pdf(pdf_path))

    if not all_records:
        log.error("No records extracted. Check PDF paths and format.")
        sys.exit(1)

    # Sort by year then jurisdiction for readability
    all_records.sort(key=lambda r: (r.get("year") or 0, r.get("jurisdiction") or ""))

    out_path = Path(args.output)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_records)

    log.info(f"Wrote {len(all_records)} rows → {out_path}")

    # Print a quick summary table
    from collections import Counter
    counts = Counter((r.get("year"), r.get("jurisdiction")) for r in all_records)
    print(f"\n{'Year':<6}  {'Jurisdiction':<20}  {'Records':>7}")
    print("-" * 38)
    for (yr, jur), n in sorted(counts.items()):
        print(f"{str(yr):<6}  {str(jur):<20}  {n:>7}")


if __name__ == "__main__":
    main()
