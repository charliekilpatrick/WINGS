# HST-GO-18338 Target Status spreadsheet data

## Import into Google Sheet
1. Open https://docs.google.com/spreadsheets/d/12Stf1mw0zZGk5kmvr9uOLiiZqsJXkkX5f8mThz_tr7o/edit
2. File → Import → Upload → select `GO18338_target_status.csv`
3. Import location: **Replace current sheet**
4. Separator: Detect automatically (comma)
5. Click Import data
6. (Optional) Add a second sheet and import `GO18338_status_legend.csv`

## Contents
- **190 rows**: 121 Primary (WFC3) + 69 Parallel (ACS)
- Sorted by **Earliest_Plan_Window**, then Visit, then Primary before Parallel
- Status defaults to **Not yet observed**
- Distances from NED/GLADE+ cache
- STScI visit status / plan windows from https://www.stsci.edu/hst-program-info/visits/?program=18338 (pulled 2026-10-27)
- Visit **65 (NGC 4501)** is in APT but missing from STScI visit page — flagged in Notes

## Columns
Visit, Field, Target, Target_ID, Host, RA_deg, Dec_deg, RA, Dec, Distance_Mpc, Distance_err_Mpc, Distance_method, Distance_catalog, STScI_Visit_Status, Earliest_Plan_Window, Plan_Windows, Visit_Orbits, Visit_Configs, Instrument, Status, MAST_coord_search, MAST_proposal_target, STScI_visit_page, Reduction_dir, Notes, Orient
