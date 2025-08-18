import argparse
import os
import tomllib
from pathlib import Path
from zipfile import ZipFile

import geopandas as gpd
import networkx as nx
import pandas as pd
from shapely import geometry
from shapely.geometry import LineString, Point

CRS_TOML = "crs.toml"
COUNTIES_BOUNDARIES_GIS_FILEPATH = "Q:/GIS/Boundaries/Counties/Counties.shp"
COUNTIES_BOUNDARIES_GIS_CRS = "EPSG:2227"


def read_gtfs_txt(gtfs_dir: Path | str, filename: str):
    gtfs_dir = Path(gtfs_dir)
    if gtfs_dir.suffix == ".zip":
        with ZipFile(gtfs_dir, "r") as z:
            return pd.read_csv(z.open(filename))
    else:
        return pd.read_csv(gtfs_dir / filename)


def read_stops(gtfs_dir, to_crs):
    stops_df = read_gtfs_txt(gtfs_dir, "stops.txt")
    stops_gdf = gpd.GeoDataFrame(
        stops_df,
        geometry=gpd.points_from_xy(stops_df.stop_lon, stops_df.stop_lat),
        crs="EPSG:4326",
    ).to_crs(to_crs)
    return stops_gdf


def read_shapes(gtfs_dir: Path | str, service_id: str | int):
    """
    read GTFS shapes and trips

    Parameters
    ----------
    gtfs_dir
        directory/zipfile containing the GTFS .txt files
    service_id
        unique identifier for service pattern over a set of dates when
        service is available for one or more routes, defined in calendar.txt
    """
    shapes = read_gtfs_txt(gtfs_dir, "shapes.txt")
    shp_ids = shapes.shape_id.unique()
    linestrs = []
    for shp_id in shp_ids:
        shp = shapes[shapes["shape_id"] == shp_id].sort_values(by="shape_pt_sequence")
        linestrs.append(LineString(zip(shp.shape_pt_lon, shp.shape_pt_lat)))
    shapes_gdf = gpd.GeoDataFrame(
        {"shape_id": shp_ids, "geometry": linestrs}, crs="EPSG:4326"
    )

    trips = read_gtfs_txt(gtfs_dir, "trips.txt")
    trips["service_id"] = trips["service_id"].astype(str)
    trips = trips[trips["service_id"] == str(service_id)]
    trips_shapes = shapes_gdf[shapes_gdf["shape_id"].isin(trips["shape_id"])]
    return trips, trips_shapes


def read_routes(gtfs_dir):
    return read_gtfs_txt(gtfs_dir, "routes.txt")


def read_stop_times(gtfs_dir):
    df = read_gtfs_txt(gtfs_dir, "stop_times.txt")
    # SFMTA sometimes has arrival/departure_time's that miss the leading 0
    # (i.e. H:MM:SS for before noon, rather than HH:MM:SS). This causes an
    # issue later when comparing timestamps directly as strs.
    # Zero pad these two columns:
    df["arrival_time"] = df["arrival_time"].str.zfill(8)  # left pad "0"
    df["departure_time"] = df["departure_time"].str.zfill(8)  # left pad "0"
    return df


def filter_trips_by_time(
    trips,
    stop_times,
    begin_time: str,
    end_time: str,
    arrival_time: bool = True,
):
    # TODO .ipynb uses departure time, whereas .py uses arrival time
    """
    trips occuring within the time period: start_time <= trip_time < end_time

    Parameters
    ----------
    begin_time
        format: hh:mm:ss
    end_time
        format: hh:mm:ss
    arrival_time
        filter using arrival_time if True, otherwise filter using departure_time
    """
    start_stops_idx = (
        stop_times.groupby(["trip_id"])["stop_sequence"].transform(min)
        == stop_times["stop_sequence"]
    )
    trips_hour = pd.merge(
        trips,
        stop_times[start_stops_idx][["trip_id", "arrival_time", "departure_time"]],
        on="trip_id",
        how="left",
    )

    if arrival_time:
        trips_in_period = trips_hour[
            (trips_hour["arrival_time"] >= begin_time)
            & (trips_hour["arrival_time"] < end_time)
        ]
    else:
        trips_in_period = trips_hour[
            (trips_hour["departure_time"] >= begin_time)
            & (trips_hour["departure_time"] < end_time)
        ]
    return trips_in_period


def frequent_routes(
    trips_in_period,
    trips_shapes,
    period_cols,
    trips_shapes_mcv,
    routes,
    min_trips,
    output_dir,
    outname,
    peak_period,
    output_tag,
):
    """TODO just grouping everything to do with frequent routes here first"""

    # check if routes meet the minimum period and hourly requirements
    route_period_counts = (
        trips_in_period.groupby(period_cols).trip_id.count().reset_index()
    )
    route_period_counts.columns = period_cols + ["total_trips"]
    route_frequent = route_period_counts[
        route_period_counts["total_trips"] >= min_trips
    ]

    # TODO the hourly stuff is ONLY in the .ipynb! Commented out for now
    # #hourly trips
    # route_hour = trips_in_period.groupby(['route_id', 'direction_id', 'departure_hour']).trip_id.count().reset_index()
    # route_hour.columns = ['route_id', 'direction_id', 'hour', 'trips']
    # route_hour_counts = route_hour[route_hour['trips']>=hour_threshold].groupby(period_cols).hour.count().reset_index()
    # route_hour_counts.columns = ['route_id', 'direction_id', 'hour_count']
    # num_hours = end_hour - begin_hour
    # route_frequent = pd.merge(route_frequent,
    #                           route_hour_counts[route_hour_counts['hour_count']==num_hours],
    #                           on=period_cols)

    if len(route_frequent):  # if len > 0
        route_frequent_shapes = route_frequent.merge(
            trips_shapes_mcv, on=period_cols, how="left"
        )
        route_frequent_shapes = trips_shapes.merge(route_frequent_shapes, on="shape_id")
        route_frequent_shapes = route_frequent_shapes.merge(
            routes, on="route_id", how="left"
        )
        route_frequent_shapes.to_file(
            os.path.join(
                output_dir,
                f"frequent_routes_{output_tag}_{outname}_{peak_period}.gpkg",
            )
        )
    else:
        print(f"No frequent routes found for {outname} {peak_period}")

    return route_frequent  # , route_period_counts


def frequent_stops(
    stops,
    stop_times,
    route_frequent,
    trips_in_period,
    peak_period,
    min_trips,
    output_dir,
    outname,
    output_tag,
):
    """TODO just grouping everything to do with frequent stops here first"""

    # TODO this is how the .ipynb calculated stop_frequent; commented out for now:
    # TODO verify that this does the same thing as the .py calculations below
    # stop_route_period = stop_times.merge(trips[['route_id', 'direction_id', 'trip_id']], on='trip_id', how='left')
    # stop_route_period = stop_route_period[(stop_route_period['departure_hour']>=begin_hour) & (stop_route_period['departure_hour']<end_hour)]

    # stop_period_counts = stop_route_period.groupby(['stop_id', 'route_id', 'direction_id']).trip_id.count().reset_index()
    # stop_period_counts.columns = ['stop_id', 'route_id', 'direction_id', 'total_trips']
    # stop_frequent = stop_period_counts[stop_period_counts['total_trips']>= min_trips]

    # stop_route_hour_count = stop_route_period.groupby(['stop_id', 'route_id', 'direction_id', 'departure_hour']).trip_id.count().reset_index()
    # stop_route_hour_count.columns = ['stop_id', 'route_id', 'direction_id', 'hour', 'trips']
    # stop_route_hour_count_frequent = stop_route_hour_count[stop_route_hour_count['trips']>=hour_threshold].groupby(['stop_id', 'route_id', 'direction_id']).hour.count().reset_index()
    # stop_route_hour_count_frequent.columns = ['stop_id', 'route_id', 'direction_id', 'hour_count']

    # stop_frequent = pd.merge(stop_frequent,
    #                       stop_route_hour_count_frequent[stop_route_hour_count_frequent['hour_count']==num_hours],
    #                       on=['route_id', 'direction_id','stop_id'])

    # TODO this is how the .py calculated stop_frequent:
    trips_in_period = route_frequent[["route_id", "direction_id"]].merge(
        trips_in_period, how="left"
    )
    stop_cols = ["stop_id", "route_id", "direction_id"]
    stop_route_period = stop_times.merge(
        trips_in_period[["route_id", "direction_id", "trip_id"]], on="trip_id"
    )

    stop_period_counts = (
        stop_route_period.groupby(stop_cols).trip_id.count().reset_index()
    )
    stop_period_counts.columns = stop_cols + ["total_trips"]
    stop_frequent = stop_period_counts[stop_period_counts["total_trips"] >= min_trips]

    if len(stop_frequent):  # if len > 0
        stop_frequent_list = stop_frequent.stop_id.unique().tolist()
        stop_frequent_gdf = stops[stops["stop_id"].isin(stop_frequent_list)]
        stop_frequent_gdf.to_file(
            os.path.join(
                output_dir,
                f"frequent_stops_{output_tag}_{outname}_{peak_period}.gpkg",
            )
        )
    else:
        print(f"No frequent stops found for {outname}, {peak_period}")
        stop_frequent_list = []
    return stop_frequent_list  # , stop_period_counts


def frequent_bus_routes(
    gtfs_dir,
    stops,
    service_id,
    peak_period,
    outname,
    min_trips,
    output_dir,
    output_tag,
    COMBINE_ROUTES,
):
    """

    Parameters
    ----------
    peak_period
        peak period being analyzed: "AM" or "PM"
    """
    if peak_period == "AM":
        begin_time = "07:00:00"
        end_time = "09:00:00"
    elif peak_period == "PM":
        begin_time = "16:30:00"
        end_time = "18:30:00"
    else:
        print("peak_period needs to be either AM or PM")

    routes = read_routes(gtfs_dir)
    trips, trips_shapes = read_shapes(gtfs_dir, service_id)
    stop_times = read_stop_times(gtfs_dir)

    for rec in COMBINE_ROUTES:
        route_ids = list(
            routes.loc[routes["route_short_name"].isin(rec[0]), "route_id"].values
        )
        if len(route_ids) > 0:
            new_id = route_ids[0]
            routes.loc[routes["route_short_name"].isin(rec[0]), "route_id"] = new_id
            routes.loc[routes["route_short_name"].isin(rec[0]), "route_short_name"] = (
                rec[1]
            )

            trips.loc[trips["route_id"].isin(route_ids), "route_id"] = new_id

    period_cols = ["route_id", "direction_id"]
    # There may be multiples shapes for the same route, so here the most frequent shape is used for each route_id
    trips_shapes_mcv = (
        trips.groupby(period_cols)["shape_id"]
        .agg(lambda x: x.value_counts().index[0])
        .reset_index()
    )

    # TODO .ipynb uses departure time, whereas .py uses arrival time (I think .py is the final script used it seems)
    trips_in_period = filter_trips_by_time(
        trips, stop_times, begin_time, end_time, arrival_time=True
    )

    route_frequent = frequent_routes(
        trips_in_period,
        trips_shapes,
        period_cols,
        trips_shapes_mcv,
        routes,
        min_trips,
        output_dir,
        outname,
        peak_period,
        output_tag,
    )
    stop_frequent_list = frequent_stops(
        stops,
        stop_times,
        route_frequent,
        trips_in_period,
        peak_period,
        min_trips,
        output_dir,
        outname,
        output_tag,
    )
    return stop_frequent_list  # , route_period_counts, stop_period_counts


def read_maz(maz_shapefile_filepath, to_crs):
    maz_gdf = gpd.read_file(maz_shapefile_filepath)
    maz_gdf = maz_gdf[maz_gdf["COUNTY"] == 1]  # filter for SF
    maz_gdf = maz_gdf.to_crs(to_crs)
    return maz_gdf


def read_sf_boundary(counties_boundaries_gis_filepath, crs):
    gdf = gpd.read_file(counties_boundaries_gis_filepath).set_crs(crs)
    return gdf[gdf["COUNTY"] == 1]


def read_street_network(streets_shapefile_filepath, to_crs):
    """
    historically the CHAMP hwy freeflow shapefile is used
    """
    streets_gdf = gpd.read_file(streets_shapefile_filepath)
    streets_gdf.insert(
        0, "LinkID", range(1, len(streets_gdf) + 1)
    )  # TODO just use the index of streets_gdf, no need to create another index column
    streets_gdf = streets_gdf.to_crs(to_crs)
    return streets_gdf


def endnotes_from_streets(streets_gdf):
    # TODO TMP wrapping everything to do with street end nodes in here

    def latlong(x):
        return (
            round(x.coords.xy[1][0], 6),
            round(x.coords.xy[0][0], 6),
            round(x.coords.xy[1][-1], 6),
            round(x.coords.xy[0][-1], 6),
        )

    (
        streets_gdf["B_Lat"],
        streets_gdf["B_Long"],
        streets_gdf["E_Lat"],
        streets_gdf["E_Long"],
    ) = zip(*streets_gdf["geometry"].map(latlong))

    b_nodes = streets_gdf[["B_Lat", "B_Long"]]
    b_nodes.columns = ["Lat", "Long"]
    e_nodes = streets_gdf[["E_Lat", "E_Long"]]
    e_nodes.columns = ["Lat", "Long"]

    streets_endnodes = pd.concat((b_nodes, e_nodes), ignore_index=True).reset_index()

    # Assign unique node id
    endnodes_cnt = streets_endnodes.groupby(["Lat", "Long"]).index.count().reset_index()
    endnodes_cnt.rename(columns={"index": "NodeCnt"}, inplace=True)
    endnodes_cnt["NodeID"] = endnodes_cnt.index + 1

    # TODO This is commented out in the .py but not commented out in the .ipynb
    # # Generate the the unique node shapefile
    # endnodes_cnt['geometry'] = list(zip(endnodes_cnt.Long, endnodes_cnt.Lat))
    # endnodes_cnt['geometry'] = endnodes_cnt['geometry'].apply(Point)
    # endnodes_unique_gpd = gpd.GeoDataFrame(endnodes_cnt, geometry='geometry')
    # endnodes_unique_gpd.crs = CRS
    # endnodes_unique_gpd.to_file(os.path.join(Streets_Dir, 'streets_endnodes.gpkg'))

    endnodes_cnt = endnodes_cnt[["Lat", "Long", "NodeCnt", "NodeID"]]
    endnodes_cnt.columns = ["B_Lat", "B_Long", "B_NodeCnt", "B_NodeID"]
    streets_gdf = streets_gdf.merge(endnodes_cnt, on=["B_Lat", "B_Long"], how="left")

    endnodes_cnt.columns = ["E_Lat", "E_Long", "E_NodeCnt", "E_NodeID"]
    streets_gdf = streets_gdf.merge(endnodes_cnt, on=["E_Lat", "E_Long"], how="left")
    endnodes_cnt.columns = ["Lat", "Long", "NodeCnt", "NodeID"]

    streets_gdf["length"] = streets_gdf.geometry.length
    streets_gdf["b_e"] = list(zip(streets_gdf["B_NodeID"], streets_gdf["E_NodeID"]))
    streets_gdf["e_b"] = list(zip(streets_gdf["E_NodeID"], streets_gdf["B_NodeID"]))
    # Save the updated street shapefile with endnodes
    # outcols = [c for c in streets.columns.tolist() if c not in ['b_e', 'e_b']]
    # streets[outcols].to_file(os.path.join(Streets_Dir, 'streets_with_endnodes.gpkg'))

    return streets_gdf, endnodes_cnt


def build_walking_network(stops, streets_gdf, sf_boundary_gdf, endnodes_cnt):
    stops_within_sf = stops.sjoin(sf_boundary_gdf, predicate="within").reset_index()
    stops_within_sf = stops_within_sf[stops.columns]
    stops_within_sf.insert(
        0,
        "NodeID",
        range(
            endnodes_cnt["NodeID"].max() + 1,
            endnodes_cnt["NodeID"].max() + 1 + len(stops_within_sf),
        ),
    )  # TODO no need to create a separate NodeID, just use the index itself

    search_radius = 300  # ft  # TODO unit depends on the CRS

    stops_geo = stops_within_sf.copy()
    stops_geo["point_geo"] = stops_geo["geometry"]
    stops_geo["geometry"] = stops_geo["geometry"].buffer(search_radius)
    stop_near_links = gpd.sjoin(
        streets_gdf[["LinkID", "B_NodeID", "E_NodeID", "length", "geometry"]],
        stops_geo,
        predicate="intersects",
    )

    def calc_dist(x):
        stop_point = x["point_geo"]
        link_geo = x["geometry"]
        x["near_dist"] = stop_point.distance(link_geo)
        x["stop_to_begin"] = link_geo.project(stop_point)
        x["stop_to_end"] = x["length"] - x["stop_to_begin"]
        return x

    stop_near_links = stop_near_links.apply(calc_dist, axis=1)
    stop_near_links = stop_near_links.sort_values(["stop_id", "near_dist"])
    stop_near_links = stop_near_links.drop_duplicates("stop_id")
    stop_near_links["near_link"] = stop_near_links["LinkID"]
    stop_near_links["near_link_bid"] = stop_near_links["B_NodeID"]
    stop_near_links["near_link_eid"] = stop_near_links["E_NodeID"]
    stop_near_links = stop_near_links.reset_index()

    # construct a network graph
    tgraph = nx.Graph()

    # road network nodes
    tgraph.add_nodes_from(endnodes_cnt.NodeID.tolist())

    # road network links
    for i in range(0, len(streets_gdf)):
        tgraph.add_edge(
            streets_gdf.loc[i, "B_NodeID"],
            streets_gdf.loc[i, "E_NodeID"],
            weight=streets_gdf.loc[i, "length"],
        )
    return stops_within_sf, stop_near_links, tgraph


def stop_walking_area(streets_gdf, walk_graph, walk_dis, start_node, link_near_stop):
    cur_path = dict(
        nx.single_source_dijkstra_path(
            walk_graph, start_node, cutoff=walk_dis, weight="weight"
        )
    )
    del cur_path[start_node]  # TODO definitely should not have del in production code
    reach_links = {}
    for key in cur_path:
        sub_path = list(zip(cur_path[key][:-1], cur_path[key][1:]))
        for each_link in sub_path:
            if each_link in reach_links:
                next
            else:
                reach_links[each_link] = 1
    reach_links_df = pd.DataFrame.from_dict(
        reach_links, orient="index", columns=["accessed"]
    ).reset_index()
    reach_links_df.rename(columns={"index": "b_e"}, inplace=True)
    streets_access = streets_gdf[
        (streets_gdf["b_e"].isin(reach_links_df["b_e"]))
        | (streets_gdf["e_b"].isin(reach_links_df["b_e"]))
        | (streets_gdf["LinkID"] == link_near_stop)
    ]
    geom = [x for x in streets_access.geometry]
    multi_line = geometry.MultiLineString(geom)
    multi_line_polygon = multi_line.convex_hull
    if multi_line_polygon.geom_type != "Polygon":
        multi_line_polygon = multi_line_polygon.envelope
    return multi_line_polygon


def frequent_access_area(
    streets_gdf,
    walk_graph,
    stop_ids,
    stop_with_nearest_link,
    buffer_radius,
    crs,
):
    """Accessible area from high frequent stops"""
    geometrys = []
    for stop_id in stop_ids:
        lidx = stop_with_nearest_link.index[
            stop_with_nearest_link["stop_id"] == stop_id
        ][0]
        cur_node_id = stop_with_nearest_link.loc[lidx, "NodeID"]
        cur_link = stop_with_nearest_link.loc[lidx, "near_link"]

        cur_graph = walk_graph.copy()
        cur_graph.add_node(cur_node_id)
        cur_graph.add_edge(
            stop_with_nearest_link.loc[lidx, "near_link_bid"],
            stop_with_nearest_link.loc[lidx, "NodeID"],
            weight=stop_with_nearest_link.loc[lidx, "stop_to_begin"],
        )
        cur_graph.add_edge(
            stop_with_nearest_link.loc[lidx, "NodeID"],
            stop_with_nearest_link.loc[lidx, "near_link_eid"],
            weight=stop_with_nearest_link.loc[lidx, "stop_to_end"],
        )

        geometrys.append(
            stop_walking_area(
                streets_gdf, cur_graph, buffer_radius, cur_node_id, cur_link
            )
        )
    stop_access_gdf = gpd.GeoDataFrame(
        {"stop_id": stop_ids, "geometry": geometrys}, crs=crs
    )
    return stop_access_gdf


def frequent_stops_access_geo(
    maz_gdf,
    geo_data,
    frequent_stops_access_union,
    crs,
    min_intersect_area_prop,
):
    frequent_stops_access_geo = gpd.overlay(
        maz_gdf,
        gpd.GeoDataFrame({"geometry": [frequent_stops_access_union]}, crs=crs),
    )
    frequent_stops_access_geo["area_prop"] = (
        frequent_stops_access_geo.geometry.area
        / frequent_stops_access_geo["Shape_Area"]
    )
    frequent_stops_access_geo = frequent_stops_access_geo[
        frequent_stops_access_geo["area_prop"] >= min_intersect_area_prop
    ]
    geo_ids = frequent_stops_access_geo["MAZID"].unique()
    frequent_stops_access_data = geo_data[geo_data["MAZID"].isin(geo_ids)]
    # df_access_geo = gpd.GeoDataFrame(
    #     {"geometry": [frequent_stops_access_geo.geometry.unary_union]},
    #     crs=CRS,
    # )
    return frequent_stops_access_data, geo_ids


def read_maz_attrs(maz_gdf, maz_datafile_filepath):
    # Just report the percentages, do not report the actual population/
    # employment numbers, since the MAZ demographics is often more outdated. If
    # reporting of actual numbers is desired, scale with more updated numbers
    # from ACS (population) and CA EDD CES (employment).
    geo_data = pd.read_csv(maz_datafile_filepath, sep=" ")
    geo_data = geo_data[geo_data["taz_p"] < 1000]
    geo_data = geo_data[["parcelid", "hh_p", "emptot_p"]]
    geo_data["pop_p"] = geo_data["hh_p"] / geo_data["hh_p"].sum()
    geo_data["emptot_p"] = geo_data["emptot_p"] / geo_data["emptot_p"].sum()
    maz_gdf["MAZID"] = maz_gdf["MAZID"].astype("int64")
    geo_data["parcelid"] = geo_data["parcelid"].astype("int64")
    geo_data = maz_gdf[["MAZID", "geometry"]].merge(
        geo_data, left_on="MAZID", right_on="parcelid"
    )
    return geo_data


def calculate_coverage(
    maz_gdf,
    geo_data,
    streets_gdf,
    endnodes_cnt,
    gtfs_dir,
    gtfs_service_id,
    gtfs_year,
    min_trips,
    output_dir,
    output_tag,
    COMBINE_ROUTES,
    buffer_radius,
    min_intersect_area_prop,
    crs,
):
    stops = read_stops(gtfs_dir, crs)
    sf_boundary_gdf = read_sf_boundary(
        COUNTIES_BOUNDARIES_GIS_FILEPATH, COUNTIES_BOUNDARIES_GIS_CRS
    )
    coverage_df = pd.DataFrame()
    idx = 0
    stops_within_sf, stop_near_links, tgraph = build_walking_network(
        stops, streets_gdf, sf_boundary_gdf, endnodes_cnt
    )
    for peak_period in ["AM", "PM"]:
        coverage_df.loc[idx, "year"] = int(gtfs_year)
        coverage_df.loc[idx, "period"] = peak_period

        stop_frequent_list = frequent_bus_routes(
            gtfs_dir,
            stops,
            gtfs_service_id,
            peak_period,
            gtfs_year,
            min_trips,
            output_dir,
            output_tag,
            COMBINE_ROUTES,
        )
        stop_frequent_list_with_sf = [
            stopid
            for stopid in stop_frequent_list
            if stopid in stops_within_sf["stop_id"].tolist()
        ]
        if len(stop_frequent_list_with_sf) > 0:
            frequent_stops_access_area = frequent_access_area(
                streets_gdf,
                tgraph,
                stop_frequent_list_with_sf,
                stop_near_links,
                buffer_radius,
                crs,
            )
            frequent_stops_access_area.to_crs(epsg=4326).to_file(
                os.path.join(
                    output_dir,
                    f"frequent_stops_{output_tag}_{gtfs_year}_{peak_period}buffer.gpkg",
                )
            )
            frequent_stops_access_union = (
                frequent_stops_access_area.geometry.unary_union
            )
            frequent_access_geo_attrs, geo_ids = frequent_stops_access_geo(
                maz_gdf,
                geo_data,
                frequent_stops_access_union,
                crs,
                min_intersect_area_prop,
            )
            maz_gdf.loc[maz_gdf["MAZID"].isin(geo_ids), ["MAZID", "geometry"]].to_crs(
                "EPSG:4326"
            ).to_file(
                os.path.join(
                    output_dir,
                    f"coverage_{output_tag}_{gtfs_year}_{peak_period}buffer.gpkg",
                )
            )

            coverage_df.loc[idx, "cover_pop"] = frequent_access_geo_attrs["pop_p"].sum()
            coverage_df.loc[idx, "cover_jobs"] = frequent_access_geo_attrs[
                "emptot_p"
            ].sum()
        else:
            coverage_df.loc[idx, "cover_pop"] = 0
            coverage_df.loc[idx, "cover_jobs"] = 0
        coverage_df.loc[idx, "tot_pop"] = geo_data["pop_p"].sum()
        coverage_df.loc[idx, "tot_jobs"] = geo_data["emptot_p"].sum()
        coverage_df.loc[idx, "cover_pop_pct"] = round(
            100 * coverage_df.loc[idx, "cover_pop"] / coverage_df.loc[idx, "tot_pop"],
            2,
        )
        coverage_df.loc[idx, "cover_jobs_pct"] = round(
            100 * coverage_df.loc[idx, "cover_jobs"] / coverage_df.loc[idx, "tot_jobs"],
            2,
        )
        idx += 1
    return coverage_df


def transit_coverage(config):
    # TODO use SF instead? Though SFCTA generally uses CA3_ft.
    with open(CRS_TOML, "rb") as f:
        crs = tomllib.load(f)["CA3_ft"]

    # GTFS directories, service ids, and years
    gtfs_dir = Path(config["GTFS"]["DIR"])
    gtfs_service_id = config["GTFS"]["SERVICE_ID"]
    gtfs_year = config["GTFS"]["YEAR"]

    # Output directory
    output_dir = config["OUTPUT"]["DIR"]
    output_tag = config["OUTPUT"]["TAG"]

    # All Streets
    streets_shapefile_filepath = config["STREETS"]["SHAPEFILE"]

    # MAZ data
    maz_shapefile_filepath = config["ZONES"]["SHAPEFILE"]
    maz_datafile_filepath = config["ZONES"]["DATAFILE"]

    # define parameters needed by the calculation
    min_trips = int(config["PARAMS"]["MIN_TRIPS"])
    buffer_radius = (
        float(config["PARAMS"]["BUFFER_RAD_MI"]) * 5280
    )  # a quarter mile walking distance
    min_intersect_area_prop = float(config["PARAMS"]["MIN_INTERSECT_AREA"])

    COMBINE_ROUTES = [
        [["5", "5R"], "5+5R"],
        [["9", "9R"], "9+9R"],
        [["14", "14R"], "14+14R"],
        [["38", "38R"], "38+38R"],
        [["47", "49"], "47+49"],
        [
            ["KT", "M"],
            "KT+M",
        ],  # TODO these will need to be separated post-Central Subway
    ]

    os.makedirs(output_dir, exist_ok=True)

    maz_gdf = read_maz(maz_shapefile_filepath, crs)
    geo_data = read_maz_attrs(maz_gdf, maz_datafile_filepath)
    streets_gdf = read_street_network(streets_shapefile_filepath, crs)
    streets_gdf, endnodes_cnt = endnotes_from_streets(streets_gdf)
    coverage_df = calculate_coverage(
        maz_gdf,
        geo_data,
        streets_gdf,
        endnodes_cnt,
        gtfs_dir,
        gtfs_service_id,
        gtfs_year,
        min_trips,
        output_dir,
        output_tag,
        COMBINE_ROUTES,
        buffer_radius,
        min_intersect_area_prop,
        crs,
    )
    # Just report the percentages, do not report the actual population/
    # employment numbers, since the MAZ demographics is often more outdated. If
    # reporting of actual numbers is desired, scale with more updated numbers
    # from ACS (population) and CA EDD CES (employment).
    coverage_df.to_csv(
        Path(output_dir) / f"cmp_transit_coverage_metrics_{gtfs_year}.csv",
        index=False,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Calculate transit coverage.")
    parser.add_argument("config_filepath", help="config .toml filepath")
    args = parser.parse_args()
    with open(args.config_filepath, "rb") as f:
        transit_coverage(tomllib.load(f))
