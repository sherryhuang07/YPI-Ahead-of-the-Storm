# Farm-specific geography: Yale Farm pilot

Yale Farm at 345 Edwards Street, New Haven is the first pilot selected by the user. This step imports real public geometry and imagery; it does not yet automate field segmentation or identify every Connecticut farm.

## Results from spatial comparison

- OpenStreetMap way 45092131 supplies a provisional farm-extent polygon, last edited February 22, 2020. Its geodesic area is approximately 0.723 acres. Yale's own description says approximately one acre. Preserve that difference for review; do not adjust the polygon to match a descriptive acreage.
- The provisional outline intersects assessor parcel **14057**, addressed **335 Prospect Street**, over essentially 100% of its area. Parcel records were fetched from the Connecticut GIS Office's live statewide service; nearby records report collection year **2026**, despite older descriptions on some catalog pages. This is a spatial match, not confirmation of tenure or operated acreage.
- The provisional outline falls within CT DEEP subregional basin **5302, Mill River**, regional group 53, major group 5 (South Central Coast). This is an area intersection, not an address or centroid-only assignment.
- Fine-resolution 2023 aerial photography shows beds, structures, paths, and surrounding non-farm land. Aerial image pixel size is not a claim of equivalent positional accuracy. Later imagery and field checks may reveal changes.
- An actual 10-meter Sentinel-2 true-color crop from **October 23, 2026** is saved for the same neighborhood extent. The 20-meter scene classification window contains classes 4 and 5 (vegetation and non-vegetated). This is a neighborhood quality check, not a farm-only cloud statistic, drought assessment, or comparison of crop health across years.

## Data model

Keep three different geometries: assessor property parcels, farmer-confirmed operated farm extent, and separately confirmed growing/management zones. A farm may operate multiple leased or owned parcels. A parcel may include woods, houses, paths, or several operators. Never estimate planted acreage or irrigation demand using the full assessor parcel by default.

The current farm outline has `farmer_confirmed: false`. `confirmed_boundary`, `crop_area_acres`, irrigation source, and recommendation readiness remain unset or false. Growing zones and sensors are empty until mapped. Crop and equipment details cannot be reliably inferred from a parcel record or image alone.

The reusable method for later farms is: fetch nearby public parcels by location; retrieve dated high-resolution aerial evidence and cloud-screened satellite scenes; propose a farm outline; split actual growing areas into management zones; have the operator correct boundaries and confirm tenure, crops, and resources; intersect confirmed zones with watersheds and soil maps. Satellite-derived crop classifications may help find candidates, but land-use codes alone miss institutional/urban farms such as Yale. No statewide farm completeness claim is made.

## Sources

- [Yale's farm description and address](https://www.sustainablefood.yale.edu/the-yale-farm)
- [CT GIS Office parcel program and accuracy limitations](https://portal.ct.gov/datapolicy/gis-office/parcel-and-cama)
- [Live parcel service](https://services3.arcgis.com/3FL1kr7L4LvwA2Kb/arcgis/rest/services/Connecticut_CAMA_and_Parcel_Layer/FeatureServer/0)
- [CT ECO imagery services](https://maps.cteco.uconn.edu/map-services/)
- [OpenStreetMap source outline](https://www.openstreetmap.org/way/45092131), © OpenStreetMap contributors, [ODbL attribution/license](https://www.openstreetmap.org/copyright)
- [Copernicus Sentinel-2 characteristics](https://dataspace.copernicus.eu/data-collections/copernicus-sentinel-missions/sentinel-2)
- [Earth Search catalog](https://earth-search.aws.element84.com/v1/collections/sentinel-2-l2a)

## Reproduce and inspect

Raw responses, geometries, image export extent, Sentinel scene metadata, and derived profile are in `data/yale-farm`. No owner names or mailing addresses were requested in parcel downloads. The original OSM response retains its public edit attribution.

Run `node prepare-yale-farm.mjs` to recompute geometric overlaps, `node extract-satellite.mjs` to fetch the small satellite window (network required), and `node build-farm-map.mjs` to rebuild the comparison. Dependencies are recorded in package.json and pnpm-lock.yaml. Satellite extraction verifies the expected CRS and uses the returned aerial extent, not an assumed image box. Display enlargement uses nearest-neighbor sampling and adds no spatial detail.
