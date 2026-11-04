# Connecting Connecticut fields and water

This project stores public mapping locally and preserves the distinction between a mapped connection, a nearby feature, and an actual flow observation. The selected river-network extent is longitude −73.8 to −71.7 and latitude 40.9 to 42.1: Connecticut plus a border buffer. Counts therefore include some neighboring-state features. Individual geometries are not clipped at the state line. Gauge drainage basins can extend much farther upstream, including beyond Connecticut.

The completed snapshot contains **102,076 HR river-network segments, 99,147 catchments, 49,890 waterbodies, 92 gauge references and 4,308 public dams**, plus the separate current 3DHP layers. All ten map layers passed file-hash, feature-count and identifier checks. The five regional archives total about 800 MB.

**11,758 of 11,759 candidate fields** intersect an HR catchment; none of their combined catchment fractions exceeds 101%. The unmatched candidate is `osm-way-1186114605` in East Haven. The network has official references for 55 of the 69 recently reporting gauges and connects 6,976 field candidates to downstream gauges at reach level. The independent approximate NLDI basin overlap count is 7,422. These methods and their outlet-position limitations differ, so the counts are not interchangeable. All field-linked HR catchment IDs have a corresponding downloaded network reach.

22,082 waterbody features link to network paths; 21,984 have candidate outlet reaches. Their forecasts remain unset because a mapped outlet does not supply an observed training history. The 55 trained gauge forecasts are described separately in `STREAMFLOW-TRAINING.md`.

## Sources

- [USGS NHDPlus High Resolution](https://hydro.nationalmap.gov/arcgis/rest/services/NHDPlus_HR/MapServer): network flowlines, catchments, waterbodies and official gauge references. The legacy network provides stable identifiers and downstream topology.
- [USGS 3D Hydrography Program](https://www.usgs.gov/3d-hydrography-program/access-3dhp-data-products): current flowlines, waterbodies, catchments, hydro locations and work-unit coverage. These are retained as a separate source; presence in the service does not mean every location has newly surveyed elevation-derived mapping.
- [USGS NLDI](https://api.water.usgs.gov/nldi/linked-data): gauge identifiers and full upstream drainage polygons for 69 recently reporting gauges. Its NHDPlus V2 COMIDs must not be joined directly to NHDPlus HR IDs.
- [StreamStats](https://www.usgs.gov/streamstats/web-services): independent gauge drainage delineations. The older service was retired January 30, 2026; this project uses `ss-delineate/v1/delineate/sshydro/CT`. The [January 2026 workflow](https://s3.us-east-1.amazonaws.com/streamstats.usgs.gov/StreamStatsFlowStatisticsWorkflow.pdf) also documents the replacement basin-characteristic service. The saved Mill River calculation reports 24.5 square miles of upstream drainage.
- [Connecticut public dams](https://services1.arcgis.com/FjPcSmEFuDYlIdKC/arcgis/rest/services/Dams_Public/FeatureServer/0): public locations and available attributes. As described by [CT DEEP](https://portal.ct.gov/deep/water/dams/dams-safety), this public layer excludes public water-supply dams. It contains no future operating schedule.
- [Connecticut Streamflow and Sustainable Water Use Estimator](https://www.sciencebase.gov/catalog/item/5b7998b1e4b0f5d578845498): downloadable Access database and readme. This is a historical estimation tool, not measured daily discharge or a live forecast. It is archived separately and is not executed or used as observed training data.

## Relationships saved

`outputs/river-network/farm-drainage-links.json` uses the existing candidate-field IDs to join with precipitation, groundwater-context, town, parcel and watershed outputs. It records the share of each field inside each gauge's NLDI basin and each HR catchment. Areas are calculated in an equal-area projection. Point candidates receive point-in-polygon membership, not invented acreage. A field can contribute to several nested downstream gauge basins; those fractions should not be added across gauges.

The NLDI `splitCatchment=true` service returned HTTP 502 errors for all 69 requests. Whole-catchment basins are therefore retained, explicitly labeled: they can include some land downstream of a gauge within its local catchment. Five basin areas differ from the published gauge drainage area by more than 25% and are flagged. This is approximate drainage association, not a confirmed connection at every gauge position. The failed requests are preserved in `splitbasins-download-status.json`.

`directed-reaches.json` links HR reaches using the main and minor downstream hydrosequence references. References that leave the selected download extent remain explicitly unresolved. Full gauge basins supplement this geographically bounded network. Official HR gauge references, when available, support upstream traversal to fields. A field catchment containing a gauge is geographically associated with that reach; this alone cannot prove the field enters upstream of the exact gauge position.

`waterbody-links.json` connects waterbody permanent identifiers to their network paths, then lists candidate inlet and outlet reaches. These are topological candidates, not surveyed outlet-control structures. Waterbody forecasts remain null unless an appropriately located, validated discharge record is established. Lakes do not receive invented streamflow or lake-level forecasts.

`gauge-reach-candidates.json` distinguishes official HR references from nearest-line suggestions. `dam-reach-links.json` reports proximity and distance only: it does not silently turn the nearest stream into a confirmed hydraulic connection. Dam release and withdrawal histories are absent from the model.

`drainage-boundary-comparison.json` compares StreamStats and NLDI basin areas and their intersection divided by union. Overlap below 80% is flagged for review. Several raw gauge-coordinate StreamStats requests returned implausibly tiny polygons: those require corrected outlet placement and are not used for field links. Mill River's overlap is approximately 94.5%. The NLDI gauge basins supply the field links; neither source is silently treated as ground truth.

`summary.json`, `validation.json` and the source download-status files record counts, gaps and checks. The PNG/SVG overview shows candidate fields, larger physical streams, drainage basins and forecast locations. Artificial network paths are retained in the data but omitted from the overview drawing.

## Limits

The 11,759 field outlines and locations are candidates, not confirmed operating-farm boundaries. Surface drainage does not establish groundwater flow, irrigation availability, legal water access or streamflow at a farm. The trained forecasts apply to monitored gauges only. The mapping supplies the foundation for later regional modeling at ungauged outlets, but does not itself validate that extrapolation.

The current 3DHP selection contains 105,953 flowlines, 29,015 waterbodies and 1,731 catchments. Of its flowlines, 103,640 carry the legacy `NHD` work-unit label and 2,313 belong to the newer Westfield River work unit. Only 15 candidate fields intersect its available detailed catchments. The broader HR layer remains necessary for statewide field mapping. Separate 3DHP edge, waterbody, farm-catchment and gauge-proximity files preserve this distinction.

See `STREAMFLOW-TRAINING.md` for the model, test periods and errors. Geography remains separate from model inputs to preserve the requested discharge-only experiment.

## Rebuild

Run the workspace Python environment with these scripts, in order:

1. `scripts/fetch_river_network.py maps`
2. `scripts/fetch_river_network.py basins`
3. `scripts/fetch_river_network.py streamstats`
4. `scripts/fetch_river_network.py history`
5. `scripts/link_river_network.py`
6. `scripts/train_streamflow_history.py`
7. `scripts/validate_river_network.py`
8. `scripts/validate_trained_streamflow.py`
9. `scripts/render_river_research.py`

Downloads resume from checked batches. Archived files are snapshots, not an automatic refresh service.

When the HR map-query service stalled, `scripts/fetch_hydrography_bulk.py` provided a fallback using official regional FileGDB packages discovered through the National Map product catalog (`bulk-catalog.json`). Five regional packages cover the selected extent; national packages are excluded. This preserves catchment and waterbody identifiers while avoiding thousands of remote queries. These packages have 2022–2023 publication dates; counts differ from the service inventory, so source versions are preserved. Regional archive source URLs and hashes are stored beside each download. Gauge references were retrieved from their separate map-service layer. `scripts/fetch_river_network.py modern` independently retrieves public dams and 3DHP layers. Run `scripts/link_modern_hydrography.py` for their separate relationships and `scripts/summarize_river_downloads.py` to verify the full download inventory.
