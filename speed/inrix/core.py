import os
import re
from pathlib import Path
from pprint import pprint
from zipfile import ZipFile

import geopandas as gpd
import numpy as np
import pandas as pd
import polars as pl


def los_1985(road_class: pl.Expr, speed: pl.Expr):
    """LOS based on 1985 HCM"""
    # fmt: off
    return pl.when(speed.is_null()).then(pl.lit(" ")).otherwise(
        pl.when(road_class == "Fwy").then(  # Freeway
            pl.when(speed >= 60).then(pl.lit("A"))
            .when(speed >= 55).then(pl.lit("B"))
            .when(speed >= 49).then(pl.lit("C"))
            .when(speed >= 41).then(pl.lit("D"))
            .when(speed >= 30).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        ).when(road_class == "1").then(  # Arterial Class I
            pl.when(speed >= 35).then(pl.lit("A"))
            .when(speed >= 28).then(pl.lit("B"))
            .when(speed >= 22).then(pl.lit("C"))
            .when(speed >= 17).then(pl.lit("D"))
            .when(speed >= 13).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        ).when(road_class == "2").then(  # Arterial Class II
            pl.when(speed >= 30).then(pl.lit("A"))
            .when(speed >= 24).then(pl.lit("B"))
            .when(speed >= 18).then(pl.lit("C"))
            .when(speed >= 14).then(pl.lit("D"))
            .when(speed >= 10).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        ).when(road_class == "3").then(  # Arterial Class III
            pl.when(speed >= 25).then(pl.lit("A"))
            .when(speed >= 19).then(pl.lit("B"))
            .when(speed >= 13).then(pl.lit("C"))
            .when(speed >= 9).then(pl.lit("D"))
            .when(speed >= 7).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        )
    )
    # fmt: on


def los_2000(road_class: pl.Expr, speed: pl.Expr):
    """LOS based on 2000 HCM"""
    # fmt: off
    return pl.when(speed.is_null()).then(pl.lit(" ")).otherwise(
        pl.when(road_class == "Fwy").then(  # Freeway
            pl.lit(" ")
        ).when(road_class == "1").then(  # Arterial Class I
            pl.when(speed >= 42).then(pl.lit("A"))
            .when(speed >= 34).then(pl.lit("B"))
            .when(speed >= 27).then(pl.lit("C"))
            .when(speed >= 21).then(pl.lit("D"))
            .when(speed >= 16).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        ).when(road_class == "2").then(  # Arterial Class II
            pl.when(speed >= 35).then(pl.lit("A"))
            .when(speed >= 28).then(pl.lit("B"))
            .when(speed >= 22).then(pl.lit("C"))
            .when(speed >= 17).then(pl.lit("D"))
            .when(speed >= 13).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        ).when(road_class == "3").then(  # Arterial Class III
            pl.when(speed >= 30).then(pl.lit("A"))
            .when(speed >= 24).then(pl.lit("B"))
            .when(speed >= 18).then(pl.lit("C"))
            .when(speed >= 14).then(pl.lit("D"))
            .when(speed >= 10).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        ).when(road_class == "4").then(  # Arterial Class IV
            pl.when(speed >= 25).then(pl.lit("A"))
            .when(speed >= 19).then(pl.lit("B"))
            .when(speed >= 13).then(pl.lit("C"))
            .when(speed >= 9).then(pl.lit("D"))
            .when(speed >= 7).then(pl.lit("E"))
            .when(speed > 0).then(pl.lit("F"))
        )
    )
    # fmt: on


def read_cmp_inrix_conflation(filepath):
    """read CMP-INRIX segment correspondence table"""
    conflation_df = pl.read_csv(
        filepath,
        schema_overrides={
            "INRIX_SegID": pl.UInt64,
            }
        )
    cmp_segment_conflated_length = conflation_df.group_by("CMP_SegID").agg(
        cmp_segment_conflated_length=pl.sum("Length_Matched")
    )
    # TODO cmp_segment_conflated_length should be calculated with the conflation script
    # and just joined directly to the conflation CSV file
    return conflation_df, cmp_segment_conflated_length


def _dirs_in_zip(zip_filepath: str) -> set:
    """directory names in zip file (for parsing zipped INRIX data)"""
    with ZipFile(zip_filepath, "r") as z:
        return set([os.path.dirname(f) for f in z.namelist()])


def _zip_hashdir(zip_filepath: str) -> str:
    """return the only directory name in zip file

    (for parsing zipped INRIX data)
    """
    dirs = _dirs_in_zip(zip_filepath)
    if len(dirs) > 1:
        raise RuntimeError(
            f"Multiple directories found inside {zip_filepath}. There should "
            "only be one directory inside the zip files downloaded from INRIX."
        )
    return next(iter(dirs))  # return the next/only item in dirs


def glob_inrix_xd_zips_directory(directory, glob_pattern):
    """filepaths of files in directory fitting glob_pattern"""
    return sorted(
        Path(directory).glob(glob_pattern),
        # natural sort of part numbers
        key=lambda f: [int(x) for x in re.findall(r"\d+", f.stem)],
    )


def read_inrix_xd_zip(zip_filepath):
    columns = [
        "Date Time",
        "Segment ID",
        "Speed(miles/hour)",
        "Ref Speed(miles/hour)",
    ]
    # these columns aren't used anyways, so no need to specify dtype:
    # dtypes = {
    #     "Hist Av Speed(miles/hour)": pl.Int64,
    #     "CValue": pl.Float64,
    # }
    # fsspec filepath (e.g. for dask):
    # (
    #     f"zip://{_zip_hashdir(zip_filepath)}/data.csv"
    #     "::file://{zip_filepath}"
    # )
    # seems like polars cannot handle reading zip CSVs via fsspec:
    with ZipFile(zip_filepath) as z:
        with z.open(f"{_zip_hashdir(zip_filepath)}/data.csv", mode="r") as f:
            return pl.read_csv(
                f.read(),
                columns=columns,
                schema_overrides={
                    "Date Time": pl.String,
                    "Segment ID": pl.UInt64,
                    "Speed(miles/hour)": pl.UInt8,
                    "Ref Speed(miles/hour)": pl.UInt8,
                },
            )


def read_filtered_inrix_xd_zips(zip_filepaths, inrix_xd_segment_ids_to_keep):
    """
    Read and concatenate INRIX XD zip files


    filtering for XD segments in conflation_df
    """
    print("input zip filepaths:")
    pprint(zip_filepaths)
    input_dfs = []
    for zip_filepath in zip_filepaths:
        print(f"Reading input file {zip_filepath}...")
        input_df = read_inrix_xd_zip(zip_filepath)
        if len(input_df):  # if > 0
            input_df = input_df.filter(
                # only keep INRIX XD segments in conflation_df
                # (i.e. XD segments that actually correspond to a CMP segment)
                pl.col("Segment ID").is_in(inrix_xd_segment_ids_to_keep)
                # remove 0 speed segments
                & (pl.col("Speed(miles/hour)") > 0)
            )
            input_dfs.append(input_df)
    return pl.concat(input_dfs, how="vertical", rechunk=False)


def inrix_to_cmp_reference_speed(inrix_xd_segments_df, conflation_df):
    return (
        # get inrix segments reference speed
        # (per INRIX documentation: reference speed = free flow speed)
        # join INRIX reference (free flow) speed with CMP segment IDs
        # TODO joining is expensive, this shouldn't be done twice
        create_inrix_cmp_segments_mapping(
            (
                inrix_xd_segments_df.select(["Segment ID", "Ref Speed(miles/hour)"])
                .drop_nulls(subset="Ref Speed(miles/hour)")
                .unique()  # TODO shouldn't we groupby("Segment ID") then avg over ref speed instead?
            ),
            conflation_df,
            "inner",
        )
        .with_columns(
            (pl.col("Length_Matched") / pl.col("Ref Speed(miles/hour)")).alias("RefTT"),
        )
        # turn from INRIX to CMP segment IDs as the 'index'
        .group_by("CMP_SegID")
        .agg(pl.sum("Length_Matched"), pl.sum("RefTT"))
        .with_columns(
            (pl.col("Length_Matched") / pl.col("RefTT")).alias("refspd_inrix")
        )
        .rename({"CMP_SegID": "cmp_segid"})
        .select("cmp_segid", "refspd_inrix")
    )


def add_time_fields(inrix_xd_segments_df):
    # Create date and time fields for subsequent filtering
    # TODO change to parse into datetime first and then use datetime directly
    return (
        inrix_xd_segments_df.with_columns(
            pl.col("Date Time")
            .str.slice(0, 16)
            .str.replace("T", " ")
            .alias("Date_Time")
        )
        .with_columns(
            date=pl.col("Date_Time").str.slice(0, 10),
            datetime=pl.col("Date_Time").str.to_datetime(),
        )
        .with_columns(
            pl.col("datetime").dt.weekday().alias("DOW"),  # Tue=2, ..., Thu=4, ...
            pl.col("datetime").dt.hour().alias("Hour"),
            pl.col("datetime").dt.minute().alias("Minute"),
        )
    )


def create_inrix_cmp_segments_mapping(inrix_xd_segments_df, conflation_df, how):
    """attach INRIX speeds to CMP segments via INRIX/CMP Segment ID mapping"""
    # TODO why is this done twice?
    return inrix_xd_segments_df.join(
        conflation_df,
        left_on="Segment ID",
        right_on="INRIX_SegID",
        how=how,
    )


tue_to_thu_filter = (1 < pl.col("DOW")) & (pl.col("DOW") < 5)  # Tue, Wed, Thu
weekday_filter = pl.col("DOW") <= 5  # Mon-Fri
am_filter = (pl.col("Hour") == 7) | (pl.col("Hour") == 8)  # 7-9am
pm_filter = (  # 4:30-6:30pm
    ((pl.col("Hour") == 16) & (pl.col("Minute") >= 30))
    | (pl.col("Hour") == 17)
    | ((pl.col("Hour") == 18) & (pl.col("Minute") < 30))
)


def hour_filter(hour):
    return pl.col("Hour") == hour


def create_periods_tuples(
    monthly_update: bool,
    peak_min_sample_size: int,
    hourly_min_sample_size: int = None,
):
    """_summary_

    Parameters
    ----------
    monthly_update : bool
        whether this is for the CMP biennial report or
        the monthly congestion Prospector visualization update
    peak_min_sample_size : int
        _description_
    hourly_min_sample_size : int, optional
        only required if monthly_update=True, by default None

    Returns
    -------
    _type_
        _description_
    """
    peak_periods_filters = [
        ("AM", am_filter, peak_min_sample_size),
        ("PM", pm_filter, peak_min_sample_size),
    ]
    if monthly_update:
        if hourly_min_sample_size is None:
            raise RuntimeError("Monthly updates require hourly_min_sample_size.")
        hour_periods_tuples = [
            (str(hour), hour_filter(hour), hourly_min_sample_size) for hour in range(24)
        ]
        return hour_periods_tuples + peak_periods_filters
    else:
        return peak_periods_filters


def percentile(n):
    # TODO replace with pl.quantile
    def percentile_(x):
        return np.percentile(x, n)

    percentile_.__name__ = "percentile_%s" % n
    return percentile_


def _spatial_coverage(
    df,
    cmp_period_agg,
    group_cols,
    min_sample_size_threshold,
    coverage_threshold,
    monthly=False,  # for the monthly (AKA realtime) update
):
    """CMP segment level average speeds and LOS"""
    # TODO remove the monthly vs 2-year cycle discrepancy if not needed
    # TODO replacing column names with a list of column names like this is bad
    #      practice; use a dict so you know what you're renaming from/to instead
    # TODO unify the sample size (and other?) calculations with calculate_sample_size()
    #      in sample_size_analysis.py
    if monthly:
        speed_groupby_aggs = ["std", percentile(5), percentile(20)]
        sample_size_col_name = "sample_size"
        rename_cols = [
            "cmp_segid",  # from group_cols, renamed from "CMP_SegID"
            "date",  # from group_cols, renamed from "Date"
            sample_size_col_name,  # from count(travel_time) in the groupby-agg
            "travel_time",  # from sum(travel_time) in the groupby-agg
            "Len",
            "std_speed",
            "pcnt5th",
            "pcnt20th",
        ]
    else:  # biennial report
        speed_groupby_aggs = "std"
        sample_size_col_name = "sample_size_los"
        rename_cols = [
            "cmp_segid",  # from group_cols, renamed from "CMP_SegID"
            sample_size_col_name,  # from count(travel_time) in the groupby-agg
            "travel_time",  # from sum(travel_time) in the groupby-agg
            "Len",
            "std_speed",
        ]

    # select the segment IDs that are not in cmp_period_agg yet (i.e. not
    # covered by all the previous coverage thresholds yet), but that are covered
    # under the current coverage threshold
    if cmp_period_agg is not None:
        select = (~df["CMP_SegID"].isin(cmp_period_agg["cmp_segid"])) & (
            df["spatial_coverage"] >= coverage_threshold
        )
    else:
        select = df["spatial_coverage"] >= coverage_threshold
    if select.sum() > 0:
        cmp_tt_agg = (
            df[select]
            .groupby(group_cols)
            .agg(
                {
                    "travel_time": ["count", "sum"],
                    "Length_Matched": "sum",
                    "Speed": speed_groupby_aggs,
                }
            )
            .reset_index()
        )
        cmp_tt_agg.columns = rename_cols  # flattens the columnar MultiIndex too
        cmp_tt_agg["avg_speed"] = round(
            cmp_tt_agg["Len"] / cmp_tt_agg["travel_time"], 3
        )
        cmp_tt_agg["cov"] = round(
            100 * cmp_tt_agg["std_speed"] / cmp_tt_agg["avg_speed"], 3
        )
        cmp_tt_agg = cmp_tt_agg[
            cmp_tt_agg[sample_size_col_name] >= min_sample_size_threshold
        ]

        if len(cmp_tt_agg) > 0:
            cmp_tt_agg["comment"] = (
                "LOS calculation performed on "
                f"{str(coverage_threshold)}% or greater of length"
            )
            return cmp_tt_agg
        else:
            # basically a maybe monad; better to return an empty DataFrame?
            return None
    else:
        # basically a maybe monad; better to return an empty DataFrame?
        return None


def spatial_coverages(
    coverage_thresholds,
    cmp_period,
    group_cols,
    min_sample_size_threshold,
    monthly=False,
):
    cmp_period_agg = None
    for coverage_threshold in coverage_thresholds:
        coverage = _spatial_coverage(
            cmp_period,
            cmp_period_agg,
            group_cols,
            min_sample_size_threshold,
            coverage_threshold,
            monthly=monthly,
        )
        if coverage is not None:
            cmp_period_agg = pd.concat((cmp_period_agg, coverage), ignore_index=True)
    return cmp_period_agg


def process_inrix_xd_data(
    zip_filepaths,
    network_conflation_correspondence_filepath,
    monthly_update: bool,
):
    """_summary_

    Parameters
    ----------
    zip_filepaths : _type_
        _description_
    network_conflation_correspondence_filepath : _type_
        CMP-INRIX network conflation correspondence CSV filepath
    monthly_update : bool, optional
        whether this is for the CMP biennial report or
        the monthly congestion Prospector visualization update
        The only differences are:
          - the CMP biennial report only retains data from Tue-Thu, whereas the
            monthly updates keep data from all weekdays (Mon-Fri)

    Returns
    -------
    _type_
        _description_
    """
    # Get CMP and INRIX correspondence table
    conflation_df, cmp_segment_conflated_length = read_cmp_inrix_conflation(
        network_conflation_correspondence_filepath
    )
    inrix_xd_segments_df = read_filtered_inrix_xd_zips(
        zip_filepaths, conflation_df["INRIX_SegID"]
    )
    cmp_segments_reference_speed_df = inrix_to_cmp_reference_speed(
        inrix_xd_segments_df, conflation_df
    )
    # TODO cmp/inrix mapping should only be done once
    day_of_week_filter = weekday_filter if monthly_update else tue_to_thu_filter
    inrix_xd_segments_df = create_inrix_cmp_segments_mapping(
        (add_time_fields(inrix_xd_segments_df).filter(day_of_week_filter)),
        conflation_df,
        "outer",
    )
    return (
        inrix_xd_segments_df,
        cmp_segment_conflated_length,
        cmp_segments_reference_speed_df,
    )


def cmp_segments_datetime_speed_from_inrix(
    inrix_xd_segments_df, cmp_segment_conflated_length
):
    """total travel time at a particular date_time on a CMP segment"""
    return (
        inrix_xd_segments_df.with_columns(
            (pl.col("Length_Matched") / pl.col("Speed(miles/hour)")).alias(
                "travel_time"
            )
        )
        .group_by(["CMP_SegID", "date", "datetime"])
        .agg(pl.sum("Length_Matched"), pl.sum("travel_time"))
        .join(cmp_segment_conflated_length, on="CMP_SegID", how="left")
        .with_columns(
            Speed=(pl.col("Length_Matched") / pl.col("travel_time")),
            spatial_coverage=(
                100 * pl.col("Length_Matched") / pl.col("cmp_segment_conflated_length")
            ),
        )
    )


def cmp_seg_level_speed_and_los_monthly(
    cmp_segments_gdf,
    cmp_segment_conflated_length,
    inrix_xd_segments_df,
    spatial_coverage_thresholds,
    ss_threshold,
    year,
    period,
):
    """
    Calculate CMP segment level average speeds, LOS, and reliability metrics
    """
    groupby_cols = ["CMP_SegID", "date"]

    cmp_period = cmp_segments_datetime_speed_from_inrix(
        inrix_xd_segments_df, cmp_segment_conflated_length
    )
    return (
        pl.from_pandas(
            spatial_coverages(
                spatial_coverage_thresholds,
                cmp_period.to_pandas(),
                groupby_cols,
                ss_threshold,
                monthly=True,
            ),
            schema_overrides={"cmp_segid": pl.Int64},  # cast for joining later
        )
        .with_columns(
            pl.lit(period).alias("period"),
            pl.lit("INRIX").alias("source"),
        )
        .with_columns(pl.lit(year).alias("year"))
        .join(
            pl.from_pandas(cmp_segments_gdf[["cmp_segid", "cls_hcm85", "cls_hcm00"]]),
            on="cmp_segid",
            how="left",
        )
        .with_columns(
            los_1985(pl.col("cls_hcm85"), pl.col("avg_speed")).alias("los_hcm85"),
            los_2000(pl.col("cls_hcm00"), pl.col("avg_speed")).alias("los_hcm00"),
        )
        .select(
            "cmp_segid",
            "year",
            "date",
            "period",
            "avg_speed",
            "los_hcm85",
            "los_hcm00",
            "std_speed",
            "pcnt5th",
            "pcnt20th",
            "cov",
            "sample_size",
            "comment",
        )
        .with_columns(pl.lit("INRIX").alias("source"))
    )


def cmp_seg_level_speed_and_los_biennial(
    cmp_segments_gdf,
    cmp_segment_conflated_length,
    inrix_xd_segments_df,
    spatial_coverage_thresholds,
    ss_threshold,
    year,
    period,
    reliability_spatial_coverage_threshold,
    floating_car_run_speeds,
):
    """
    Calculate CMP segment level average speeds, LOS, and reliability metrics
    """
    groupby_cols = ["CMP_SegID"]

    cmp_period = cmp_segments_datetime_speed_from_inrix(
        inrix_xd_segments_df, cmp_segment_conflated_length
    )

    # Use minimum 70% spatial coverage for reliability metric calculation
    cmp_period_r = (
        cmp_period.filter(
            pl.col("spatial_coverage") >= reliability_spatial_coverage_threshold
        )
        .group_by(groupby_cols)
        .agg(
            pl.count("Speed").alias("sample_size_rel"),
            pl.quantile("Speed", 0.05, interpolation="linear").alias("pcnt5th"),
            pl.quantile("Speed", 0.2, interpolation="linear").alias("pcnt20th"),
            pl.quantile("Speed", 0.5, interpolation="linear").alias("pcnt50th"),
        )
        .rename({"CMP_SegID": "cmp_segid"})
        .filter(pl.col("sample_size_rel") >= ss_threshold)
    )

    # Calculate avg and std of speeds based on different spatial coverage requirements
    inrix_df = pl.from_pandas(
        spatial_coverages(
            spatial_coverage_thresholds,
            cmp_period.to_pandas(),
            groupby_cols,
            ss_threshold,
            monthly=False,
        ),
        schema_overrides={"cmp_segid": pl.Int64},  # cast for joining later
    ).with_columns(
        pl.lit(period).alias("period"),
        pl.lit("INRIX").alias("source"),
    )

    # for data not available from inrix, get from floating car runs
    inrix_missing_cmp_segment_ids = cmp_segments_gdf[
        ~cmp_segments_gdf["cmp_segid"].isin(inrix_df["cmp_segid"])
    ]["cmp_segid"]
    floating_car_run_df = process_floating_car_run_speeds(
        floating_car_run_speeds, inrix_missing_cmp_segment_ids, year, period
    )

    # Append floating car run segments
    return (
        pl.concat(
            (inrix_df, floating_car_run_df),
            how="diagonal",  # not vertical, as columns are different
            rechunk=False,
        )
        .with_columns(pl.lit(year).alias("year"))
        .join(
            pl.from_pandas(cmp_segments_gdf[["cmp_segid", "cls_hcm85", "cls_hcm00"]]),
            on="cmp_segid",
            how="left",
        )
        .with_columns(
            los_1985(pl.col("cls_hcm85"), pl.col("avg_speed")).alias("los_hcm85"),
            los_2000(pl.col("cls_hcm00"), pl.col("avg_speed")).alias("los_hcm00"),
        )
        .join(cmp_period_r, on="cmp_segid", how="left")
        .select(
            "cmp_segid",
            "year",
            "source",
            "period",
            "avg_speed",
            "los_hcm85",
            "los_hcm00",
            "sample_size_los",
            "comment",
            "std_speed",
            "cov",
            "pcnt5th",
            "pcnt20th",
            "pcnt50th",
            "sample_size_rel",
        )
    )


def calculate_segments_speed_and_los(
    cmp_segments_gdf,
    cmp_segment_conflated_length,
    inrix_xd_segments_df,
    spatial_coverage_thresholds,
    year,
    peak_min_sample_size_threshold,
    monthly_update,
    hourly_min_sample_size_threshold=None,
    reliability_spatial_coverage_threshold=None,
    fcr_avg_spds=None,
):
    segments_dfs = []
    # TODO update to: add period column, then do calculations over the rows of each
    # period, then no need to concat back together.
    # After that we can continue with the groupbys (including the period now)
    # (see sample_size_analysis.py)
    for (
        period,
        period_filter,
        min_sample_size_threshold,
    ) in create_periods_tuples(
        monthly_update,
        peak_min_sample_size_threshold,
        hourly_min_sample_size_threshold,
    ):
        if monthly_update:
            segments_dfs.append(
                cmp_seg_level_speed_and_los_monthly(
                    cmp_segments_gdf,
                    cmp_segment_conflated_length,
                    inrix_xd_segments_df.filter(period_filter),
                    spatial_coverage_thresholds,
                    min_sample_size_threshold,
                    year,
                    period,
                )
            )
        else:
            segments_dfs.append(
                cmp_seg_level_speed_and_los_biennial(
                    cmp_segments_gdf,
                    cmp_segment_conflated_length,
                    inrix_xd_segments_df.filter(period_filter),
                    spatial_coverage_thresholds,
                    min_sample_size_threshold,
                    year,
                    period,
                    reliability_spatial_coverage_threshold,
                    fcr_avg_spds,
                )
            )
    print("Finished processing all periods.")
    return pl.concat(segments_dfs, how="vertical")


def process_floating_car_run_speeds(speeds_df, cmp_segment_ids_to_use, year, period):
    return (
        speeds_df.filter(
            (pl.col("period") == period)
            & pl.col("cmp_segid").is_in(cmp_segment_ids_to_use)
        )
        .with_columns(
            pl.lit(year).alias("year"),
            pl.lit("Floating Car").alias("source"),
        )
        .select(
            "cmp_segid",
            "year",
            "source",
            "period",
            "avg_speed",
            "std_speed",
            "sample_size",
        )
        # I guess to contrast with sample_size_rel?:
        .rename({"sample_size": "sample_size_los"})
    )


def calculate_reliability_metrics(
    segments_df, cmp_segments_reference_speed_df, monthly_update
):
    # TODO or just do this on just INRIX data before merging with
    # floating car data, then we can skip the when_inrix and otherwise(None)
    when_inrix = pl.when(pl.col("source") == "INRIX")
    segments_df = segments_df.join(
        cmp_segments_reference_speed_df,
        on="cmp_segid",
        how="left",
    ).with_columns(
        when_inrix.then(
            pl.max_horizontal(pl.lit(1), (pl.col("refspd_inrix") / pl.col("pcnt5th")))
        )
        .otherwise(None)
        .alias("tti95"),
        when_inrix.then(
            pl.max_horizontal(pl.lit(1), (pl.col("refspd_inrix") / pl.col("pcnt20th")))
        )
        .otherwise(None)
        .alias("tti80"),
        when_inrix.then(
            pl.max_horizontal(pl.lit(0), (pl.col("avg_speed") / pl.col("pcnt5th") - 1))
        )
        .otherwise(None)
        .alias("bi"),
    )
    if monthly_update:
        return segments_df
    else:
        return segments_df.with_columns(
            when_inrix.then(
                pl.max_horizontal(pl.lit(1), (pl.col("pcnt50th") / pl.col("pcnt20th")))
            )
            .otherwise(None)
            .alias("lottr")
        )


def write_csv(segments_df, filepath_stem, separate_periods):
    if separate_periods:
        # AM/PM peak
        segments_df.filter(pl.col("period").is_in(["AM", "PM"])).write_csv(
            f"{filepath_stem}_AMPM.csv"
        )
        # hourly
        segments_df.filter(~pl.col("period").is_in(["AM", "PM"])).rename(
            {"period": "hour"}
        ).write_csv(f"{filepath_stem}_Hourly.csv")
    else:
        segments_df.write_csv(f"{filepath_stem}.csv")


def read_and_process_speed_to_los_and_reliability(
    zip_filepaths,
    output_filepath_stem,
    network_conflation_correspondence_filepath,
    cmp_segments_gis_filepath,
    spatial_coverage_thresholds,
    year,
    peak_min_sample_size_threshold,
    monthly_update,
    floating_car_run_speeds_filepath=None,
    hourly_min_sample_size_threshold=None,
    reliability_spatial_coverage_threshold=None,
):
    (
        inrix_xd_segments_df,
        cmp_segment_conflated_length,
        cmp_segments_reference_speed_df,
    ) = process_inrix_xd_data(
        zip_filepaths,
        network_conflation_correspondence_filepath,
        monthly_update,
    )
    cmp_segments_gdf = gpd.read_file(cmp_segments_gis_filepath)

    if floating_car_run_speeds_filepath:
        # floating car run average speed
        floating_car_run_speeds = pl.read_csv(floating_car_run_speeds_filepath)
    else:
        floating_car_run_speeds = None

    print("Processing hourly & AM/PM periods...")
    write_csv(
        calculate_reliability_metrics(
            calculate_segments_speed_and_los(
                cmp_segments_gdf,
                cmp_segment_conflated_length,
                inrix_xd_segments_df,
                spatial_coverage_thresholds,
                year,
                peak_min_sample_size_threshold,
                monthly_update=monthly_update,
                hourly_min_sample_size_threshold=hourly_min_sample_size_threshold,
                reliability_spatial_coverage_threshold=reliability_spatial_coverage_threshold,
                fcr_avg_spds=floating_car_run_speeds,
            ),
            cmp_segments_reference_speed_df,
            monthly_update=monthly_update,
        ),
        output_filepath_stem,
        separate_periods=monthly_update,  # separate if monthly_update
    )
