# INRIX XD road network segments
Manage INRIX XD road network segments

## Directory structure
Scripts related INRIX XD road network segments are located in `INRIX/xd_segments/` and `Conflation` (because there is a script conflating the CMP and DTA networks in that directory so not sure how best to organize the directory tree)

## Location of data
### CMP network (see README.md in the root directory of this repo)
### INRIX XD shapefiles
- traffic data are in: `Q:\Data\Observed\Streets\INRIX`
  - the downloaded data are filed by map release version (the `vyy0x` directories (e.g. v2301 for map release 23.1))
- map/shapefiles are in: `Q:\GIS\Transportation\Roads\INRIX\XD`
  - starting from map version 2202, the map version directory name format is changed from ##_0# to ##0# 

## Determining the map version for downloaded INRIX data
- the map version for the downloaded INRIX data can be determined in `reportContents.json` in the `mapVersion` field

## INRIX Map Version updates
- INRIX updates their map version twice a year, in March and September
- 'we roll up all XD data to the most current map. This means that all data within your downloads is on our current map. However, if you were to wait to download this data until our next map update you would find that all of the data would be on the that map.  This means that it DOES matter when you download the data because it will have slightly different segmentation. There is typically at 5-10% difference in segmentation.'
- map data can be downloaded at https://map-data-downloader.inrix.com/

### Network conflation process
The INRIX XD road network segments are matched to CMP road segments via a network conflation process. The initial network conflation process is recorded in `Q:\CMP\LOS Monitoring 2019\Network_Conflation\Network Conflation Process Memo.docx`. The TRB paper and presentation are at `O:\Presentations, Conferences, Training, Awards\Conferences, Awards\TRB\2021\Annual Meeting\CMP Pipeline`. Also some scripts in `Q:\Model Projects\101_280\notebooks\Validation`. One of them, `compare_correspondences.ipynb`, is meant to assess the quality of alternative corresonponce files.

### Updating network conflation after each INRIX map version update
Also reference "XD - Map Update - Best Practices for Map Matching.docx" on the Documents section of https://map-data-downloader.inrix.com/

The network conflation correspondences have to be updated after each INRIX map version update. The updating process involves regenerating the network conflation correspondences file with the new INRIX map data. The correspondences file should stay mostly the same as the previous version's file (unless INRIX did a major update to its road segments).

The inputs/outputs for the conflation process are located at `Q:\Data\Observed\Streets\INRIX\vyy0x\network_conflation\CMP\` (except for the data downloaded directly from INRIX, the storage location of which is specified in the "Location of data" section above). The results are stored in a correspondences CSV file in this directory.

Historical notes:
Up to INRIX XD update `v2501`, conflation results were saved at `Q:\CMP\LOS Monitoring yyyy\Network_Conflation\vyy0x\`. (`v2501` itself was conflated again with EPSG:7131 at the current/new directory.)

In the following, `yy0x` refers to the map release version (e.g. 2301 for map release 23.1).

1. Every March and September, download the latest map release at https://map-data-downloader.inrix.com/
    1. Create a `yy0x` directory under `Q:\GIS\Transportation\Roads\INRIX\XD` to place the downloaded data.
    2. Download the following files to `Q:\GIS\Transportation\Roads\INRIX\XD\yy0x\`:
        1. Shapefiles: USA CA Bay Area  
        2. XDAdded: USA CA
        3. XDRemoved: USA CA
        4. XDReplaced: USA CA
2. Filter for only SF data in the Bay Area shapefile downloaded in step 1.2.1: run `python bayarea_to_sf.py yy0x`.
3. Create `Q:\Data\Observed\Streets\INRIX\vyy0x\network_conflation\CMP\`, where `yy0x` is that the map version was released, e.g. `Q:\Data\Observed\Streets\INRIX\v2501\network_conflation\CMP` for map release version 25.1.
4. Copy `Q:\GIS\Transportation\Roads\INRIX\XD\vyy0x\INRIX_XD-SF-yy0x.gpkg` (created in step 2) into `Q:\Data\Observed\Streets\INRIX\vyy0x\network_conflation\` (created in step 3).
5. `Conflation/SF_CMP_INRIX_Network_Conflation.py`.
    1. Copy `cmp_scripts/Conflation/cmp_inrix_network_conflation_vyy0x.toml` to `Q:\Data\Observed\Streets\INRIX\vyy0x\network_conflation\CMP\` (created in step 3), and rename to `cmp_inrix_network_conflation_v2501-{monthly, biennial}.toml`
    2. Change the `inrix_map_version` (to `yy0x`, i.e. the current INRIX map release version), `mode` (to `"biennial"` if conflating onto the CMP network (as in the biennial reports) or `"monthly"` if conflating onto the online monthly congestion dashboard network) , and `output.dir` variables as appropriate.
    3. Leave `manual_update` as `true`. Start by using `manual_add.csv` and `manual_remove.csv` from the previous update.
    4. `uv run Conflation/SF_CMP_INRIX_Network_Conflation.py Q:\Data\Observed\Streets\INRIX\vyy0x\network_conflation\CMP\cmp_inrix_network_conflation_v2501-{monthly, biennial}.toml`.
    5. Probably: make changes to `manual_add.csv` and `manual_remove.csv` as needed and rerun step 4.
6. `xd_diff.ipynb` can then be used to explore the differences between the current and the last map version of the INRIX XD road network. (And probably potentially loop back to step 5.4 and 5.5 if necessary).
7. If desired, use GIS software to visualize the results for further verification.
8. For network conflation with the monthly COVID tracker network (i.e. not the CMP network as in reports) rename/add "-expandednetwork.csv" at the end of the two correspondence files (one "Manual" one not).