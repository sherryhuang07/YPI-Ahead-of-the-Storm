# First drought-model layer: watersheds

We use Connecticut DEEP's subregional drainage basins as the first geographic units. These nest into regional and major drainage areas. They are Connecticut basin identifiers, not federal HUC identifiers; joining federal datasets will require a spatial match or a verified crosswalk.

The downloaded polygon layer contains **374 records, 335 distinct subregional IDs, 44 regional IDs, and 8 major IDs**. Multiple polygon records may share one basin ID. The build groups those records without dropping their original geometry. Historical descriptive pages give some different counts; the application reports the actual downloaded records and unique identifiers.

The eight major areas are Pawcatuck, Southeast Coast, Thames, Connecticut, South Central Coast, Housatonic, Southwest Coast, and Hudson. Coastal groups contain multiple coastal catchments rather than one single river outlet.

## Source and reproducibility

- [Official CT DEEP polygon service](https://services1.arcgis.com/FjPcSmEFuDYlIdKC/ArcGIS/rest/services/Connecticut_Subregional_Drainage_Basin/FeatureServer/1)
- [CT ECO basin definitions and limitations](https://cteco.uconn.edu/guides/Subregional_Basin.htm)
- [CT ECO major basin guide](https://cteco.uconn.edu/guides/Major_Basin.htm)

The original download uses longitude/latitude coordinates (WGS84). Source metadata and the server's record count are retained alongside it. The generated catalog records retrieval time and a SHA-256 fingerprint. Rebuilding checks the record count, geometry types, identifiers, and nesting. Map paths are simplified only for display; analysis geometry is unchanged.

## What these boundaries do and do not tell us

The original source extent includes neighboring-state portions and is not clipped to Connecticut. Retaining these pieces avoids discarding cross-border context, but this layer does not represent every complete upstream contributing area. State-only summaries will require a separate Connecticut boundary mask. Basin numbering describes nesting; it is not a downstream routing network. Do not sum neighboring basins as upstream contributors without verified flow connections.

These are legacy topographic boundaries, with mapping completed in 1988 according to CT ECO. Later development, drainage changes, and artificial diversions may differ from mapped natural drainage. Field-scale decisions require finer information. No farm has been assigned to a watershed yet; field polygons may overlap more than one basin.

Watersheds organize surface drainage. They do not by themselves determine rainfall, groundwater flow, root-zone water storage, or agricultural drought. Each model unit currently has a null (unknown) drought status, never a zero-risk default.

## Next model steps

1. Assign farm fields and sensors to these units using their locations, keeping fields that cross boundaries split by area.
2. Add observed precipitation, soil water capacity, current soil moisture, and crop water demand.
3. Add 14-day weather forecast ensembles and verified upstream connections where surface-water supply matters.
4. Calculate and validate soil-water deficits and forecast uncertainty before offering farm actions.

No drought scores, flow directions, farm strategies, or forecasts have been inferred from the watershed shapes alone.
