# GO-18338 Nearby Galaxies Treasury — Working Group Update
**Slide-by-slide draft for Google Slides**  
Source material: HST Cycle 34 Large/Treasury scientific justification; JWST MCT white paper; Phase II APT catalog (`go18338_targets.json`, source `phase2-apt`, updated 2026-10-06).

> Placeholders in `[brackets]` need your confirmation (people, scheduling numbers, dates).

---

## Slide 1 — Title
**Title:** GO-18338 Nearby Galaxies HST Treasury  
**Subtitle:** Working group update — program goals, status, synergies, and next steps  
**Footer:** Charles Kilpatrick · [Meeting / date]

---

## Slide 2 — Agenda
1. Program goals, data, science plan, and STScI deliverables  
2. Working-group status and long-term plan  
3. Phase II / APT and observation status (GO-18338)  
4. Synergies (Roman, HST, JWST, Euclid)  
5. How we organize going forward  
6. JWST Multi-Cycle Treasury (MCT) — due **Nov 4** — read / comment / endorse  

---

## SECTION 1 — Goals & deliverables

## Slide 3 — Why this program exists
- Nearby (<20 Mpc) star-forming galaxies anchor stellar populations, structure, and SN progenitors  
- Only ≲25% of luminous disks in this volume had multi-band HST UV/optical coverage (pre-program)  
- Rubin / Roman / Euclid will not replace HST UV + sub-arcsecond resolution for massive stars  
- Aligns with Cycle 34 Special Initiatives: **LTM**, **Hubble–Roman Science (HRS)**, **HWO Precursor (HPS)**

## Slide 4 — Goals (science)
- Complete UV/optical resolved-star baselines for **121** luminous SF galaxies at <20 Mpc still missing required filters  
- Enable SN progenitor / site priors before Rubin/LSST explosions (irrecoverable post-explosion)  
- Long-baseline first epoch for variability and **failed-SN** tests  
- Halo **ACS parallels** → TRGB-ready fields + distances where feasible  

## Slide 5 — What data we get
- **Primary:** WFC3/UVIS gap-filling in **F336W / F606W / F814W** (only missing combinations)  
  - Depth goals: M_F336W < −4.3, M_F606W < −3.5, M_F814W < −3.8 AB  
  - Up to **2 orbits/target**; program total **193 WFC3 orbits** (excl. parallels)  
- **Parallels:** ACS **F606W+F814W** halo fields (~6′ offset) on **69** two-orbit targets → **138** parallel orbits  
  - Omit parallels for 9 hosts covered by JWST-GO-7763 TRGB  
- **No proprietary period** (Treasury)

## Slide 6 — What we proposed to do with the data
- Gaia-aligned photometry with **JHAT** + **DOLPHOT** (crowded-field optimized)  
- Resolved stellar SEDs for massive stars / binaries; deblend vs Rubin/Euclid/Roman  
- First-epoch catalogs for multi-mission time domain + failed-SN / merger diagnostics  
- TRGB distances + RGB calibrators from parallel halo fields  
- Products designed to combine with Roman WFI (crowding mitigation, CCS/GA planning)

## Slide 7 — Required STScI / Treasury deliverables
- Coordinate with STScI on **photometric catalogs** of resolved stellar populations (Hubble–Roman science)  
- Deliver for every primary + parallel:  
  - Robust DOLPHOT photometry + **limiting magnitudes from fake-star tests**  
  - F336W / F606W / F814W catalogs  
- High-level science products: **TRGB distances** and RGB calibrators  
- LTM/HRS/HPS: calibrated first-epoch imaging, aligned catalogs, completeness-characterized photometry  

---

## SECTION 2 — Working-group status

## Slide 8 — Working group: who & what so far
- **PI / coordination:** Charles Kilpatrick  
- **Core contributors so far:** [names — e.g. Aswin Suresh, …]  
- Work to date (examples to keep / edit):  
  - Phase II APT complete → **121 prime + 69 parallel** fields ingested  
  - Reduction / campaign infrastructure (WINGS + st123): download → JHAT → mosaic → DOLPHOT → catalogs  
  - Full-field remosaic + photometry refresh underway for early products / QA  
  - [Other WG activities: target vetting, parallel orients, documentation, …]

## Slide 9 — Long-term plan (WG)
- Near-term: finish Phase II implementation follow-up; pipeline maturity; early HLSP prototypes  
- Mid-term: as visits execute → automated reduction, QA, catalog releases  
- Longer-term: HLSP delivery to MAST; synergy products with Roman / Euclid / JWST; papers  
- Governance: [cadence of WG meetings; Slack/GitHub; who owns photometry / TRGB / SN / HLSP]

---

## SECTION 3 — APT & observations

## Slide 10 — Phase II / APT summary
- Program: **HST-GO-18338** (Treasury / Large)  
- Phase II source: public APT + internal catalog (`phase2-apt`, updated **2026-10-06**)  
- Target count in APT catalog: **190** fields = **121 prime** + **69 ACS parallels**  
- Strategy: flexible scheduling for most targets; orient restrictions only where required  
  - Noted special cases: **NGC 1350**, **UGC 11920** (bright-star contamination → orient limits)

## Slide 11 — Observation / implementation status
- Public Phase II APT: https://www.stsci.edu/hst/phase2-public/18338.apt (Apt 2026.5.1)  
- Official title: *Completing a Legacy Dataset with Deep HST Imaging of 121 Nearby Star-Forming Galaxies*  
- **All 120 APT visits currently `Status="implementation"`** (none flown yet as of APT pull)  
- Scheduling windows present in APT; flexible scheduling for most targets  
- Local WINGS catalog: 121 prime + 69 parallel fields ready for reduction when data land  
- Open items: [Contact Scientist notes; NGC 1350 / UGC 11920 orient restrictions]

## Slide 12 — Early reduction status (optional, if useful)
- Reduction tree live under `/data/ckilpatrick/go18338/` for APT targets with archival / early frames  
- Full-field mosaic + DOLPHOT refresh in progress across campaign  
- Known hard cases so far: **ic5267** (WFC3 UV/blue L3 reject), **ngc1350** (JHAT catastrophic residual ~350 mas)  
- Goal: public-ready catalogs aligned to Treasury deliverable standards  

---

## SECTION 4 — Synergies

## Slide 13 — Synergy map
| Facility / program | Overlap / value |
|---|---|
| **Aswin — Roman Cycle 1** | [title / targets / how HST UV/opt priors feed Roman] |
| **Maria — failed SN (HST/Roman)** | LTM baseline + UV for disappearing-star / failed-SN tests |
| **JWST (archival + GO)** | IR cool/dusty stars; SED baselines; TRGB (e.g. GO-7763) |
| **JWST MCT (this Nov)** | Gap-fill NIRCam six-filter census on luminous disks |
| **Euclid DR1** | Wide VIS+NIR context; HST resolves what Euclid blends |
| **Rubin/LSST** | Transient discovery ↔ HST progenitor/site priors |
| **Roman HLWAS / HLTDS** | HRS products; crowding priors; CCS/GA planning |

## Slide 14 — Synergies — talking points
- HST supplies the **UV/optical half** of the Local Volume census; JWST/Roman supply IR  
- Failed-SN and progenitor science needs **pre-explosion** HST depth + multi-mission cadences  
- Euclid DR1: immediate wide-field context; our catalogs provide deblended stellar truth samples  
- Aswin’s Roman program: [1–2 bullets you want emphasized]  
- Maria’s failed-SN work: [1–2 bullets]

---

## SECTION 5 — Organization going forward

## Slide 15 — Where the work lives
- **Coordination / science decisions:** WG meetings + [Slack / email list]  
- **Phase II / scheduling:** PI ↔ STScI Contact Scientist; APT updates as needed  
- **Reductions & catalogs:** [Northwestern / WINGS+st123 pipeline; who runs batches]  
- **Science workstreams:** photometry QA · TRGB · SN progenitors / failed SN · HLSP / papers  
- **External synergies:** Roman (Aswin et al.), JWST MCT, Euclid cross-matches  

## Slide 16 — Near-term asks of the group
- Review early catalogs / QA for [subset of targets]  
- Nominate owners for workstreams above  
- Flag Roman / JWST / Euclid projects that need early HST products  
- Read & endorse JWST MCT (next slide)

---

## SECTION 6 — JWST MCT

## Slide 17 — JWST MCT (due Nov 4)
**Title:** Completing a Census of Infrared Emission from Resolved Stars in Nearby Galaxies with JWST  
- Gap-filling **Multi-Cycle Treasury**: ~**120** luminous SF hosts at <25 Mpc → near-complete **six-filter NIRCam** disk coverage  
- ~**6×** increase over ~21 science-ready disks today  
- ~**600 charged hours** over **3 cycles**  
- Filters spanning ~0.9–4.4 µm (e.g. F090W/F115W, F150W, F200W, F277W, F356W, F444W)  
- Deliverable: public resolved-star catalogs + physical parameters (RSG/AGB/RGB, dusty progenitors)

## Slide 18 — How to help (by Nov 4)
- **Read** the white paper / draft proposal  
- **Comment** (science, target list, filter strategy, synergies with GO-18338)  
- **Endorse / co-author** if you want to be listed  
- Contact: Charles Kilpatrick · ckilpatrick@northwestern.edu  
- Shared draft: [link]

## Slide 19 — Closing
- GO-18338 is the UV/optical Treasury backbone for Local Volume massive-star & progenitor science  
- Pipeline + WG structure coming online as visits execute  
- Synergies with Roman, JWST, Euclid, Rubin are intentional — join the workstreams  
- **Action:** MCT comments/endorsements by **Nov 4**  

## Slide 20 — Backup / references
- HST Cycle 34 Large Program scientific justification (attached)  
- JWST MCT Nearby Galaxies white paper (attached)  
- Public APT: `https://www.stsci.edu/hst/phase2-public/18338.apt`  
- Campaign catalog: WINGS `go18338_targets.json` (121+69 fields)
