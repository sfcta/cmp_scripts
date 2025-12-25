# CMP_Scripts
Data preparation scripts for the Congestion Management Program (CMP)

## Definitions
- monitoring period: Tue/Wed/Thur in April and May (excluding holidays etc)
- peak periods (in use since (at least) CMP 2007)
  - AM: 7-9am
  - PM: 4:30-6:30pm
  - the earliest instance I could find for this definition was in the LOS Monitoring appendix to CMP 2007, where it also said that the 2004 and 2006 studies used 4-6pm as the PM peak (Carter Burgess 2007 CMP Spring 2007 Level of Service Monitoring, p2; p172 in 2007_CMP_ALL.pdf)

## Map / GIS
- The CMP road network data (for the biennial report) is at Q:\GIS\Transportation\Roads\CMP\cmp_roadway_segments* (see README explaining the differet files in that directory).
- Note that CMP and CHAMP segments are different

## Data directories
2001-2023 data are stored in Q:\CMP\LOS Monitoring 20yy. Starting with the 2023 CMP cycle, I'm trying to start storing metrics calculation outputs (and certain inputs) in Q:\CMP\metrics

### Raw data stored elsewhere
- speed
  - floating car runs: Q:\Data\Observed\Streets\Speed\CMP-floating_car_run\
- transit
  - GTFS: Q:\Data\Networks\Transit\Muni\GTFS

## Sections/Metrics
### Transit
#### APC
##### Download
1. Reach out to SFMTA Transit Performance and Analytics for APC and GTFS data for April & May of the CMP year.
2. Use TD&A's Box account (username: modeling@sfcta.org) for the transfer.
3. Save the APC data to `Q:\Data\Observed\Transit\Muni\APC\`, and the GTFS data to `Q:\Data\Networks\Transit\Muni\GTFS`

##### Parsing
- requires a GTFS stops GIS file, see GTFS section below.
- Run `transit_apc_volume_and_speed.py` with config files as in `transit/apc/configs`. However, it's unclear to Chun Ho (Sept 2023) how the postprocessing csv file is generated.
- use figures.ipynb to create the figures for the report

#### GTFS
##### Download
As of Aug 2023: the MTC feed (which is the official feed for SFMTA) at https://511.org/open-data/transit (Bulk Data Feed -> GTFS Feed Download) has a `service_id` for each day of service in `calendar_dates.txt`, and there is no `calendar.txt`. I.e., no regular service is defined, and all services are defined de novo for each day (i.e. MTC does not give GTFS data based on scheduled service). Also, as of Aug 2023, the historic data feed has to include all operators (`opearator_id=RG` for regional). i.e.
`http://api.511.org/transit/datafeeds?api_key=[your_key]&operator_id=RG&historic=[YYYY-MM]`
or
`http://api.511.org/transit/datafeeds?api_key=[your_key]&operator_id=SF`.

The latest SFMTA GTFS (scheduled) is also available on Data SF: https://data.sfgov.org/Transportation/SFMTA-General-Transit-Feed-Specification-GTFS-Prod/dni7-qpv3

For more historical SFMTA GTFS data (scheduled rather than each day as a special case as on 511.org), reach out to SFMTA (as of 2023: Simon.Hochberg@sfmta.com)

Place the data at `Q:\Data\Networks\Transit\Muni\GTFS\`.
##### Analysis
- For transit coverage calculations: Open `calendar.txt` to find the weekday `service_id` (for the period of analysis).
- For transit volume and speed calculations: Use the GTFS Go plugin in QGIS to get the stops GIS file for input to transit_apc_volume_and_speed.py. Though it seems like `transit/apc/legacy/qaqc/SF_CMP2021_Transit_APC_QAQC.ipynb` has python code to do this extraction.

#### Coverage
##### Calculate transit coverage
1. Make the input toml file. These are saved in 
2. Run e.g. `python transit/coverage/transit_coverage.py 

### Screenline volumes (Bay Bridge and San Mateo County Line)
From PeMS data, use PeMS/.....py

### Speed: LOS and reliability
The [monthly dashboard](https://cmp.sfcta.org/) used to be referred to as real-time, so there are still some references to `realtime`/`rt` left in the code/database.
#### Floating car
0. Not 100% sure, but I think: Before the monitoring period, `speed/inrix/sample_size_analysis.py` is used to determine which CMP segments need to have data collected on floating car runs to supplement the INRIX data.
1. Run `parse_raw_data.py`.
2. Use `compare_years.ipynb` to compare floating car data across years.
#### INRIX (& merging floating car data in)
1. Run the INRIX network conflation code for the CMP roadway network for the biennial reports (see [[speed/inrix/xd_segments/README.md]]).
2. The INRIX data should already be downloaded to directories like `Q:\Data\Observed\Streets\INRIX\v2501\2025\04` for the monthly INRIX dashboard updates. If not, see the [Monthly Congestion Dashboard / INRIX: Data Download and Processing Guide](https://docs.google.com/document/d/1Pt7duNvKq12PCoeR6YsCwzVrQBAEsifi22JmQSo9gx8).
3. Create the TOML config file using the template `speed/inrix/biennial_auto_los_reliability_20yy.toml`.
4. `uv run speed/inrix/biennial_auto_los_reliability.py path/to/biennial_auto_los_reliability_20yy.toml` (with the TOML config file created in the last step)
#### analysis
- `speed/compare_years.ipynb`: scatter plot comparing speeds across 2 years
- `warehouse_scripts\cmp\_README.md`

### Counts
For intersection and midblock counts, see the READMEs in Counts/intersection and Counts/midblock.

## House style
"AM"/"PM" peak (period), but e.g. "7 a.m.".