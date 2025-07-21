"""
This script is developed to automatically establish the corresponding relationship between CMP segments and INRIX XD network links.
It finds INRIX links that are near each CMP segment and decides the matching links based on street name, angle and distance attributes.

INPUTS:
1. cmp_roadway_segments.gpkg, the CMP segment GIS file provided by SFCTA.
2. inrix_xd_sf.gpkg, the INRIX XD network shapefile provided by INRIX. Because the originial shapefile provided is for the whole
state of California, only roadways in San Francisco County are selected and exported as inrix_xd_sf.gpkg.

OUTPUTS:
1. cmp_roadway_segments_matchedlength_check.gpkg, a shapefile generated for quality check purpose. The field "Len_Ratio" indicates the
ratio of the total length of matched INRIX links over the length of the CMP segment. Special attention should should be given to
segments whose Len_Ratio is below 95% or over 100%.
2. CMP_Segment_INRIX_Links_Correspondence.csv, a csv file containing the correspondence between CMP segments and INRIX XD links. The
field "Length_Matched" indicates the length of an INRIX link matched to a CMP segment. Note that the table is not final as quality
assurance needs to be performed on the conflation results and necessary changes could be made. Please see
Network Conflation Process Memo.docx for more detailed discussions.

USAGE:
To use the script, place the script under the same folder with input files and run with following command:
python SF_CMP_INRIX_Network_Conflation.py
"""

import argparse
import math
import tomllib
import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point, mapping

warnings.filterwarnings("ignore")

# NAD 1983 StatePlane California III
cal3 = {
    "proj": "lcc +lat_1=37.06666666666667 +lat_2=38.43333333333333 +lat_0=36.5 +lon_0=-120.5 +x_0=2000000 +y_0=500000.0000000002",
    "ellps": "GRS80",
    "datum": "NAD83",
    "no_defs": True,
}


def _geometry_get_start_end_vertices(linelike_geometry: LineString | MultiLineString):
    if isinstance(linelike_geometry, LineString):
        coords = list(linelike_geometry.coords)
        start = coords[0]
        end = coords[-1]
    elif isinstance(linelike_geometry, MultiLineString):
        lines = list(linelike_geometry.geoms)
        start = list(lines[0].coords)[0]
        end = list(lines[-1].coords)[-1]
    return MultiPoint([start, end])


def gdf_get_start_end_vertices(linelike_gdf, cols_to_keep, latlong_cols=True):
    start_end_vertex_gdf = (
        # replace (Multi)LineString geometry column with
        # geometry column of MultiPoint([start_vertex, end_vertex])
        linelike_gdf[cols_to_keep]
        .set_geometry(
            linelike_gdf.geometry.map(_geometry_get_start_end_vertices), drop=True
        )
        # explode the geometry column of MultiPoints (each of the start & end vertices)
        # to each point having their own row, then using the index level 1 to set the
        # type column as "start" or "end"
        .explode(index_parts=True)
        .reset_index(level=1)
        .rename(columns={"level_1": "type"})
    )
    start_end_vertex_gdf["type"] = start_end_vertex_gdf["type"].map(
        {0: "begin", 1: "end"}
    )
    if latlong_cols:  # TODO remove this and just use the Point geometry col directly
        start_end_vertex_gdf["Latitude"] = start_end_vertex_gdf.geometry.y
        start_end_vertex_gdf["Longitude"] = start_end_vertex_gdf.geometry.x
    return start_end_vertex_gdf.reset_index(drop=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("toml_filepath")
    args = parser.parse_args()
    with open(args.toml_filepath, "rb") as f:
        config = tomllib.load(f)

    if config["mode"] not in {"monthly", "biennial"}:
        raise NotImplementedError

    inrix_map_version = config["inrix_map_version"]
    inrix_sf_network_gis_filepath = Path(config["input_gis_filepath"]["dir"]) / config[
        "input_gis_filepath"
    ]["inrix_sf_network"].format(inrix_map_version=inrix_map_version)
    inrix_segid_col = "XDSegID"
    cmp_segments_gis_filepath = config["input_gis_filepath"]["cmp_segments"][
        config["mode"]
    ]
    output_dir = Path(config["output"]["dir"])
    output_filename_base = config["output"]["filename_base"].format(
        inrix_map_version=inrix_map_version
    )
    output_filepath = output_dir / (
        output_filename_base
        + ("_Manual" if config["manual_update"]["manual_update"] else "")
        + ("-expandednetwork" if config["mode"] == "monthly" else "")
        + ".csv"
    )

    # Convert original coordinate system to California III state plane
    # CMP network
    cmp_segments = gpd.read_file(cmp_segments_gis_filepath).to_crs(cal3)
    cmp_segments["cmp_name"] = cmp_segments["cmp_name"].str.replace("/ ", "/")
    # replace length column in CMP segments (mi) GIS file with length in the CRS unit
    cmp_segments["length"] = cmp_segments.geometry.length
    cmp_segments["length"] = cmp_segments["length"] * 3.2808  # meters to feet

    # INRIX XD network
    # HOTFIX, leaving this hardcoded for now
    inrix_network = gpd.read_file(inrix_sf_network_gis_filepath).to_crs(cal3)
    inrix_network["length"] = inrix_network.geometry.length
    inrix_network["length"] = inrix_network["length"] * 3.2808  # meters to feet
    inrix_network["SegID"] = inrix_network[inrix_segid_col].astype(int)
    inrix_network["Miles"] = inrix_network["Miles"].astype(float)
    inrix_network = inrix_network.rename(
        columns={"PreviousXD": "PreviousSe", "NextXDSegI": "NextSegID"}
    )

    inrix_endpoints = gdf_get_start_end_vertices(inrix_network, ["SegID", "RoadName"])

    # Assign unique node id
    endpoints_cnt = (
        inrix_endpoints.groupby(["geometry", "Latitude", "Longitude"])
        .SegID.count()
        .reset_index()
        # CH NOTE: NodeCnt refers to the segment ID
        .rename(columns={"SegID": "NodeCnt"})
    )
    endpoints_cnt["NodeID"] = endpoints_cnt.index + 1
    # endpoints_cnt.to_file(
    #     output_dir / (output_filename_base + "-inrix_endpoints_unique.gpkg")
    # )

    inrix_endpoints = inrix_endpoints.merge(
        endpoints_cnt, on=["geometry", "Latitude", "Longitude"], how="left"
    )

    # TODO can we just use the Point geometry col directly instead of lat/long?
    # Attached the endpoint information to the link network
    endpoints_begin = inrix_endpoints[inrix_endpoints["type"] == "begin"][
        ["SegID", "Latitude", "Longitude", "NodeID"]
    ]
    endpoints_begin.columns = ["SegID", "B_Lat", "B_Long", "B_NodeID"]

    endpoints_end = inrix_endpoints[inrix_endpoints["type"] == "end"][
        ["SegID", "Latitude", "Longitude", "NodeID"]
    ]
    endpoints_end.columns = ["SegID", "E_Lat", "E_Long", "E_NodeID"]

    inrix_network = inrix_network.merge(endpoints_begin, on="SegID")
    inrix_network = inrix_network.merge(endpoints_end, on="SegID")

    # Get endnodes of CMP segments
    cmp_endpoints = gdf_get_start_end_vertices(
        cmp_segments, ["cmp_segid", "cmp_name"]
    ).reset_index(names="NodeID")

    cmp_endpoint_b = cmp_endpoints[cmp_endpoints["type"] == "begin"][
        ["cmp_segid", "Latitude", "Longitude", "NodeID"]
    ]
    cmp_endpoint_b.columns = ["cmp_segid", "B_Lat", "B_Long", "CMP_Node_B"]
    cmp_endpoint_e = cmp_endpoints[cmp_endpoints["type"] == "end"][
        ["cmp_segid", "Latitude", "Longitude", "NodeID"]
    ]
    cmp_endpoint_e.columns = ["cmp_segid", "E_Lat", "E_Long", "CMP_Node_E"]

    cmp_segments = cmp_segments.merge(cmp_endpoint_b, on="cmp_segid", how="left")
    cmp_segments = cmp_segments.merge(cmp_endpoint_e, on="cmp_segid", how="left")

    # Calculate the bearing of cmp segments
    cmp_segments["Degree"] = cmp_segments.apply(
        lambda x: (180 / math.pi)
        * math.atan2(x["E_Long"] - x["B_Long"], x["E_Lat"] - x["B_Lat"]),
        axis=1,
    )

    # # Network Conflation
    # ## Get nearby INRIX links
    # Create a buffer zone for each cmp segment
    ft = 150  # 150 ft distance
    mt = round(ft / 3.2808, 4)
    cmp_segs_buffer = cmp_segments.copy()
    cmp_segs_buffer["geometry"] = np.where(
        cmp_segs_buffer["cmp_segid"] == 81,
        cmp_segs_buffer.geometry.buffer(mt * 2),
        cmp_segs_buffer.geometry.buffer(mt),
    )
    # cmp_segs_buffer.to_file(
    #     output_dir / (output_filename_base + "-cmp_segments_buffer.gpkg")
    # )

    # INRIX lines intersecting cmp segment buffer zone
    inrix_lines_intersect = gpd.sjoin(
        inrix_network, cmp_segs_buffer, predicate="intersects"
    ).reset_index()

    # INRIX lines within cmp segment buffer zone
    inrix_lines_within = gpd.sjoin(
        inrix_network, cmp_segs_buffer, predicate="within"
    ).reset_index()

    # ## Determine matching INRIX links within each CMP buffer
    len_ratio_thrhd = 0.8
    angle_thrhd = 15
    for cmp_seg_idx in range(len(cmp_segments)):
        cmp_seg_id = cmp_segments.loc[cmp_seg_idx, "cmp_segid"]
        cmp_seg_geo = cmp_segments.loc[cmp_seg_idx]["geometry"]
        cmp_seg_len = cmp_segments.loc[cmp_seg_idx]["length"]
        cmp_b_lat = cmp_segments.loc[cmp_seg_idx]["B_Lat"]
        cmp_b_long = cmp_segments.loc[cmp_seg_idx]["B_Long"]
        cmp_e_lat = cmp_segments.loc[cmp_seg_idx]["E_Lat"]
        cmp_e_long = cmp_segments.loc[cmp_seg_idx]["E_Long"]
        cmp_names = (
            cmp_segments.loc[cmp_seg_idx]["cmp_name"].lower().split("/")
        )  # Street name
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] == "Doyle/Lombard/Richardson":
            cmp_names = cmp_names + ["us-101", "us 101"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] == "Duboce/Division":
            cmp_names = cmp_names + ["13th st", "13th street", "central freeway"]
        if (cmp_seg_id == 147) or (cmp_seg_id == 148):
            cmp_names = cmp_names + ["kennedy"]
        if (cmp_seg_id == 26) or (cmp_seg_id == 27):
            cmp_names = cmp_names + ["veterans"]

        # v2001 updates
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in [
            "19th Ave/Park Presidio",
            "Junipero Serra",
        ]:
            cmp_names = cmp_names + ["ca 1"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in ["Skyline", "Sloat"]:
            cmp_names = cmp_names + ["ca 35"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] == "I-80":
            cmp_names = cmp_names + ["i 80", "james lick freeway"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] == "I-280":
            cmp_names = cmp_names + ["i 280"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in ["US-101"]:
            cmp_names = cmp_names + ["us 101", "central freeway"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in ["Van Ness/S VanNess"]:
            cmp_names = cmp_names + ["us 101"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in ["Geary"]:
            cmp_names = cmp_names + ["geary boulevard", "point lobos avenue"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in ["Guerrero/San Jose"]:
            cmp_names = cmp_names + ["san jose avenue"]
        if cmp_segments.loc[cmp_seg_idx]["cmp_name"] in ["Harrison"]:
            cmp_names = cmp_names + ["harrison street"]
        if (cmp_seg_id == 52) or (cmp_seg_id == 47):
            cmp_names = ["robert c levy tunnel"]
        if (cmp_seg_id == 192) or (cmp_seg_id == 193):
            cmp_names = ["octavia boulevard"]
        if cmp_seg_id == 150:
            cmp_names = ["main street"]
        if cmp_seg_id == 175:
            cmp_names = ["mission street", "otis street"]

        inrix_lns_within = inrix_lines_within[
            inrix_lines_within["cmp_segid"] == cmp_seg_id
        ]
        inrix_lns_idx = inrix_lines_within.index[
            inrix_lines_within["cmp_segid"] == cmp_seg_id
        ].tolist()
        if ~inrix_lns_within.empty:
            for ln_idx in inrix_lns_idx:
                inrix_b_lat = inrix_lines_within.loc[ln_idx]["B_Lat_left"]
                inrix_b_long = inrix_lines_within.loc[ln_idx]["B_Long_left"]
                inrix_e_lat = inrix_lines_within.loc[ln_idx]["E_Lat_left"]
                inrix_e_long = inrix_lines_within.loc[ln_idx]["E_Long_left"]
                inrix_geo = inrix_lines_within.loc[ln_idx]["geometry"]
                inrix_len = (
                    inrix_lines_within.loc[ln_idx]["Miles"] * 5280
                )  # miles to feet

                if pd.notnull(inrix_lines_within.loc[ln_idx]["RoadName"]):
                    inrix_roadname = (
                        inrix_lines_within.loc[ln_idx]["RoadName"].lower().split("/")
                    )  # Street name
                else:
                    inrix_roadname = []
                if pd.notnull(inrix_lines_within.loc[ln_idx]["RoadNumber"]):
                    inrix_roadnumber = (
                        inrix_lines_within.loc[ln_idx]["RoadNumber"].lower().split("/")
                    )
                    inrix_roadname = inrix_roadname + inrix_roadnumber
                if pd.notnull(inrix_lines_within.loc[ln_idx]["RoadList"]):
                    inrix_roadlist = (
                        inrix_lines_within.loc[ln_idx]["RoadList"].lower().split("/")
                    )
                    inrix_roadname = inrix_roadname + inrix_roadlist
                inrix_roadname = list(set(inrix_roadname))
                if inrix_roadname:
                    matched_names = [
                        iname
                        for iname in inrix_roadname
                        if any(cname in iname for cname in cmp_names)
                    ]
                    if len(matched_names) > 0:
                        inrix_lines_within.loc[ln_idx, "namematch"] = 1
                    else:
                        inrix_lines_within.loc[ln_idx, "namematch"] = 0
                else:
                    inrix_lines_within.loc[ln_idx, "namematch"] = 0

                inrix_b_point = Point(float(inrix_b_long), float(inrix_b_lat))
                inrix_b_dis = cmp_seg_geo.project(inrix_b_point)
                inrix_lines_within.loc[ln_idx, "INRIX_B_Loc"] = (
                    inrix_b_dis * 3.2808
                )  # meters to feet
                inrix_b_projected = cmp_seg_geo.interpolate(
                    inrix_b_dis
                )  # projected inrix begin point on cmp segment

                inrix_e_point = Point(float(inrix_e_long), float(inrix_e_lat))
                inrix_e_dis = cmp_seg_geo.project(inrix_e_point)
                inrix_lines_within.loc[ln_idx, "INRIX_E_Loc"] = inrix_e_dis * 3.2808
                inrix_e_projected = cmp_seg_geo.interpolate(
                    inrix_e_dis
                )  # projected inrix end point on cmp segment

                inrix_b_e_dis = (inrix_e_dis - inrix_b_dis) * 3.2808
                inrix_lines_within.loc[ln_idx, "INX_B_CMP_B"] = inrix_b_dis * 3.2808
                inrix_lines_within.loc[ln_idx, "INX_E_CMP_E"] = (
                    cmp_seg_len - inrix_e_dis * 3.2808
                )

                if (
                    (inrix_b_dis == 0)
                    & (inrix_b_long != cmp_b_long)
                    & (inrix_b_lat != cmp_b_lat)
                ):
                    # INRIX link begin point is outside cmp segment
                    cmp_b_point = Point(float(cmp_b_long), float(cmp_b_lat))
                    cmp_b_dis = inrix_geo.project(cmp_b_point)
                    cmp_b_inrix_e_dis = inrix_len - cmp_b_dis * 3.2808
                    cmp_b_projected = inrix_geo.interpolate(cmp_b_dis)
                    projected_len_ratio = abs(inrix_b_e_dis) / cmp_b_inrix_e_dis
                elif (
                    (inrix_e_dis * 3.2808 / cmp_seg_len > 0.99)
                    & (inrix_e_long != cmp_e_long)
                    & (inrix_e_lat != cmp_e_lat)
                ):
                    # INRIX link end point is outside cmp segment
                    cmp_e_point = Point(float(cmp_e_long), float(cmp_e_lat))
                    cmp_e_inrix_b_dis = inrix_geo.project(cmp_e_point)
                    if cmp_e_inrix_b_dis == 0:
                        inrix_lines_within.loc[ln_idx, "Matching"] = "No"
                        continue
                    cmp_e_projected = inrix_geo.interpolate(cmp_e_inrix_b_dis)
                    projected_len_ratio = abs(inrix_b_e_dis) / (
                        cmp_e_inrix_b_dis * 3.2808
                    )
                else:
                    # INRIX link in between cmp endpoints
                    projected_len_ratio = abs(inrix_b_e_dis) / inrix_len

                inrix_lines_within.loc[ln_idx, "Proj_Ratio"] = projected_len_ratio

                inrix_degree = (180 / math.pi) * math.atan2(
                    inrix_e_long - inrix_b_long, inrix_e_lat - inrix_b_lat
                )
                # Ensure the degree is calculated following the original direction
                if inrix_e_dis > inrix_b_dis:
                    cmp_degree = (180 / math.pi) * math.atan2(
                        inrix_e_projected.x - inrix_b_projected.x,
                        inrix_e_projected.y - inrix_b_projected.y,
                    )
                else:
                    cmp_degree = (180 / math.pi) * math.atan2(
                        inrix_b_projected.x - inrix_e_projected.x,
                        inrix_b_projected.y - inrix_e_projected.y,
                    )

                inrix_cmp_angle = abs(cmp_degree - inrix_degree)
                if inrix_cmp_angle > 270:
                    inrix_cmp_angle = 360 - inrix_cmp_angle
                inrix_lines_within.loc[ln_idx, "Proj_Angle"] = inrix_cmp_angle

                if (projected_len_ratio > len_ratio_thrhd) & (
                    inrix_cmp_angle < angle_thrhd
                ):
                    inrix_lines_within.loc[ln_idx, "Matching"] = "Yes"
                else:
                    inrix_lines_within.loc[ln_idx, "Matching"] = "No"

    inrix_lines_matched = (
        inrix_lines_within[
            (inrix_lines_within["namematch"] == 1)
            & (inrix_lines_within["Matching"] == "Yes")
        ]
        .sort_values(["cmp_segid", "INX_B_CMP_B"])
        .reset_index()
    )
    inrix_lines_matched["Length_Matched"] = (
        inrix_lines_matched["INRIX_E_Loc"] - inrix_lines_matched["INRIX_B_Loc"]
    )

    cols = [
        "SegID",
        "PreviousSe",
        "NextSegID",
        "B_NodeID",
        "E_NodeID",
        "Length_Matched",
        "cmp_segid",
        "INRIX_B_Loc",
        "INRIX_E_Loc",
        "INX_B_CMP_B",
        "INX_E_CMP_E",
    ]
    inrix_lines_matched_final = inrix_lines_matched[cols]

    # Calculate the total length of INRIX links that have been matched
    inrix_matched_length = (
        inrix_lines_matched_final.groupby("cmp_segid")
        .Length_Matched.sum()
        .reset_index()
    )
    inrix_matched_length.columns = ["cmp_segid", "Len_Matched"]
    inrix_matched_length["cmp_segid"] = inrix_matched_length["cmp_segid"].astype(int)
    cmp_segments = cmp_segments.merge(inrix_matched_length, on="cmp_segid", how="left")

    # Calculate the ratio of the total length of matched INRIX links to the CMP segment length
    cmp_segments["Len_Ratio"] = np.where(
        pd.isnull(cmp_segments["Len_Matched"]),
        0.0,
        cmp_segments["Len_Matched"] / cmp_segments["length"],
    )
    cmp_segments["Len_Ratio"] = cmp_segments["Len_Ratio"].round(1)

    # ## Search forward and backward based on already matched INRIX links
    # Establish sequence from matched links
    gap_thrhd = 0.01
    for cmp_seg_idx in range(len(cmp_segments)):
        if (cmp_segments.loc[cmp_seg_idx, "Len_Ratio"] > 0) & (
            cmp_segments.loc[cmp_seg_idx, "Len_Ratio"] < 98
        ):
            cmp_seg_id = cmp_segments.loc[cmp_seg_idx, "cmp_segid"]
            cmp_seg_geo = cmp_segments.loc[cmp_seg_idx]["geometry"]
            cmp_seg_buffer = cmp_segments.loc[cmp_seg_idx]["geometry"].buffer(
                mt
            )  # Create 150ft buffer for the segment
            cmp_b_lat = cmp_segments.loc[cmp_seg_idx]["B_Lat"]
            cmp_b_long = cmp_segments.loc[cmp_seg_idx]["B_Long"]
            cmp_e_lat = cmp_segments.loc[cmp_seg_idx]["E_Lat"]
            cmp_e_long = cmp_segments.loc[cmp_seg_idx]["E_Long"]
            cmp_seg_len = cmp_segments.loc[cmp_seg_idx]["length"]

            inrix_lns_matched = inrix_lines_matched_final[
                inrix_lines_matched_final["cmp_segid"] == cmp_seg_id
            ]
            inrix_lns_matched_idx = inrix_lns_matched.index.tolist()

            # Search backward to check previous links
            inrix_matched_first_idx = inrix_lns_matched_idx[0]
            inrix_matched_first_b_dis = inrix_lines_matched_final.loc[
                inrix_matched_first_idx
            ]["INX_B_CMP_B"]
            if inrix_matched_first_b_dis / cmp_seg_len < gap_thrhd:
                cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = "Yes"
            else:
                # Need find previous links
                preNode = inrix_lines_matched_final.loc[inrix_matched_first_idx][
                    "B_NodeID"
                ]
                found = 0
                matched = 0
                GAP_COUNTER = 0
                while inrix_matched_first_b_dis / cmp_seg_len > gap_thrhd:
                    GAP_COUNTER += 1
                    if GAP_COUNTER == 50:
                        print("Backward Search Loop")
                        print(
                            "Gap threshold issue: match_ratio= %s, check cmpid= %s"
                            % (
                                round(inrix_matched_first_b_dis / cmp_seg_len, 3),
                                cmp_seg_id,
                            )
                        )
                        break
                    preLinks = inrix_lines_intersect[
                        (inrix_lines_intersect["cmp_segid"] == cmp_seg_id)
                        & (inrix_lines_intersect["E_NodeID"] == preNode)
                    ]
                    if len(preLinks) == 0:
                        cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = (
                            "Previous links not found"
                        )
                        break
                    else:
                        preLinks_idx = preLinks.index.tolist()
                        for prelink_idx in preLinks_idx:
                            prelink_geo = inrix_lines_intersect.loc[prelink_idx][
                                "geometry"
                            ]
                            prelink_b_lat = preLinks.loc[prelink_idx]["B_Lat_left"]
                            prelink_b_long = preLinks.loc[prelink_idx]["B_Long_left"]
                            prelink_e_lat = preLinks.loc[prelink_idx]["E_Lat_left"]
                            prelink_e_long = preLinks.loc[prelink_idx]["E_Long_left"]
                            prelink_len = (
                                preLinks.loc[prelink_idx]["Miles"] * 5280
                            )  # miles to feet

                            if prelink_geo.within(
                                cmp_seg_buffer
                            ):  # prelink is within the buffer zone
                                prelink_b_point = Point(
                                    float(prelink_b_long), float(prelink_b_lat)
                                )
                                prelink_b_dis = cmp_seg_geo.project(prelink_b_point)
                                preLinks.loc[prelink_idx, "INRIX_B_Loc"] = (
                                    prelink_b_dis * 3.2808
                                )
                                prelink_b_projected = cmp_seg_geo.interpolate(
                                    prelink_b_dis
                                )  # projected prelink begin point on cmp segment

                                prelink_e_point = Point(
                                    float(prelink_e_long), float(prelink_e_lat)
                                )
                                prelink_e_dis = cmp_seg_geo.project(prelink_e_point)
                                preLinks.loc[prelink_idx, "INRIX_E_Loc"] = (
                                    prelink_e_dis * 3.2808
                                )
                                prelink_e_projected = cmp_seg_geo.interpolate(
                                    prelink_e_dis
                                )  # projected prelink end point on cmp segment

                                preLinks.loc[prelink_idx, "INX_B_CMP_B"] = (
                                    prelink_b_dis * 3.2808
                                )  # meters to feet
                                preLinks.loc[prelink_idx, "INX_E_CMP_E"] = (
                                    cmp_seg_len - prelink_e_dis * 3.2808
                                )  # meters to feet

                                prelink_b_e_dis = (
                                    prelink_e_dis - prelink_b_dis
                                ) * 3.2808
                                projected_len_ratio = abs(prelink_b_e_dis) / prelink_len
                                preLinks.loc[prelink_idx, "Proj_Ratio"] = (
                                    projected_len_ratio
                                )

                                prelink_degree = (180 / math.pi) * math.atan2(
                                    prelink_e_long - prelink_b_long,
                                    prelink_e_lat - prelink_b_lat,
                                )
                                # Ensure the degree is calculated following the original direction
                                if prelink_e_dis > prelink_b_dis:
                                    cmp_degree = (180 / math.pi) * math.atan2(
                                        prelink_e_projected.x - prelink_b_projected.x,
                                        prelink_e_projected.y - prelink_b_projected.y,
                                    )
                                else:
                                    cmp_degree = (180 / math.pi) * math.atan2(
                                        prelink_b_projected.x - prelink_e_projected.x,
                                        prelink_b_projected.y - prelink_e_projected.y,
                                    )

                                prelink_cmp_angle = abs(cmp_degree - prelink_degree)
                                if prelink_cmp_angle > 270:
                                    prelink_cmp_angle = 360 - prelink_cmp_angle
                                preLinks.loc[prelink_idx, "Proj_Angle"] = (
                                    prelink_cmp_angle
                                )

                                if (projected_len_ratio > len_ratio_thrhd) & (
                                    prelink_cmp_angle < angle_thrhd
                                ):
                                    found = 1
                                    cur_cnt = len(inrix_lines_matched_final)
                                    inrix_lines_matched_final.loc[cur_cnt, "SegID"] = (
                                        preLinks.loc[prelink_idx]["SegID"]
                                    )
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "PreviousSe"
                                    ] = preLinks.loc[prelink_idx]["PreviousSe"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "NextSegID"
                                    ] = preLinks.loc[prelink_idx]["NextSegID"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "Length_Matched"
                                    ] = prelink_b_e_dis
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "cmp_segid"
                                    ] = cmp_seg_id
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_B_Loc"
                                    ] = prelink_b_dis * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_E_Loc"
                                    ] = prelink_e_dis * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_B_CMP_B"
                                    ] = prelink_b_dis * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_E_CMP_E"
                                    ] = cmp_seg_len - prelink_e_dis * 3.2808
                                    inrix_matched_first_b_dis = prelink_b_dis * 3.2808
                                    if (
                                        inrix_matched_first_b_dis / cmp_seg_len
                                        < gap_thrhd
                                    ):
                                        matched = 1
                                    preNode = preLinks.loc[prelink_idx]["B_NodeID"]
                                    break
                                else:
                                    preLinks.loc[prelink_idx, "Matching"] = "No"

                            else:  # prelink is intersecting with buffer zone
                                # prelink End Node is within buffer zone while Begin Node is outside buffer zone
                                prelink_e_point = Point(
                                    float(prelink_e_long), float(prelink_e_lat)
                                )
                                prelink_e_cmp_b_dis = cmp_seg_geo.project(
                                    prelink_e_point
                                )  # meter, distance from cmp begin point to prelink end point
                                preLinks.loc[prelink_idx, "INRIX_E_Loc"] = (
                                    prelink_e_cmp_b_dis * 3.2808
                                )  # meters to feet
                                prelink_e_projected = cmp_seg_geo.interpolate(
                                    prelink_e_cmp_b_dis
                                )  # projected prelink end point on cmp segment

                                cmp_b_point = Point(float(cmp_b_long), float(cmp_b_lat))
                                cmp_b_dis = prelink_geo.project(
                                    cmp_b_point
                                )  # distance from inrix prelink to cmp begin point
                                cmp_b_prelink_e_dis = (
                                    prelink_len - cmp_b_dis * 3.2808
                                )  # feet
                                cmp_b_projected = prelink_geo.interpolate(
                                    cmp_b_dis
                                )  # projected cmp begin point on intersecting inrix link

                                projected_len_ratio = min(
                                    cmp_b_prelink_e_dis
                                    / (prelink_e_cmp_b_dis * 3.2808),
                                    (prelink_e_cmp_b_dis * 3.2808)
                                    / cmp_b_prelink_e_dis,
                                )
                                preLinks.loc[prelink_idx, "Proj_Ratio"] = (
                                    projected_len_ratio
                                )

                                prelink_degree = (180 / math.pi) * math.atan2(
                                    prelink_e_long - cmp_b_projected.x,
                                    prelink_e_lat - cmp_b_projected.y,
                                )
                                cmp_degree = (180 / math.pi) * math.atan2(
                                    prelink_e_projected.x - cmp_b_long,
                                    prelink_e_projected.y - cmp_b_lat,
                                )
                                prelink_cmp_angle = abs(cmp_degree - prelink_degree)
                                if prelink_cmp_angle > 270:
                                    prelink_cmp_angle = 360 - prelink_cmp_angle
                                preLinks.loc[prelink_idx, "Proj_Angle"] = (
                                    prelink_cmp_angle
                                )

                                if (projected_len_ratio > len_ratio_thrhd) & (
                                    prelink_cmp_angle < angle_thrhd
                                ):
                                    found = 1
                                    matched = 1
                                    cur_cnt = len(inrix_lines_matched_final)
                                    inrix_lines_matched_final.loc[cur_cnt, "SegID"] = (
                                        preLinks.loc[prelink_idx]["SegID"]
                                    )
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "PreviousSe"
                                    ] = preLinks.loc[prelink_idx]["PreviousSe"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "NextSegID"
                                    ] = preLinks.loc[prelink_idx]["NextSegID"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "Length_Matched"
                                    ] = prelink_e_cmp_b_dis * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "cmp_segid"
                                    ] = cmp_seg_id
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_B_Loc"
                                    ] = 0
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_E_Loc"
                                    ] = prelink_e_cmp_b_dis * 3.2808  # meters to feet
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_B_CMP_B"
                                    ] = 0
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_E_CMP_E"
                                    ] = (
                                        cmp_seg_len - prelink_e_cmp_b_dis * 3.2808
                                    )  # meters to feet
                                    inrix_matched_first_b_dis = 0
                                    break
                                else:
                                    preLinks.loc[prelink_idx, "Matching"] = "No"
                        if matched == 1:
                            cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = (
                                "Yes-LinkAdded"
                            )
                        if (
                            found == 0
                        ):  # break while loop if no mathcing link found in prelinks
                            cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = (
                                "No Matching Previous Link"
                            )
                            break

            # Search forward to maintain the sequence along the traveling direction
            inrix_matched_e_dis = inrix_lines_matched_final.loc[
                inrix_matched_first_idx
            ]["INX_E_CMP_E"]
            if inrix_matched_e_dis / cmp_seg_len < gap_thrhd:
                cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = "Yes"
            else:
                nextNode = inrix_lines_matched_final.loc[inrix_matched_first_idx][
                    "E_NodeID"
                ]
                found = 0
                matched = 0
                GAP_COUNTER = 0
                while inrix_matched_e_dis / cmp_seg_len > gap_thrhd:
                    GAP_COUNTER += 1
                    if GAP_COUNTER == 50:
                        print("Forward Search Loop")
                        print(
                            "Gap threshold issue: match_ratio= %s, check cmpid= %s"
                            % (
                                round(inrix_matched_e_dis / cmp_seg_len, 3),
                                cmp_seg_id,
                            )
                        )
                        break
                    if (
                        len(
                            inrix_lns_matched[inrix_lns_matched["B_NodeID"] == nextNode]
                        )
                        == 1
                    ):
                        matched_link_next = inrix_lns_matched[
                            inrix_lns_matched["B_NodeID"] == nextNode
                        ]
                        inrix_matched_e_dis = matched_link_next.INX_E_CMP_E.item()
                        nextNode = matched_link_next.E_NodeID.item()
                    elif (
                        len(
                            inrix_lns_matched[inrix_lns_matched["B_NodeID"] == nextNode]
                        )
                        > 1
                    ):
                        break
                    else:
                        nextLinks = inrix_lines_intersect[
                            (inrix_lines_intersect["cmp_segid"] == cmp_seg_id)
                            & (inrix_lines_intersect["B_NodeID"] == nextNode)
                        ]
                        if len(nextLinks) == 0:
                            cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = (
                                "Next links not found"
                            )
                            break
                        else:
                            nextLinks_idx = nextLinks.index.tolist()
                            for nextlink_idx in nextLinks_idx:
                                nextlink_geo = inrix_lines_intersect.loc[nextlink_idx][
                                    "geometry"
                                ]
                                nextlink_b_lat = nextLinks.loc[nextlink_idx][
                                    "B_Lat_left"
                                ]
                                nextlink_b_long = nextLinks.loc[nextlink_idx][
                                    "B_Long_left"
                                ]
                                nextlink_e_lat = nextLinks.loc[nextlink_idx][
                                    "E_Lat_left"
                                ]
                                nextlink_e_long = nextLinks.loc[nextlink_idx][
                                    "E_Long_left"
                                ]
                                nextlink_len = (
                                    nextLinks.loc[nextlink_idx]["Miles"] * 5280
                                )  # miles to feet

                                if nextlink_geo.within(
                                    cmp_seg_buffer
                                ):  # nextlink is within the buffer zone
                                    nextlink_b_point = Point(
                                        float(nextlink_b_long),
                                        float(nextlink_b_lat),
                                    )
                                    nextlink_b_dis = cmp_seg_geo.project(
                                        nextlink_b_point
                                    )
                                    nextLinks.loc[nextlink_idx, "INRIX_B_Loc"] = (
                                        nextlink_b_dis * 3.2808
                                    )  # meters to feet
                                    nextlink_b_projected = cmp_seg_geo.interpolate(
                                        nextlink_b_dis
                                    )  # projected nextlink begin point on cmp segment

                                    nextlink_e_point = Point(
                                        float(nextlink_e_long),
                                        float(nextlink_e_lat),
                                    )
                                    nextlink_e_dis = cmp_seg_geo.project(
                                        nextlink_e_point
                                    )
                                    nextLinks.loc[nextlink_idx, "INRIX_E_Loc"] = (
                                        nextlink_e_dis * 3.2808
                                    )  # meters to feet
                                    nextlink_e_projected = cmp_seg_geo.interpolate(
                                        nextlink_e_dis
                                    )  # projected nextlink end point on cmp segment

                                    nextLinks.loc[nextlink_idx, "INX_B_CMP_B"] = (
                                        nextlink_b_dis * 3.2808
                                    )  # meters to feet
                                    nextLinks.loc[nextlink_idx, "INX_E_CMP_E"] = (
                                        cmp_seg_len - nextlink_e_dis * 3.2808
                                    )  # meters to feet

                                    nextlink_b_e_dis = (
                                        nextlink_e_dis - nextlink_b_dis
                                    ) * 3.2808  # meters to feet
                                    projected_len_ratio = (
                                        abs(nextlink_b_e_dis) / nextlink_len
                                    )
                                    nextLinks.loc[nextlink_idx, "Proj_Ratio"] = (
                                        projected_len_ratio
                                    )

                                    nextlink_degree = (180 / math.pi) * math.atan2(
                                        nextlink_e_long - nextlink_b_long,
                                        nextlink_e_lat - nextlink_b_lat,
                                    )
                                    # Ensure the degree is calculated following the original direction
                                    if nextlink_e_dis > nextlink_b_dis:
                                        cmp_degree = (180 / math.pi) * math.atan2(
                                            nextlink_e_projected.x
                                            - nextlink_b_projected.x,
                                            nextlink_e_projected.y
                                            - nextlink_b_projected.y,
                                        )
                                    else:
                                        cmp_degree = (180 / math.pi) * math.atan2(
                                            nextlink_b_projected.x
                                            - nextlink_e_projected.x,
                                            nextlink_b_projected.y
                                            - nextlink_e_projected.y,
                                        )

                                    nextlink_cmp_angle = abs(
                                        cmp_degree - nextlink_degree
                                    )
                                    if nextlink_cmp_angle > 270:
                                        nextlink_cmp_angle = 360 - nextlink_cmp_angle
                                    nextLinks.loc[nextlink_idx, "Proj_Angle"] = (
                                        nextlink_cmp_angle
                                    )

                                    if (projected_len_ratio > len_ratio_thrhd) & (
                                        nextlink_cmp_angle < angle_thrhd
                                    ):
                                        found = 1
                                        cur_cnt = len(inrix_lines_matched_final)
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "SegID"
                                        ] = nextLinks.loc[nextlink_idx]["SegID"]
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "PreviousSe"
                                        ] = nextLinks.loc[nextlink_idx]["PreviousSe"]
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "NextSegID"
                                        ] = nextLinks.loc[nextlink_idx]["NextSegID"]
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "Length_Matched"
                                        ] = nextlink_b_e_dis
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "cmp_segid"
                                        ] = cmp_seg_id
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INRIX_B_Loc"
                                        ] = nextlink_b_dis * 3.2808  # meters to feet
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INRIX_E_Loc"
                                        ] = nextlink_e_dis * 3.2808  # meters to feet
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INX_B_CMP_B"
                                        ] = nextlink_b_dis * 3.2808  # meters to feet
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INX_E_CMP_E"
                                        ] = (
                                            cmp_seg_len - nextlink_e_dis * 3.2808
                                        )  # meters to feet
                                        inrix_matched_e_dis = (
                                            cmp_seg_len - nextlink_e_dis * 3.2808
                                        )
                                        if (
                                            inrix_matched_e_dis / cmp_seg_len
                                            < gap_thrhd
                                        ):
                                            matched = 1
                                        nextNode = nextLinks.loc[nextlink_idx][
                                            "E_NodeID"
                                        ]
                                        break
                                    else:
                                        nextLinks.loc[nextlink_idx, "Matching"] = "No"

                                else:  # nextlink is intersecting with buffer zone
                                    # nextlink Begin Node is within buffer zone while End Node is outside buffer zone
                                    nextlink_b_point = Point(
                                        float(nextlink_b_long),
                                        float(nextlink_b_lat),
                                    )
                                    nextlink_b_dis = cmp_seg_geo.project(
                                        nextlink_b_point
                                    )
                                    nextlink_b_cmp_e_dis = (
                                        cmp_seg_len - nextlink_b_dis * 3.2808
                                    )  # distance from nextlink begin point to cmp end point
                                    nextLinks.loc[nextlink_idx, "INRIX_B_Loc"] = (
                                        nextlink_b_dis * 3.2808
                                    )  # meters to feet
                                    nextlink_b_projected = cmp_seg_geo.interpolate(
                                        nextlink_b_dis
                                    )  # projected nextlink begin point on cmp segment

                                    cmp_e_point = Point(
                                        float(cmp_e_long), float(cmp_e_lat)
                                    )
                                    cmp_e_nextlink_b_dis = nextlink_geo.project(
                                        cmp_e_point
                                    )  # distance from inrix nextlink begin point to cmp end point
                                    cmp_e_projected = nextlink_geo.interpolate(
                                        cmp_e_nextlink_b_dis
                                    )  # projected cmp end point on intersecting inrix link

                                    projected_len_ratio = min(
                                        cmp_e_nextlink_b_dis
                                        * 3.2808
                                        / nextlink_b_cmp_e_dis,
                                        nextlink_b_cmp_e_dis
                                        / (cmp_e_nextlink_b_dis * 3.2808),
                                    )
                                    nextLinks.loc[nextlink_idx, "Proj_Ratio"] = (
                                        projected_len_ratio
                                    )

                                    nextlink_degree = (180 / math.pi) * math.atan2(
                                        cmp_e_projected.x - nextlink_b_long,
                                        cmp_e_projected.y - nextlink_b_lat,
                                    )
                                    cmp_degree = (180 / math.pi) * math.atan2(
                                        cmp_e_long - nextlink_b_projected.x,
                                        cmp_e_lat - nextlink_b_projected.y,
                                    )
                                    nextlink_cmp_angle = abs(
                                        cmp_degree - nextlink_degree
                                    )
                                    if nextlink_cmp_angle > 270:
                                        nextlink_cmp_angle = 360 - nextlink_cmp_angle
                                    nextLinks.loc[nextlink_idx, "Proj_Angle"] = (
                                        nextlink_cmp_angle
                                    )

                                    if (projected_len_ratio > len_ratio_thrhd) & (
                                        nextlink_cmp_angle < angle_thrhd
                                    ):
                                        found = 1
                                        matched = 1
                                        cur_cnt = len(inrix_lines_matched_final)
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "SegID"
                                        ] = nextLinks.loc[nextlink_idx]["SegID"]
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "PreviousSe"
                                        ] = nextLinks.loc[nextlink_idx]["PreviousSe"]
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "NextSegID"
                                        ] = nextLinks.loc[nextlink_idx]["NextSegID"]
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "Length_Matched"
                                        ] = nextlink_b_cmp_e_dis
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "cmp_segid"
                                        ] = cmp_seg_id
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INRIX_B_Loc"
                                        ] = nextlink_b_dis * 3.2808
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INRIX_E_Loc"
                                        ] = cmp_seg_len
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INX_B_CMP_B"
                                        ] = nextlink_b_dis * 3.2808
                                        inrix_lines_matched_final.loc[
                                            cur_cnt, "INX_E_CMP_E"
                                        ] = 0
                                        inrix_matched_e_dis = 0
                                        break
                                    else:
                                        nextLinks.loc[nextlink_idx, "Matching"] = "No"
                            if matched == 1:
                                cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = (
                                    "Yes-LinkAdded"
                                )
                            if (
                                found == 0
                            ):  # break while loop if no mathcing link found in nextlinks
                                cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = (
                                    "No Matching Next Link"
                                )
                                break

    # ## Find matches for remaining CMP segments that don't have any matches from previous steps
    # Create buffers at both endpoints to get intersecting INRIX links
    ft = 150
    mt = round(ft / 3.2808, 4)
    cmp_endpoints_buffer = cmp_endpoints.copy()
    cmp_endpoints_buffer["geometry"] = cmp_endpoints_buffer.geometry.buffer(mt)
    # cmp_endpoints_buffer.to_file(
    #     output_dir / (output_filename_base + "-cmp_endpoints_buffer.gpkg")
    # )

    # INRIX lines intersecting with cmp endpoint buffer zone
    inrix_lines_intersect_ep = gpd.sjoin(
        inrix_network, cmp_endpoints_buffer, predicate="intersects"
    ).reset_index()

    # Find matching lines for zero Len_Ratio
    for cmp_seg_idx in range(len(cmp_segments)):
        if cmp_segments.loc[cmp_seg_idx, "Len_Ratio"] == 0:
            cmp_seg_id = cmp_segments.loc[cmp_seg_idx, "cmp_segid"]
            cmp_seg_geo = cmp_segments.loc[cmp_seg_idx]["geometry"]
            cmp_seg_buffer = cmp_segments.loc[cmp_seg_idx]["geometry"].buffer(
                mt
            )  # Create 150ft buffer for the segment
            cmp_seg_len = cmp_segments.loc[cmp_seg_idx]["length"]
            cmp_b_id = cmp_segments.loc[cmp_seg_idx]["CMP_Node_B"]
            cmp_b_lat = cmp_segments.loc[cmp_seg_idx]["B_Lat"]
            cmp_b_long = cmp_segments.loc[cmp_seg_idx]["B_Long"]
            cmp_e_id = cmp_segments.loc[cmp_seg_idx]["CMP_Node_E"]
            cmp_e_lat = cmp_segments.loc[cmp_seg_idx]["E_Lat"]
            cmp_e_long = cmp_segments.loc[cmp_seg_idx]["E_Long"]

            intersect_b = inrix_lines_intersect_ep[
                inrix_lines_intersect_ep["NodeID"] == cmp_b_id
            ]

            if intersect_b.empty:
                cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = (
                    "No Intersecting Lines Found"
                )
            else:
                found_b = 0
                found_match = 0
                intersect_b_idx = intersect_b.index.tolist()
                for link_idx in intersect_b_idx:
                    link_geo = intersect_b.loc[link_idx]["geometry"]
                    link_b_lat = intersect_b.loc[link_idx]["B_Lat"]
                    link_b_long = intersect_b.loc[link_idx]["B_Long"]
                    link_e_lat = intersect_b.loc[link_idx]["E_Lat"]
                    link_e_long = intersect_b.loc[link_idx]["E_Long"]
                    link_len = (
                        intersect_b.loc[link_idx]["Miles"] * 5280
                    )  # miles to feet

                    # link End Node is within buffer zone while Begin Node is outside buffer zone
                    link_e_point = Point(float(link_e_long), float(link_e_lat))
                    link_e_cmp_b_dis = cmp_seg_geo.project(
                        link_e_point
                    )  # distance from cmp begin point to link end point
                    link_e_projected = cmp_seg_geo.interpolate(
                        link_e_cmp_b_dis
                    )  # projected link end point on cmp segment

                    if link_e_cmp_b_dis * 3.2808 / link_len < 0.02:
                        continue
                    if link_e_cmp_b_dis * 3.2808 / cmp_seg_len > 0.98:
                        cmp_b_point = Point(float(cmp_b_long), float(cmp_b_lat))
                        cmp_b_dis = link_geo.project(
                            cmp_b_point
                        )  # distance from inrix link to cmp begin point
                        cmp_b_projected = link_geo.interpolate(
                            cmp_b_dis
                        )  # projected cmp begin point on intersecting inrix link
                        cmp_e_point = Point(float(cmp_e_long), float(cmp_e_lat))
                        cmp_e_dis = link_geo.project(
                            cmp_e_point
                        )  # distance from inrix link to cmp begin point
                        cmp_e_projected = link_geo.interpolate(
                            cmp_e_dis
                        )  # projected cmp begin point on intersecting inrix link

                        link_degree = (180 / math.pi) * math.atan2(
                            cmp_e_projected.x - cmp_b_projected.x,
                            cmp_e_projected.y - cmp_b_projected.y,
                        )
                        cmp_degree = (180 / math.pi) * math.atan2(
                            cmp_e_long - cmp_b_long, cmp_e_lat - cmp_b_lat
                        )
                        link_cmp_angle = abs(cmp_degree - link_degree)
                        if link_cmp_angle > 270:
                            link_cmp_angle = 360 - link_cmp_angle

                        if link_cmp_angle < angle_thrhd:
                            found_match = 1
                            cur_cnt = len(inrix_lines_matched_final)
                            inrix_lines_matched_final.loc[cur_cnt, "SegID"] = (
                                intersect_b.loc[link_idx]["SegID"]
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "PreviousSe"] = (
                                intersect_b.loc[link_idx]["PreviousSe"]
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "NextSegID"] = (
                                intersect_b.loc[link_idx]["NextSegID"]
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "Length_Matched"] = (
                                link_e_cmp_b_dis * 3.2808
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "cmp_segid"] = (
                                cmp_seg_id
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "INRIX_B_Loc"] = 0
                            inrix_lines_matched_final.loc[cur_cnt, "INRIX_E_Loc"] = (
                                link_e_cmp_b_dis * 3.2808
                            )  # meters to feet
                            inrix_lines_matched_final.loc[cur_cnt, "INX_B_CMP_B"] = 0
                            inrix_lines_matched_final.loc[cur_cnt, "INX_E_CMP_E"] = (
                                cmp_seg_len - link_e_cmp_b_dis * 3.2808
                            )  # meters to feet
                            break  # link_idx for loop

                    else:
                        cmp_b_point = Point(float(cmp_b_long), float(cmp_b_lat))
                        cmp_b_dis = link_geo.project(
                            cmp_b_point
                        )  # distance from inrix link to cmp begin point
                        cmp_b_link_e_dis = (
                            link_len - cmp_b_dis * 3.2808
                        )  # meters to feet
                        cmp_b_projected = link_geo.interpolate(
                            cmp_b_dis
                        )  # projected cmp begin point on intersecting inrix link
                        projected_len_ratio = cmp_b_link_e_dis / (
                            link_e_cmp_b_dis * 3.2808
                        )  # meters to feet

                        link_degree = (180 / math.pi) * math.atan2(
                            link_e_long - cmp_b_projected.x,
                            link_e_lat - cmp_b_projected.y,
                        )
                        cmp_degree = (180 / math.pi) * math.atan2(
                            link_e_projected.x - cmp_b_long,
                            link_e_projected.y - cmp_b_lat,
                        )
                        link_cmp_angle = abs(cmp_degree - link_degree)
                        if link_cmp_angle > 270:
                            link_cmp_angle = 360 - link_cmp_angle

                        if (projected_len_ratio > len_ratio_thrhd) & (
                            link_cmp_angle < angle_thrhd
                        ):
                            found_b = 1
                            cur_cnt = len(inrix_lines_matched_final)
                            inrix_lines_matched_final.loc[cur_cnt, "SegID"] = (
                                intersect_b.loc[link_idx]["SegID"]
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "PreviousSe"] = (
                                intersect_b.loc[link_idx]["PreviousSe"]
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "NextSegID"] = (
                                intersect_b.loc[link_idx]["NextSegID"]
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "Length_Matched"] = (
                                link_e_cmp_b_dis * 3.2808
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "cmp_segid"] = (
                                cmp_seg_id
                            )
                            inrix_lines_matched_final.loc[cur_cnt, "INRIX_B_Loc"] = 0
                            inrix_lines_matched_final.loc[cur_cnt, "INRIX_E_Loc"] = (
                                link_e_cmp_b_dis * 3.2808
                            )  # meters to feet
                            inrix_lines_matched_final.loc[cur_cnt, "INX_B_CMP_B"] = 0
                            inrix_lines_matched_final.loc[cur_cnt, "INX_E_CMP_E"] = (
                                cmp_seg_len - link_e_cmp_b_dis * 3.2808
                            )  # meters to feet
                            inrix_matched_e_dis = (
                                cmp_seg_len - link_e_cmp_b_dis * 3.2808
                            )
                            nextNode = intersect_b.loc[link_idx]["E_NodeID"]
                            inrix_frc = intersect_b.loc[link_idx]["FRC"]
                            break  # link_idx for loop

                if found_match == 1:
                    cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = (
                        "Found Matching Link for Whole CMP Segment"
                    )
                    continue

                if found_b == 0:
                    cmp_segments.loc[cmp_seg_idx, "CMP_B_Indt"] = (
                        "No Matching Intersecting Link"
                    )
                    continue

                found_next = 0
                found_next_match = 0
                GAP_COUNTER = 0
                while inrix_matched_e_dis / cmp_seg_len > gap_thrhd:
                    GAP_COUNTER += 1
                    if GAP_COUNTER == 50:
                        print("Zero Match Loop")
                        print(
                            "Gap threshold issue: match_ratio= %s, check cmpid= %s"
                            % (
                                round(inrix_matched_e_dis / cmp_seg_len, 3),
                                cmp_seg_id,
                            )
                        )
                        break
                    nextLinks = inrix_lines_intersect[
                        (inrix_lines_intersect["cmp_segid"] == cmp_seg_id)
                        & (inrix_lines_intersect["B_NodeID"] == nextNode)
                    ]
                    if len(nextLinks) == 0:
                        cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = (
                            "Next links not found"
                        )
                        break
                    else:
                        nextLinks_idx = nextLinks.index.tolist()
                        for nextlink_idx in nextLinks_idx:
                            nextlink_geo = nextLinks.loc[nextlink_idx]["geometry"]
                            nextlink_b_lat = nextLinks.loc[nextlink_idx]["B_Lat_left"]
                            nextlink_b_long = nextLinks.loc[nextlink_idx]["B_Long_left"]
                            nextlink_e_lat = nextLinks.loc[nextlink_idx]["E_Lat_left"]
                            nextlink_e_long = nextLinks.loc[nextlink_idx]["E_Long_left"]
                            nextlink_len = (
                                nextLinks.loc[nextlink_idx]["Miles"] * 5280
                            )  # miles to feet

                            if nextlink_geo.within(
                                cmp_seg_buffer
                            ):  # nextlink is within the buffer zone
                                nextlink_b_point = Point(
                                    float(nextlink_b_long), float(nextlink_b_lat)
                                )
                                nextlink_b_dis = cmp_seg_geo.project(nextlink_b_point)
                                nextLinks.loc[nextlink_idx, "INRIX_B_Loc"] = (
                                    nextlink_b_dis * 3.2808
                                )  # meters to feet
                                nextlink_b_projected = cmp_seg_geo.interpolate(
                                    nextlink_b_dis
                                )  # projected nextlink begin point on cmp segment

                                nextlink_e_point = Point(
                                    float(nextlink_e_long), float(nextlink_e_lat)
                                )
                                nextlink_e_dis = cmp_seg_geo.project(nextlink_e_point)
                                nextLinks.loc[nextlink_idx, "INRIX_E_Loc"] = (
                                    nextlink_e_dis * 3.2808
                                )  # meters to feet
                                nextlink_e_projected = cmp_seg_geo.interpolate(
                                    nextlink_e_dis
                                )  # projected nextlink end point on cmp segment

                                nextLinks.loc[nextlink_idx, "INX_B_CMP_B"] = (
                                    nextlink_b_dis * 3.2808
                                )  # meters to feet
                                nextLinks.loc[nextlink_idx, "INX_E_CMP_E"] = (
                                    cmp_seg_len - nextlink_e_dis * 3.2808
                                )  # meters to feet

                                nextlink_b_e_dis = (
                                    nextlink_e_dis - nextlink_b_dis
                                ) * 3.2808  # meters to feet
                                projected_len_ratio = (
                                    abs(nextlink_b_e_dis) / nextlink_len
                                )
                                nextLinks.loc[nextlink_idx, "Proj_Ratio"] = (
                                    projected_len_ratio
                                )

                                nextlink_degree = (180 / math.pi) * math.atan2(
                                    nextlink_e_long - nextlink_b_long,
                                    nextlink_e_lat - nextlink_b_lat,
                                )
                                # Ensure the degree is calculated following the original direction
                                if nextlink_e_dis > nextlink_b_dis:
                                    cmp_degree = (180 / math.pi) * math.atan2(
                                        nextlink_e_projected.x - nextlink_b_projected.x,
                                        nextlink_e_projected.y - nextlink_b_projected.y,
                                    )
                                else:
                                    cmp_degree = (180 / math.pi) * math.atan2(
                                        nextlink_b_projected.x - nextlink_e_projected.x,
                                        nextlink_b_projected.y - nextlink_e_projected.y,
                                    )

                                nextlink_cmp_angle = abs(cmp_degree - nextlink_degree)
                                if nextlink_cmp_angle > 270:
                                    nextlink_cmp_angle = 360 - nextlink_cmp_angle
                                nextLinks.loc[nextlink_idx, "Proj_Angle"] = (
                                    nextlink_cmp_angle
                                )

                                nextlink_frc = nextLinks.loc[nextlink_idx]["FRC"]

                                if (
                                    (projected_len_ratio > len_ratio_thrhd)
                                    & (nextlink_cmp_angle < angle_thrhd)
                                    & (inrix_frc == nextlink_frc)
                                ):
                                    found_next = 1
                                    cur_cnt = len(inrix_lines_matched_final)
                                    inrix_lines_matched_final.loc[cur_cnt, "SegID"] = (
                                        nextLinks.loc[nextlink_idx]["SegID"]
                                    )
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "PreviousSe"
                                    ] = nextLinks.loc[nextlink_idx]["PreviousSe"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "NextSegID"
                                    ] = nextLinks.loc[nextlink_idx]["NextSegID"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "Length_Matched"
                                    ] = nextlink_b_e_dis
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "cmp_segid"
                                    ] = cmp_seg_id
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_B_Loc"
                                    ] = nextlink_b_dis * 3.2808  # meters to feet
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_E_Loc"
                                    ] = nextlink_e_dis * 3.2808  # meters to feet
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_B_CMP_B"
                                    ] = nextlink_b_dis * 3.2808  # meters to feet
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_E_CMP_E"
                                    ] = (
                                        cmp_seg_len - nextlink_e_dis * 3.2808
                                    )  # meters to feet
                                    inrix_matched_e_dis = (
                                        cmp_seg_len - nextlink_e_dis * 3.2808
                                    )
                                    if inrix_matched_e_dis / cmp_seg_len < gap_thrhd:
                                        found_next_match = 1
                                    nextNode = nextLinks.loc[nextlink_idx]["E_NodeID"]
                                    break  # for loop
                                else:
                                    nextLinks.loc[nextlink_idx, "Matching"] = "No"

                            else:  # nextlink is intersecting with buffer zone
                                # nextlink Begin Node is within buffer zone while End Node is outside buffer zone
                                nextlink_b_point = Point(
                                    float(nextlink_b_long), float(nextlink_b_lat)
                                )
                                nextlink_b_dis = cmp_seg_geo.project(nextlink_b_point)
                                nextlink_b_cmp_e_dis = (
                                    cmp_seg_len - nextlink_b_dis * 3.2808
                                )  # distance from nextlink begin point to cmp end point
                                nextLinks.loc[nextlink_idx, "INRIX_B_Loc"] = (
                                    nextlink_b_dis * 3.2808
                                )  # meters to feet
                                nextlink_b_projected = cmp_seg_geo.interpolate(
                                    nextlink_b_dis
                                )  # projected nextlink begin point on cmp segment

                                cmp_e_point = Point(float(cmp_e_long), float(cmp_e_lat))
                                cmp_e_nextlink_b_dis = nextlink_geo.project(
                                    cmp_e_point
                                )  # distance from inrix nextlink begin point to cmp end point
                                cmp_e_projected = nextlink_geo.interpolate(
                                    cmp_e_nextlink_b_dis
                                )  # projected cmp end point on intersecting inrix link

                                projected_len_ratio = min(
                                    cmp_e_nextlink_b_dis
                                    * 3.2808
                                    / nextlink_b_cmp_e_dis,
                                    nextlink_b_cmp_e_dis
                                    / (cmp_e_nextlink_b_dis * 3.2808),
                                )
                                nextLinks.loc[nextlink_idx, "Proj_Ratio"] = (
                                    projected_len_ratio
                                )

                                nextlink_degree = (180 / math.pi) * math.atan2(
                                    cmp_e_projected.x - nextlink_b_long,
                                    cmp_e_projected.y - nextlink_b_lat,
                                )
                                cmp_degree = (180 / math.pi) * math.atan2(
                                    cmp_e_long - nextlink_b_projected.x,
                                    cmp_e_lat - nextlink_b_projected.y,
                                )
                                nextlink_cmp_angle = abs(cmp_degree - nextlink_degree)
                                if nextlink_cmp_angle > 270:
                                    nextlink_cmp_angle = 360 - nextlink_cmp_angle
                                nextLinks.loc[nextlink_idx, "Proj_Angle"] = (
                                    nextlink_cmp_angle
                                )

                                nextlink_frc = nextLinks.loc[nextlink_idx]["FRC"]

                                if (
                                    (projected_len_ratio > len_ratio_thrhd)
                                    & (nextlink_cmp_angle < angle_thrhd)
                                    & (inrix_frc == nextlink_frc)
                                ):
                                    found_next = 1
                                    found_next_match = 1
                                    cur_cnt = len(inrix_lines_matched_final)
                                    inrix_lines_matched_final.loc[cur_cnt, "SegID"] = (
                                        nextLinks.loc[nextlink_idx]["SegID"]
                                    )
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "PreviousSe"
                                    ] = nextLinks.loc[nextlink_idx]["PreviousSe"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "NextSegID"
                                    ] = nextLinks.loc[nextlink_idx]["NextSegID"]
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "Length_Matched"
                                    ] = nextlink_b_cmp_e_dis
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "cmp_segid"
                                    ] = cmp_seg_id
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_B_Loc"
                                    ] = nextlink_b_dis * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INRIX_E_Loc"
                                    ] = cmp_seg_geo.project(cmp_e_projected) * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_B_CMP_B"
                                    ] = nextlink_b_dis * 3.2808
                                    inrix_lines_matched_final.loc[
                                        cur_cnt, "INX_E_CMP_E"
                                    ] = max(
                                        0,
                                        cmp_seg_len
                                        - cmp_seg_geo.project(cmp_e_projected) * 3.2808,
                                    )
                                    inrix_matched_e_dis = max(
                                        0,
                                        cmp_seg_len
                                        - cmp_seg_geo.project(cmp_e_projected) * 3.2808,
                                    )
                                    nextNode = nextLinks.loc[nextlink_idx]["E_NodeID"]
                                    break  # for loop
                                else:
                                    nextLinks.loc[nextlink_idx, "Matching"] = "No"
                        if found_next_match == 1:
                            cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = (
                                "Yes-LinkAdded"
                            )
                        if (
                            found_next == 0
                        ):  # break while loop if no mathcing link found in nextlinks
                            cmp_segments.loc[cmp_seg_idx, "CMP_E_Indt"] = (
                                "No Matching Next Link"
                            )
                            break

    del cmp_segments["Len_Matched"]
    del cmp_segments["Len_Ratio"]

    # Calculate the total length of matched INRIX links
    inrix_matched_length = (
        inrix_lines_matched_final.groupby("cmp_segid")
        .Length_Matched.sum()
        .reset_index()
    )
    inrix_matched_length.columns = ["cmp_segid", "Len_Matched"]
    inrix_matched_length["cmp_segid"] = inrix_matched_length["cmp_segid"].astype(int)

    cmp_segments = cmp_segments.merge(inrix_matched_length, on="cmp_segid", how="left")
    cmp_segments["Len_Ratio"] = np.where(
        pd.isnull(cmp_segments["Len_Matched"]),
        0,
        cmp_segments["Len_Matched"] / cmp_segments["length"],
    )
    cmp_segments["Len_Ratio"] = cmp_segments["Len_Ratio"].round(1)

    inrix_lines_matched_output = inrix_lines_matched_final[
        ["cmp_segid", "SegID", "Length_Matched"]
    ]
    inrix_lines_matched_output.columns = ["CMP_SegID", "INRIX_SegID", "Length_Matched"]

    # Output files
    cmp_segments.to_file(
        output_dir / (output_filename_base + "-matchedlength_check.gpkg")
    )

    inrix_lines_matched_output[["CMP_SegID", "INRIX_SegID"]] = (
        inrix_lines_matched_output[["CMP_SegID", "INRIX_SegID"]].astype(int)
    )

    if config["manual_update"]["manual_update"]:
        cols = inrix_lines_matched_output.columns
        rem_df = pd.read_csv(config["manual_update"]["csv"]["remove"])
        rem_df["del_flag"] = 1
        inrix_lines_matched_output = inrix_lines_matched_output.merge(
            rem_df, how="left"
        )
        inrix_lines_matched_output = inrix_lines_matched_output.loc[
            pd.isna(inrix_lines_matched_output["del_flag"]),
        ]

        add_df = pd.read_csv(config["manual_update"]["csv"]["add"])
        inrix_lines_matched_output = pd.concat(
            (inrix_lines_matched_output[cols], add_df)
        )

    inrix_lines_matched_output.to_csv(output_filepath, index=False)
