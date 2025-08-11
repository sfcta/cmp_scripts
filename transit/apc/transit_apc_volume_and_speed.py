import argparse
import math
import os
import tomllib
from itertools import product
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import polars as pl


def create_stop_ids_time_periods_df(stop_ids):
    """Create empty dataframe with continuous time periods for each stop ID

    to be merged with the actual volumes later"""
    daytype = ["Weekdays", "Saturday", "Sunday"]
    hour = range(24)
    minute = ["00", "30"]
    # epoch: repeat len(daytype) * len(stop_ids) times
    epoch = list(range(48)) * len(daytype) * len(stop_ids)
    df = pd.DataFrame(
        product(stop_ids, daytype, hour, minute),
        columns=["stopid", "daytype", "hour", "minute"],
    )
    df["epoch"] = epoch
    df["period"] = df["hour"].astype(str) + ":" + df["minute"]
    return df


def calculate_boardings_alightings_loads(apc_notnull, stops):
    """Calculate transit boardings, alightings, and loads"""
    vol_sum = (
        apc_notnull.groupby(["BS_ID", "Date", "Epoch"])
        .agg(
            {
                "ONS": "sum",
                "OFFS": "sum",
                "MAX_LOAD": "sum",
                "Close_Time": "count",
            }
        )
        .reset_index()
    )
    vol_sum.columns = [
        "stopid",
        "date",
        "epoch",
        "boardings",
        "alightings",
        "loads",
        "samples",
    ]

    vol_sum["date"] = pd.to_datetime(vol_sum["date"])
    vol_sum["dow"] = vol_sum.date.dt.dayofweek  # Mon-0
    vol_sum["daytype"] = np.where(
        vol_sum["dow"] <= 4,
        "Weekdays",
        np.where(vol_sum["dow"] == 5, "Saturday", "Sunday"),
    )

    # Remove Mondays and Fridays to get typical weekdays
    vol_sum = vol_sum[(vol_sum["dow"] != 0) & (vol_sum["dow"] != 4)]

    vol_daytype_avg_stops = (
        vol_sum.groupby(["stopid", "daytype", "epoch"])
        .agg({"boardings": "mean", "alightings": "mean", "loads": "mean"})
        .reset_index()
    )
    vol_daytype_avg_stops.columns = [
        "stopid",
        "daytype",
        "epoch",
        "boardings",
        "alightings",
        "loads",
    ]

    stops_time_periods_complete_df = create_stop_ids_time_periods_df(
        stops.stop_id.unique()
    )

    stop_vol_complete = pd.merge(
        stops_time_periods_complete_df,
        vol_daytype_avg_stops,
        on=["stopid", "daytype", "epoch"],
        how="left",
    )

    # Save volume output file
    return stop_vol_complete


def update_apc_stopid(apc_df, year):
    """Update the APC DataFrame to use the new (post-2023) stop IDs

    For 2023/04-05 APC data, the APC stop IDs were still using the old
    (pre-2022) stop IDs (< 10000), whereas the GTFS data were already using the
    new stop IDs (> 10000).
    BS_ID is the column name for stop IDs
    """
    if year > 2022:
        return apc_df.with_columns(
            pl.when(pl.col("BS_ID") < 10000)  # if old (pre-2022) stop ID
            .then(pl.col("BS_ID") + 10000)  # then convert to new stop ID
            .otherwise(pl.col("BS_ID"))  # else leave as is
        )
    else:
        return apc_df


def match_intermediate_apc_stops(
    apc_pairs,
    apc_cmp,
    overlap_pairs,
    cmp_segments_gdf,
    timep,
    year,
    output_dir: Path,  # for saving AM/PM APC trip speeds CSVs
):
    """Transit Speeds on CMP Segment"""
    # ### Auto Matched Pairs
    apc_pairs["cmp_segid"] = apc_pairs["cmp_segid"].astype(int)
    apc_pairs["cur_stop_id"] = apc_pairs["cur_stop_id"].astype(int)
    apc_pairs["next_stop_id"] = apc_pairs["next_stop_id"].astype(int)

    # ### Manually Matched Pairs
    pair_cnt = len(apc_pairs)
    for cur_stop_idx in range(len(overlap_pairs)):
        cur_stopid = overlap_pairs.loc[cur_stop_idx, "pre_stopid"]
        next_stopid = overlap_pairs.loc[cur_stop_idx, "next_stopid"]
        cur_stop_trips = apc_cmp.index[apc_cmp["BS_ID"] == cur_stopid].tolist()
        for cur_stop_trip_idx in cur_stop_trips:
            if apc_cmp.loc[cur_stop_trip_idx + 1, "BS_ID"] == next_stopid:
                cur_stop_trip_id = apc_cmp.loc[cur_stop_trip_idx, "TRIP_ID_EXTERNAL"]
                cur_stop_date = apc_cmp.loc[cur_stop_trip_idx, "Date"]
                cur_stop_veh_id = apc_cmp.loc[cur_stop_trip_idx, "VEHICLE_ID"]
                cur_stop_route_alpha = apc_cmp.loc[cur_stop_trip_idx, "ROUTE_ALPHA"]
                cur_stop_route_dir = apc_cmp.loc[cur_stop_trip_idx, "DIRECTION"]
                cur_stop_open_time = apc_cmp.loc[cur_stop_trip_idx, "Open_Time"]
                cur_stop_close_time = apc_cmp.loc[cur_stop_trip_idx, "Close_Time"]
                cur_stop_dwell_time = apc_cmp.loc[cur_stop_trip_idx, "DWELL_TIME"]

                next_stop_trip_id = apc_cmp.loc[
                    cur_stop_trip_idx + 1, "TRIP_ID_EXTERNAL"
                ]
                next_stop_date = apc_cmp.loc[cur_stop_trip_idx + 1, "Date"]
                next_stop_veh_id = apc_cmp.loc[cur_stop_trip_idx + 1, "VEHICLE_ID"]
                next_stop_open_time = apc_cmp.loc[cur_stop_trip_idx + 1, "Open_Time"]
                next_stop_close_time = apc_cmp.loc[cur_stop_trip_idx + 1, "Close_Time"]
                next_stop_dwell_time = apc_cmp.loc[cur_stop_trip_idx + 1, "DWELL_TIME"]

                # Check if two stops share the same trip id, date, and vehicle id
                if (
                    (cur_stop_trip_id == next_stop_trip_id)
                    & (cur_stop_date == next_stop_date)
                    & (cur_stop_veh_id == next_stop_veh_id)
                ):
                    cur_next_traveltime = (
                        next_stop_open_time - cur_stop_open_time
                    ).total_seconds()
                    cur_next_loc_dis = (
                        overlap_pairs.loc[cur_stop_idx, "cmp_overlap_len"]
                        / 5280
                        / overlap_pairs.loc[cur_stop_idx, "cmp_overlap_ratio"]
                    )

                    # Remove records deemed erroneous according to memo from last cycle
                    if (cur_next_loc_dis > 0) & (cur_next_traveltime > 0):
                        if 3600 * cur_next_loc_dis / cur_next_traveltime <= 55:
                            # Add matched stop pairs to the dataframe for subsequent speed calculation
                            apc_pairs.loc[pair_cnt, "cmp_segid"] = overlap_pairs.loc[
                                cur_stop_idx, "cmp_segid"
                            ]
                            apc_pairs.loc[pair_cnt, "trip_id"] = cur_stop_trip_id
                            apc_pairs.loc[pair_cnt, "trip_date"] = cur_stop_date
                            apc_pairs.loc[pair_cnt, "vehicle_id"] = cur_stop_veh_id
                            apc_pairs.loc[pair_cnt, "route_alpha"] = (
                                cur_stop_route_alpha
                            )
                            apc_pairs.loc[pair_cnt, "direction"] = cur_stop_route_dir

                            apc_pairs.loc[pair_cnt, "cur_stop_id"] = cur_stopid
                            apc_pairs.loc[pair_cnt, "cur_stop_open_time"] = (
                                cur_stop_open_time
                            )
                            apc_pairs.loc[pair_cnt, "cur_stop_close_time"] = (
                                cur_stop_close_time
                            )
                            apc_pairs.loc[pair_cnt, "cur_stop_dwell_time"] = (
                                cur_stop_dwell_time
                            )

                            apc_pairs.loc[pair_cnt, "next_stop_id"] = next_stopid
                            apc_pairs.loc[pair_cnt, "next_stop_open_time"] = (
                                next_stop_open_time
                            )
                            apc_pairs.loc[pair_cnt, "next_stop_close_time"] = (
                                next_stop_close_time
                            )
                            apc_pairs.loc[pair_cnt, "next_stop_dwell_time"] = (
                                next_stop_dwell_time
                            )

                            apc_pairs.loc[pair_cnt, "cur_next_time"] = (
                                cur_next_traveltime
                            )
                            apc_pairs.loc[pair_cnt, "cur_next_loc_dis"] = (
                                cur_next_loc_dis
                            )
                            apc_pairs.loc[pair_cnt, "cur_next_rev_dis"] = apc_cmp.loc[
                                cur_stop_trip_idx, "REV_DISTANCE"
                            ]

                        pair_cnt = pair_cnt + 1

    apc_pairs["cur_next_loc_dis"] = np.where(
        apc_pairs["cur_next_loc_dis"] >= apc_pairs["cur_next_rev_dis"],
        apc_pairs["cur_next_loc_dis"],
        apc_pairs["cur_next_rev_dis"],
    )

    # I-80 (Bay Bridge) between Fremont Exit and Treasure ISland
    cmp_segments_baybridge = [237, 245]

    # get a clean apc_pairs, then calculate trip speeds
    apc_trip_speeds = (
        pl.from_pandas(
            apc_pairs[
                (apc_pairs["cur_stop_dwell_time"] < 180)
                | (apc_pairs["cmp_segid"].isin(cmp_segments_baybridge))
            ]
        )
        .with_columns(
            # remove leading 0's
            pl.col("route_alpha").str.strip_chars_start("0")
        )
        .with_columns(
            # TODO We probably shouldn't merge route_alpha and direction into
            #      route_dir if there's no particular reason to?
            pl.concat_str(
                (pl.col("route_alpha"), pl.col("direction")), separator="_"
            ).alias("route_dir"),
        )
        # apc_pairs cleaned, now get trip speeds
        .group_by(["cmp_segid", "trip_id", "trip_date", "route_dir"])
        .agg(
            pl.sum("cur_next_loc_dis").alias("trip_stop_distance"),
            pl.sum("cur_next_time").alias("trip_traveltime"),
        )
        .with_columns(
            (3600 * pl.col("trip_stop_distance") / pl.col("trip_traveltime")).alias(
                "trip_loc_speed"
            )
        )
    ).to_pandas()

    apc_trip_speeds = pd.merge(
        apc_trip_speeds,
        cmp_segments_gdf[["cmp_segid", "length"]],
        on="cmp_segid",
        how="left",
    )
    apc_trip_speeds["len_ratio"] = (
        100 * apc_trip_speeds["trip_stop_distance"] / apc_trip_speeds["length"]
    )

    apc_trip_speeds.to_csv(
        output_dir / f"CMP{year}_APC_Matched_Trips_{timep}.csv", index=False
    )

    # Only include trips covering at least 50% of CMP length
    apc_trip_speeds_over50 = apc_trip_speeds[apc_trip_speeds["len_ratio"] >= 50]
    apc_cmp_speeds = (
        apc_trip_speeds_over50.groupby(["cmp_segid"])
        .agg({"trip_loc_speed": ["mean", "std"], "trip_id": "count"})
        .reset_index()
    )

    apc_cmp_speeds.columns = [
        "cmp_segid",
        "avg_speed",
        "std_dev",
        "sample_size",
    ]
    apc_cmp_speeds["cov"] = (
        100 * apc_cmp_speeds["std_dev"] / apc_cmp_speeds["avg_speed"]
    )

    apc_cmp_speeds["year"] = year
    apc_cmp_speeds["source"] = "APC"
    apc_cmp_speeds["period"] = timep

    apc_cmp_speeds_routes = (
        apc_trip_speeds_over50.groupby(["cmp_segid"])["route_dir"]
        .agg(["unique"])
        .reset_index()
    )
    apc_cmp_speeds_routes.columns = ["cmp_segid", "comment"]
    apc_cmp_speeds = apc_cmp_speeds.merge(
        apc_cmp_speeds_routes, on="cmp_segid", how="left"
    )

    return apc_cmp_speeds


def match_stop_pairs_to_cmp(
    apc_cmp_df,
    stops_near_cmp_list,
    cmp_segs_near,
    cmp_segments_gdf,
    angle_thrd,
):
    apc_pairs_columns = [
        "cmp_segid",
        "trip_id",
        "trip_date",
        "vehicle_id",
        "route_alpha",
        "direction",
        "cur_stop_id",
        "cur_stop_open_time",
        "cur_stop_close_time",
        "cur_stop_dwell_time",
        "cur_stop_loc",
        "next_stop_id",
        "next_stop_open_time",
        "next_stop_close_time",
        "next_stop_dwell_time",
        "next_stop_loc",
        "cur_next_time",
        "cur_next_loc_dis",
        "cur_next_rev_dis",
    ]
    # TODO eventually use apc_pairs_schema.keys() as apc_pairs_columns
    # and give the schema when creating apc_pairs (if apc_pairs need to be
    # constructed from a dict rather than directly from apc_cmp_df)
    # apc_pairs_schema = {"route_alpha": pl.Utf8}
    apc_pairs_dict = {key: [] for key in apc_pairs_columns}
    # Enumerate the records in apc_cmp_df
    # TODO we should not be looping through the elements one by one
    for cur_stop_idx in range(len(apc_cmp_df) - 2):
        # Check if the stop_id is in the previously matched list
        if apc_cmp_df.loc[cur_stop_idx, "stop_id"] in stops_near_cmp_list:
            next_stop_match = 0
            if apc_cmp_df.loc[cur_stop_idx + 1, "stop_id"] in stops_near_cmp_list:
                next_stop_idx = cur_stop_idx + 1
                next_stop_match = 1
            # This is to ensure the stop_id associated with cur_stop_idx + 2 is also checked when the stop_id associated with cur_stop_idx + 1 is not found in the matched list
            elif apc_cmp_df.loc[cur_stop_idx + 2, "stop_id"] in stops_near_cmp_list:
                next_stop_idx = cur_stop_idx + 2
                next_stop_match = 2

            if next_stop_match > 0:
                # Transit stop of interest
                cur_stop_trip_id = apc_cmp_df.loc[cur_stop_idx, "TRIP_ID_EXTERNAL"]
                cur_stop_date = apc_cmp_df.loc[cur_stop_idx, "Date"]
                cur_stop_veh_id = apc_cmp_df.loc[cur_stop_idx, "VEHICLE_ID"]
                cur_stop_route_alpha = apc_cmp_df.loc[cur_stop_idx, "ROUTE_ALPHA"]
                cur_stop_route_dir = apc_cmp_df.loc[cur_stop_idx, "DIRECTION"]

                # Succeeding candidate stop in the dataframe
                next_stop_trip_id = apc_cmp_df.loc[next_stop_idx, "TRIP_ID_EXTERNAL"]
                next_stop_date = apc_cmp_df.loc[next_stop_idx, "Date"]
                next_stop_veh_id = apc_cmp_df.loc[next_stop_idx, "VEHICLE_ID"]

                # Check if two stops share the same trip id, date, and vehicle id
                if (
                    (cur_stop_trip_id == next_stop_trip_id)
                    & (cur_stop_date == next_stop_date)
                    & (cur_stop_veh_id == next_stop_veh_id)
                ):
                    cur_stop_id = apc_cmp_df.loc[cur_stop_idx, "stop_id"]
                    cur_stop_open_time = apc_cmp_df.loc[cur_stop_idx, "Open_Time"]
                    cur_stop_close_time = apc_cmp_df.loc[cur_stop_idx, "Close_Time"]
                    cur_stop_dwell_time = apc_cmp_df.loc[cur_stop_idx, "DWELL_TIME"]

                    next_stop_id = apc_cmp_df.loc[next_stop_idx, "stop_id"]
                    next_stop_open_time = apc_cmp_df.loc[next_stop_idx, "Open_Time"]
                    next_stop_close_time = apc_cmp_df.loc[next_stop_idx, "Close_Time"]
                    next_stop_dwell_time = apc_cmp_df.loc[next_stop_idx, "DWELL_TIME"]

                    # Matched CMP segments for the current stop
                    cur_stop_near_segs = list(
                        cmp_segs_near[cmp_segs_near["stop_id"] == cur_stop_id][
                            "cmp_segid"
                        ]
                    )
                    # Matched CMP segments for the succeeding stop
                    next_stop_near_segs = list(
                        cmp_segs_near[cmp_segs_near["stop_id"] == next_stop_id][
                            "cmp_segid"
                        ]
                    )

                    # Find the common CMP segments in two sets
                    common_segs = list(
                        set(cur_stop_near_segs) & set(next_stop_near_segs)
                    )

                    if len(common_segs) > 0:
                        cur_stop_geo = apc_cmp_df.loc[cur_stop_idx][
                            "geometry"
                        ]  # location geometry of current stop
                        next_stop_geo = apc_cmp_df.loc[next_stop_idx][
                            "geometry"
                        ]  # location geometry of succeeding stop

                        # Traveling direction from current stop to succeeding stop
                        stop_degree = (180 / math.pi) * math.atan2(
                            next_stop_geo.x - cur_stop_geo.x,
                            next_stop_geo.y - cur_stop_geo.y,
                        )

                        # Iterate through the common segments set
                        for common_seg_id in common_segs:
                            # line geometry of the cmp segment
                            common_seg_geo = cmp_segments_gdf.set_index(
                                "cmp_segid", inplace=False
                            ).loc[common_seg_id, "geometry"]

                            # distance between the beginning point of cmp segment and the projected transit stop
                            cur_stop_dis = common_seg_geo.project(cur_stop_geo)
                            # project current stop onto cmp segment
                            cur_stop_projected = common_seg_geo.interpolate(
                                cur_stop_dis
                            )
                            # meters to feet
                            cur_stop_loc = cur_stop_dis * 3.2808

                            next_stop_dis = common_seg_geo.project(next_stop_geo)
                            # project next stop onto cmp segment
                            next_stop_projected = common_seg_geo.interpolate(
                                next_stop_dis
                            )
                            # meters to feet
                            next_stop_loc = next_stop_dis * 3.2808

                            # Ensure the degree is calculated following the traveling direction
                            if float(next_stop_loc) > float(cur_stop_loc):
                                cmp_degree = (180 / math.pi) * math.atan2(
                                    next_stop_projected.x - cur_stop_projected.x,
                                    next_stop_projected.y - cur_stop_projected.y,
                                )
                            else:
                                cmp_degree = (180 / math.pi) * math.atan2(
                                    cur_stop_projected.x - next_stop_projected.x,
                                    cur_stop_projected.y - next_stop_projected.y,
                                )

                            stop_cmp_angle = abs(cmp_degree - stop_degree)
                            if stop_cmp_angle > 270:
                                stop_cmp_angle = 360 - stop_cmp_angle

                            if (
                                stop_cmp_angle < angle_thrd
                            ):  # Angle between CMP segment and transit stop pair meets the requirement
                                cur_next_traveltime = (
                                    next_stop_open_time - cur_stop_open_time
                                ).total_seconds()
                                cur_next_loc_dis = (
                                    abs(float(next_stop_loc) - float(cur_stop_loc))
                                    / 5280
                                )  # feet to miles

                                # Remove records deemed erroneous according to memo from last cycle
                                if (cur_next_loc_dis > 0) & (cur_next_traveltime > 0):
                                    if (
                                        3600 * cur_next_loc_dis / cur_next_traveltime
                                        <= 55
                                    ):
                                        # Add matched stop pairs to the new dataframe for subsequent speed calculation
                                        apc_pairs_dict["cmp_segid"].append(
                                            common_seg_id
                                        )
                                        apc_pairs_dict["trip_id"].append(
                                            cur_stop_trip_id
                                        )
                                        apc_pairs_dict["trip_date"].append(
                                            cur_stop_date
                                        )
                                        apc_pairs_dict["vehicle_id"].append(
                                            cur_stop_veh_id
                                        )
                                        apc_pairs_dict["route_alpha"].append(
                                            cur_stop_route_alpha
                                        )
                                        apc_pairs_dict["direction"].append(
                                            cur_stop_route_dir
                                        )

                                        apc_pairs_dict["cur_stop_id"].append(
                                            cur_stop_id
                                        )
                                        apc_pairs_dict["cur_stop_open_time"].append(
                                            cur_stop_open_time
                                        )
                                        apc_pairs_dict["cur_stop_close_time"].append(
                                            cur_stop_close_time
                                        )
                                        apc_pairs_dict["cur_stop_dwell_time"].append(
                                            cur_stop_dwell_time
                                        )
                                        apc_pairs_dict["cur_stop_loc"].append(
                                            float(cur_stop_loc)
                                        )

                                        apc_pairs_dict["next_stop_id"].append(
                                            next_stop_id
                                        )
                                        apc_pairs_dict["next_stop_open_time"].append(
                                            next_stop_open_time
                                        )
                                        apc_pairs_dict["next_stop_close_time"].append(
                                            next_stop_close_time
                                        )
                                        apc_pairs_dict["next_stop_dwell_time"].append(
                                            next_stop_dwell_time
                                        )
                                        apc_pairs_dict["next_stop_loc"].append(
                                            float(next_stop_loc)
                                        )

                                        apc_pairs_dict["cur_next_time"].append(
                                            cur_next_traveltime
                                        )
                                        apc_pairs_dict["cur_next_loc_dis"].append(
                                            cur_next_loc_dis
                                        )
                                        if next_stop_match == 1:
                                            apc_pairs_dict["cur_next_rev_dis"].append(
                                                apc_cmp_df.loc[
                                                    cur_stop_idx,
                                                    "REV_DISTANCE",
                                                ]
                                            )
                                        else:
                                            apc_pairs_dict["cur_next_rev_dis"].append(
                                                apc_cmp_df.loc[
                                                    cur_stop_idx,
                                                    "REV_DISTANCE",
                                                ]
                                                + apc_cmp_df.loc[
                                                    cur_stop_idx + 1,
                                                    "REV_DISTANCE",
                                                ]
                                            )

        if cur_stop_idx % 50000 == 0:
            print(
                "Processed %s percent" % round(100 * cur_stop_idx / len(apc_cmp_df), 2)
            )

    apc_pairs_df = pd.DataFrame.from_dict(apc_pairs_dict)

    # Update the stop location for CMP 175 due to its irregular geometry
    # stop IDs are renumbered (+10000) between 2022/2023
    apc_pairs_df["cur_stop_loc"] = np.where(
        apc_pairs_df["cmp_segid"] == 175,
        np.where(
            apc_pairs_df["cur_stop_id"].isin({5543, 15543}),
            173.935,
            np.where(
                apc_pairs_df["cur_stop_id"].isin({5545, 15545}),
                1020.629,
                np.where(
                    apc_pairs_df["cur_stop_id"].isin({5836, 15836}),
                    1804.72,
                    np.where(
                        apc_pairs_df["cur_stop_id"].isin({5835, 15835}),
                        2685.807,
                        apc_pairs_df["cur_stop_loc"],
                    ),
                ),
            ),
        ),
        apc_pairs_df["cur_stop_loc"],
    )
    apc_pairs_df["next_stop_loc"] = np.where(
        apc_pairs_df["cmp_segid"] == 175,
        np.where(
            apc_pairs_df["next_stop_id"].isin({5543, 15543}),
            173.935,
            np.where(
                apc_pairs_df["next_stop_id"].isin({5545, 15545}),
                1020.629,
                np.where(
                    apc_pairs_df["next_stop_id"].isin({5836, 15836}),
                    1804.72,
                    np.where(
                        apc_pairs_df["next_stop_id"].isin({5835, 15835}),
                        2685.807,
                        apc_pairs_df["next_stop_loc"],
                    ),
                ),
            ),
        ),
        apc_pairs_df["next_stop_loc"],
    )
    apc_pairs_df["cur_next_loc_dis"] = np.where(
        apc_pairs_df["cmp_segid"] == 175,
        abs(apc_pairs_df["next_stop_loc"] - apc_pairs_df["cur_stop_loc"]) / 5280,
        apc_pairs_df["cur_next_loc_dis"],
    )
    return apc_pairs_df


def calculate_transit_speed_and_reliability(
    cmp_segments_gdf,
    inrix_network_gdf,
    cmp_inrix_correspondence,
    apc_notnull,
    stops,
    overlap_pairs,
    year,
    output_dir,
):
    """Calculate transit speed and reliability"""
    # Define WGS 1984 coordinate system
    wgs84 = {
        "proj": "longlat",
        "ellps": "WGS84",
        "datum": "WGS84",
        "no_defs": True,
    }
    # Define NAD 1983 StatePlane California III
    cal3 = {
        "proj": "lcc +lat_1=37.06666666666667 +lat_2=38.43333333333333 +lat_0=36.5 +lon_0=-120.5 +x_0=2000000 +y_0=500000.0000000002",
        "ellps": "GRS80",
        "datum": "NAD83",
        "no_defs": True,
    }

    # CMP network
    cmp_segments_gdf = cmp_segments_gdf.to_crs(cal3)
    cmp_segments_gdf["cmp_name"] = cmp_segments_gdf["cmp_name"].str.replace("/ ", "/")
    cmp_segments_gdf["cmp_name"] = cmp_segments_gdf["cmp_name"].str.lower()
    # m to ft
    cmp_segments_gdf["Length"] = cmp_segments_gdf.geometry.length * 3.2808

    # INRIX network: add INRIX street names to be more comprehensive
    inrix_network_gdf["RoadName"] = inrix_network_gdf["RoadName"].str.lower()

    # Convert transit stops original coordinate system to state plane
    stops = stops.to_crs(cal3)
    stops["stop_name"] = stops["stop_name"].str.lower()
    stops[["street_1", "street_2"]] = stops.stop_name.str.split(
        "&", expand=True
    )  # split stop name into operating street and intersecting street

    # Create a buffer zone for each cmp segment
    ft = 160  # According to the memo from last CMP cycle
    mt = round(ft / 3.2808, 4)
    stops_buffer = stops.copy()
    stops_buffer["geometry"] = stops_buffer.geometry.buffer(mt)
    # stops_buffer.to_file(os.path.join(MAIN_DIR, 'stops_buffer.shp'))

    # cmp segments intersecting transit stop buffer zone
    cmp_segs_intersect = gpd.sjoin(
        cmp_segments_gdf, stops_buffer, predicate="intersects"
    ).reset_index()

    stops["near_cmp"] = 0
    cmp_segs_intersect["name_match"] = 0
    for stop_idx in range(len(stops)):
        stop_id = stops.loc[stop_idx, "stop_id"]
        stop_geo = stops.loc[stop_idx]["geometry"]
        stop_names = stops.loc[stop_idx]["street_1"].split("/")
        if "point lobos" in stop_names:
            stop_names = stop_names + ["geary"]
        if stop_id in {7357, 17357}:  # stop IDs renumbered (+10000) in 2022/23
            stop_names = stop_names + ["third st"]

        cmp_segs_int = cmp_segs_intersect[cmp_segs_intersect["stop_id"] == stop_id]
        cmp_segs_idx = cmp_segs_intersect.index[
            cmp_segs_intersect["stop_id"] == stop_id
        ].tolist()

        near_dis = 5000
        if ~cmp_segs_int.empty:
            for seg_idx in cmp_segs_idx:
                cmp_seg_id = cmp_segs_int.loc[seg_idx, "cmp_segid"]
                cmp_seg_geo = cmp_segs_int.loc[seg_idx]["geometry"]
                cmp_seg_names = cmp_segs_int.loc[seg_idx]["cmp_name"].split("/")
                if "bayshore" in cmp_seg_names:
                    cmp_seg_names = cmp_seg_names + ["bay shore"]
                if "3rd st" in cmp_seg_names:
                    cmp_seg_names = cmp_seg_names + ["third st"]
                if "19th ave" in cmp_seg_names:
                    cmp_seg_names = cmp_seg_names + ["19th avenue"]
                if "geary" in cmp_seg_names:
                    cmp_seg_names = cmp_seg_names + ["point lobos"]

                # Add INRIX street name to be comprehensive
                inrix_links = cmp_inrix_correspondence[
                    cmp_inrix_correspondence["CMP_SegID"] == cmp_seg_id
                ]
                inrix_link_names = inrix_network_gdf[
                    inrix_network_gdf["XDSegID"].isin(inrix_links["INRIX_SegID"])
                ]["RoadName"].tolist()
                inrix_link_names = list(filter(None, inrix_link_names))
                if len(inrix_link_names) > 0:
                    inrix_link_names = list(set(inrix_link_names))
                    cmp_seg_link_names = cmp_seg_names + inrix_link_names
                else:
                    cmp_seg_link_names = cmp_seg_names

                matched_names = [
                    stop_name
                    for stop_name in stop_names
                    if any(cname in stop_name for cname in cmp_seg_link_names)
                ]
                if len(matched_names) > 0:
                    stops.loc[stop_idx, "near_cmp"] = 1
                    cmp_segs_intersect.loc[seg_idx, "name_match"] = 1
                    cur_dis = stop_geo.distance(cmp_seg_geo)
                    cmp_segs_intersect.loc[seg_idx, "distance"] = cur_dis
                    near_dis = min(near_dis, cur_dis)
                    stops.loc[stop_idx, "near_dis"] = near_dis

    stops_near_cmp = stops[stops["near_cmp"] == 1]
    stops_near_cmp = stops_near_cmp.to_crs(wgs84)

    stops_near_cmp_list = stops_near_cmp["stop_id"].unique().tolist()

    cmp_segs_near = cmp_segs_intersect[cmp_segs_intersect["name_match"] == 1]

    # Remove mismatched stops based on manual review
    remove_cmp_stop = [
        (175, 5546),
        (175, 5547),
        (175, 7299),
        (175, 5544),
        (66, 7744),
        (214, 7235),
        (107, 4735),
        (115, 4275),
        (143, 4824),
        (172, 5603),
    ]
    # stop IDs renumbered (+10000) in 2022/23
    if year > 2022:
        [(cmp_seg_id, stop_id + 10000) for (cmp_seg_id, stop_id) in remove_cmp_stop]
    for remove_idx in range(len(remove_cmp_stop)):
        rmv_cmp_id = remove_cmp_stop[remove_idx][0]
        rmv_stop_id = remove_cmp_stop[remove_idx][1]
        remove_df_idx = cmp_segs_near.index[
            (cmp_segs_near["cmp_segid"] == rmv_cmp_id)
            & (cmp_segs_near["stop_id"] == rmv_stop_id)
        ].tolist()
        if len(remove_df_idx) > 0:
            cmp_segs_near = cmp_segs_near.drop([remove_df_idx[0]], axis=0)

    apc_cmp = (
        pl.from_pandas(apc_notnull)
        .filter(
            (
                (pl.col("DOW") > 1) & (pl.col("DOW") < 5)  # only Tue, Wed, Thu
                # CMP monitoring months (if required):
                # & ((pl.col("Month") == 4) | (pl.col("Month") == 5))
            )
        )
        .with_columns(
            pl.col("Date").dt.day().alias("Day"),
            (
                pl.col("Open_Hour")
                + pl.col("Open_Minute") / 60
                + pl.col("Open_Second") / 3600
            ).alias("Open_Time_float"),
            (
                pl.col("Close_Hour")
                + pl.col("Close_Minute") / 60
                + pl.col("Close_Second") / 3600
            ).alias("Close_Time_float"),
        )
    ).to_pandas()

    # # Match AM&PM transit stops to CMP segments
    angle_thrd = 10

    # ## AM
    apc_cmp_am = apc_cmp[(apc_cmp["Open_Hour"] < 9) & (apc_cmp["Close_Hour"] > 6)]
    apc_cmp_am = apc_cmp_am.merge(
        stops, left_on="BS_ID", right_on="stop_id", how="left"
    )
    apc_cmp_am = apc_cmp_am.sort_values(
        by=["TRIP_ID_EXTERNAL", "Date", "VEHICLE_ID", "Open_Time"]
    ).reset_index()

    print("------------Start processing AM trips------------")
    apc_pairs_am = match_stop_pairs_to_cmp(
        apc_cmp_am,
        stops_near_cmp_list,
        cmp_segs_near,
        cmp_segments_gdf,
        angle_thrd,
    )

    # ## PM
    apc_cmp_pm = apc_cmp[
        (apc_cmp["Open_Time_float"] <= 18.5) & (apc_cmp["Close_Time_float"] >= 16.5)
    ]

    apc_cmp_pm = apc_cmp_pm.merge(
        stops, left_on="BS_ID", right_on="stop_id", how="left"
    )
    apc_cmp_pm = apc_cmp_pm.sort_values(
        by=["TRIP_ID_EXTERNAL", "Date", "VEHICLE_ID", "Open_Time"]
    ).reset_index()

    print("------------Start processing PM trips------------")
    apc_pairs_pm = match_stop_pairs_to_cmp(
        apc_cmp_pm,
        stops_near_cmp_list,
        cmp_segs_near,
        cmp_segments_gdf,
        angle_thrd,
    )

    # Transit Speeds on CMP Segment
    # ## AM
    apc_cmp_speeds_am = match_intermediate_apc_stops(
        apc_pairs_am,
        apc_cmp_am,
        overlap_pairs,
        cmp_segments_gdf,
        "AM",
        year,
        output_dir,
    )

    # ## PM
    apc_cmp_speeds_pm = match_intermediate_apc_stops(
        apc_pairs_pm,
        apc_cmp_pm,
        overlap_pairs,
        cmp_segments_gdf,
        "PM",
        year,
        output_dir,
    )

    # ## Combine AM and PM
    apc_cmp_speeds = pd.concat(
        (apc_cmp_speeds_am, apc_cmp_speeds_pm), ignore_index=True
    )
    apc_cmp_speeds = apc_cmp_speeds[apc_cmp_speeds["sample_size"] >= 9]
    print("Number of segment-periods ", len(apc_cmp_speeds))

    out_cols = [
        "cmp_segid",
        "year",
        "source",
        "period",
        "avg_speed",
        "std_dev",
        "cov",
        "sample_size",
        "comment",
    ]
    return apc_cmp_speeds[out_cols]


def create_apc_notnull(apc_df):
    apc_notnull = (
        (
            apc_df.drop_nulls(subset="CLOSE_DATE_TIME")
            .with_columns(pl.col("ACTUALDATE").str.to_datetime().alias("Date"))
            .with_columns(
                pl.col("Date").dt.weekday().alias("DOW")  # day of week: Mon=1 ... Sun=7
            )
            .with_columns(
                pl.col("Date").dt.month().alias("Month"),
                pl.when(pl.col("DOW") < 6)
                .then(pl.lit("Weekdays"))
                .when(pl.col("DOW") == 6)
                .then(pl.lit("Saturday"))
                .otherwise(pl.lit("Sunday"))
                .alias("DayType"),
            )
        )
        .collect()
        .to_pandas()
    )  # cannot pass LazyFrame directly to_pandas
    # cannot get len(apc_df) if apc_df is a LazyFrame, so commented out for now
    # print(
    #     "Percent of records ignored "
    #     "(due to null value in field CLOSE_DATE_TIME): ",
    #     round(100 - 100 * (len(apc_notnull) / len(apc_df.collect())), 2),
    # )
    apc_notnull["Close_Hour"] = apc_notnull["CLOSE_DATE_TIME"].str[10:13].astype(int)
    apc_notnull["Close_Minute"] = apc_notnull["CLOSE_DATE_TIME"].str[14:16].astype(int)
    apc_notnull["Close_Second"] = apc_notnull["CLOSE_DATE_TIME"].str[17:19].astype(int)
    # apc_notnull['Close_Period'] = apc_notnull['CLOSE_DATE_TIME'].str[-2:]
    apc_notnull["Close_Time"] = (
        apc_notnull["Date"].astype("str")
        + " "
        + apc_notnull["Close_Hour"].astype("str")
        + ":"
        + apc_notnull["Close_Minute"].astype("str")
        + ":"
        + apc_notnull["Close_Second"].astype("str")
    )
    apc_notnull["Close_Time"] = pd.to_datetime(apc_notnull["Close_Time"])
    apc_notnull["Epoch"] = (
        2 * apc_notnull["Close_Time"].dt.hour
        + apc_notnull["Close_Time"].dt.minute // 30
    )

    apc_notnull["Open_Hour"] = apc_notnull["OPEN_DATE_TIME"].str[10:13].astype(int)
    apc_notnull["Open_Minute"] = apc_notnull["OPEN_DATE_TIME"].str[14:16].astype(int)
    apc_notnull["Open_Second"] = apc_notnull["OPEN_DATE_TIME"].str[17:19].astype(int)
    # apc_notnull['Open_Period'] = apc_notnull['OPEN_DATE_TIME'].str[-2:]
    apc_notnull["Open_Time"] = (
        apc_notnull["Date"].astype("str")
        + " "
        + apc_notnull["Open_Hour"].astype("str")
        + ":"
        + apc_notnull["Open_Minute"].astype("str")
        + ":"
        + apc_notnull["Open_Second"].astype("str")
    )
    apc_notnull["Open_Time"] = pd.to_datetime(apc_notnull["Open_Time"])
    return apc_notnull


def read_gtfs_stops_GIS(
    gtfs_stops_GIS_filepath: str | Path,
) -> gpd.GeoDataFrame:
    stops = gpd.read_file(gtfs_stops_GIS_filepath)
    stops["stop_id"] = stops["stop_id"].astype(int)
    return stops


def transit_volume_and_speed(config):
    cmp_segments_gdf = gpd.read_file(Path(config["cmp_plus_GIS_filepath"]))
    year = config["year"]
    stops = read_gtfs_stops_GIS(Path(config["gtfs_stops_GIS_filepath"]))
    output_dir = Path(config["output_directory"])

    os.makedirs(output_dir, exist_ok=True)

    # Read in transit APC data
    apc_dfs = (
        pl.scan_csv(Path(config["apc_directory"]) / f, dtypes={"ROUTE_ALPHA": pl.Utf8})
        for f in config["apc_filenames"]
    )
    apc_df = pl.concat(apc_dfs, how="vertical", rechunk=False)

    # Read in the list of stop pairs manually identified
    # that are patially overlap with cmp segments
    # TODO not sure how to generate this postprocessing file at all,
    # thus keep using 2022 one. Consider removing the code if this may
    # not be needed
    overlap_pairs = pd.read_csv(Path(config["postprocessing_overlap_pairs_filepath"]))

    # INRIX network: add INRIX street names to be more comprehensive
    # TODO can't we just get streetnames from the CMP segments GIS file?
    inrix_network_gdf = gpd.read_file(Path(config["inrix_network_GIS_filepath"]))
    cmp_inrix_correspondence = pd.read_csv(
        Path(config["cmp_inrix_network_conflation_filepath"])
    )

    apc_notnull = create_apc_notnull(update_apc_stopid(apc_df, year))
    calculate_boardings_alightings_loads(apc_notnull, stops).to_csv(
        output_dir / f"Muni-APC-Transit_Volume-{year}.csv", index=False
    )
    calculate_transit_speed_and_reliability(
        cmp_segments_gdf,
        inrix_network_gdf,
        cmp_inrix_correspondence,
        apc_notnull,
        stops,
        overlap_pairs,
        year,
        output_dir,
    ).to_csv(output_dir / f"Muni-APC-Transit_Speeds-{year}.csv", index=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calculate transit volume and speed from APC data."
    )
    parser.add_argument("config_filepath", help="config .toml filepath")
    args = parser.parse_args()
    with open(args.config_filepath, "rb") as f:
        transit_volume_and_speed(tomllib.load(f))
