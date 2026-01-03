# EDGAR XBRL Statement Pipeline

This repository documents a practical pipeline for extracting structured, statement-level financial data from SEC EDGAR filings using XBRL linkbase files and the SEC companyfacts API.

The project began as an exploration of SEC JSON endpoints, progressed through an attempted Arelle-based iXBRL approach, and ultimately converged on a reliable linkbase-driven methodology.

## Why this exists
EDGAR filings contain machine-readable financial data, but:
- Company facts JSON lacks statement structure and ordering
- HTML tables are inconsistent and fragile
- Some iXBRL tooling is environment-sensitive

This project reconstructs full statement views directly from XBRL linkbases (`*_pre.xml`, `*_lab.xml`) while sourcing numeric values from SEC companyfacts.

## Scripts (current state)

### `xbrlpull.py`
Initial SEC JSON exploration:
- Pulls filings metadata
- Pulls companyfacts
- Filters facts to the latest 10-K

### `10Kstatements.py`
Attempted Arelle-based solution:
- Loads iXBRL/DTS via Arelle
- Retained for reference due to environment-specific issues

### `10_linkbase.py`
Working solution:
- Parses presentation and label linkbases
- Reconstructs statement hierarchies
- Outputs one CSV per presentation role

## Output
CSV files representing statements and note tables, including:
- indentation depth
- line item labels
- XBRL concept identifiers
- period-correct values

## Status
This repository is a working proof-of-concept intended to be extended into:
- multi-company pipelines
- trend analysis
- dashboards and client-facing reporting
