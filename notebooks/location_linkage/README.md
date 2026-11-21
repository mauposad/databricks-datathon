# Location linkage: facility coordinates vs. India Post pincode

Bronze-stage exploration of how far each facility's own coordinates (`facilities.latitude/longitude`) sit from
the location implied by its pincode (`facilities.address_zipOrPostcode` → `india_post_pincode_directory`), broken
down by many different definitions of "region".

Each facility gives an **ordered pair** (pincode point → facility point). We measure the haversine distance, the
bearing, and the north/east offset. Records that can't form a pair (bad pincode, missing or out-of-India
coordinates, etc.) are kept as their own **pair category** and still drawn on every map.

## Run order

1. `00_build_location_pairs`: builds every bronze table (run first; re-run when inputs or widgets change)
2. `01`–`10`: one notebook per region definition (independent of each other; run sequentially, because they
   all write their rows into `bronze_loclink_region_summary`)
3. `11_region_assignment_disagreement`: where the four state sources (pincode, written text, facility
   coordinates, pincode coordinates) disagree, plus shared/default coordinates
4. `12_pincode_point_strategy_comparison`: evidence for the open team question of how to turn a pincode
   (a cloud of post offices) into one point
5. `13_population_clusters`: overlays population clusters (GHSL urban centres, 2025, tiers `1M+` /
   `100k-1M` / `50k-100k`) on the pairs; urban-vs-rural split and per-city stats, with membership taken from
   the facility point and from the pincode point; error vs distance to the nearest city. Downloads the GHSL
   regional file (~67 MB) into the volume on first run. Writes four schemes into `bronze_loclink_region_summary`,
   so don't run it in parallel with 01–10

| # | region definition | groups by |
|---|---|---|
| 01 | India Post circle | pincode → modal `circlename` |
| 02 | India Post region | pincode → modal `regionname` |
| 03 | India Post division | pincode → modal `divisionname` |
| 04 | state per directory | pincode → modal `statename` |
| 05 | district per directory | pincode → modal `statename \| district` |
| 06 | state as written | `address_stateOrRegion`, normalised (city text left unresolved) |
| 07 | state at facility coords | ADM1 polygon containing facility lat/lon |
| 08 | district at facility coords | ADM2 polygon containing facility lat/lon |
| 09 | Zonal Council | zone of the directory state |
| 10 | H3 hexagons | equal-area cell containing facility lat/lon |

All notebooks run on serverless and `%pip install geopandas==1.0.1`. Shared logic lives in `_common`
(`%run ./_common`).

## Widgets

- `out_catalog` / `out_schema` (default `workspace.default`): where `bronze_loclink_*` tables and the
  `loclink_geo` volume go. The source dataset is a read-only Delta Sharing catalog.
- `primary_strategy` (default `office_median`): which pincode point drives the maps and headline tables. Every
  strategy is always computed and stored.
- Notebook 00 only: `trim_km`, `coastal_snap_km`, `h3_res`, `swap_match_km`, `swap_min_km`.

## Outputs

`bronze_loclink_offices`, `_pincodes`, `_pairs` (facility × strategy), `_facility_regions` (region label per
scheme, measured three ways: definition / at facility point / at pincode point), `_region_shapes`,
`_adm2_labels`, `_region_summary` (scheme × region × strategy stats), `_state_agreement`, `_urban_centres` (GHSL
India urban centres with tier and WKT), `_urban_pairs` (pairs × strategy with the cluster containing / nearest to
each end and distance to it).

## Caveats

- Boundaries are geoBoundaries gbOpen (simplified) ADM1/ADM2, downloaded into the `loclink_geo` volume. Postal and
  directory-district outlines are **approximate**: each ADM2 polygon takes the label held by most of the
  geocoded offices inside it.
- The `__pin_pt` region labels always use the `office_median` pincode point, whatever `primary_strategy` is set to.
- GHSL urban centres (EC JRC, CC BY 4.0, cite doi:10.2905/1a338be6-7eaf-480c-9664-3a8ade88cbcd) are
  density-defined clusters, not municipal limits. Contiguous dense belts merge into one very large centre
  (Hajipur–Muzaffarpur, Kozhikode, Kollam), and satellite towns join their metro (Noida/Gurugram are in "New Delhi").
- Notebook 13's pincode-end membership uses the `primary_strategy` point; its notebook output is close to the
  10 MB export limit, so avoid adding large plots there.
