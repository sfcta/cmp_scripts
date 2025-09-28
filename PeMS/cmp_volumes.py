import datetime as dt
import os
import sys
import holidays
import numpy as np
import pandas as pd
from pathlib import Path
import argparse
import re

try:
    import tomllib as toml   # Python 3.11+
except ImportError:
    import toml


def get_dir(base, year=2023, data_type="station_5min", district=4):
    if data_type in ["station_hour", "station_5min", "station_meta"]:
        return os.path.join(base, "D{}_Data_{}/{}".format(district, year, data_type))


def get_columns(data_type, num_cols):
    if data_type == "station_meta":
        columns = [
            "station",
            "route",
            "dir",
            "district",
            "county",
            "city",
            "state_postmile",
            "abs_postmile",
            "latitude",
            "longitude",
            "length",
            "type",
            "lanes",
            "name",
            "user_id_1",
            "user_id_2",
            "user_id_3",
            "user_id_4",
        ]
    if data_type == "station_hour":
        columns = [
            "timestamp",
            "station",
            "district",
            "route",
            "dir",
            "lane_type",
            "station_length",
            "samples",
            "obs_pct",
            "total_flow",
            "avg_occupancy",
            "avg_speed",
            "delay_35",
            "delay_40",
            "delay_45",
            "delay_50",
            "delay_55",
            "delay_60",
        ]
        for i in range(0, int((num_cols - 18) / 3)):
            columns += [
                f"lane_{i}_flow",
                f"lane_{i}_avg_occ",
                f"lane_{i}_avg_speed",
            ]
    if data_type == "station_5min":
        columns = [
            "timestamp",
            "station",
            "district",
            "route",
            "dir",
            "lane_type",
            "station_length",
            "samples",
            "obs_pct",
            "total_flow",
            "avg_occupancy",
            "avg_speed",
        ]
        for i in range(0, int((num_cols - 12) / 5)):
            columns += [
                f"lane_{i}_samples",
                f"lane_{i}_flow",
                f"lane_{i}_avg_occ",
                f"lane_{i}_avg_speed",
                f"lane_{i}_avg_obs",
            ]
    return columns


def parse_args():
    p = argparse.ArgumentParser(
        description="Process PeMS volumes with a TOML config."
    )
    p.add_argument(
        "config",
        nargs="?", 
        help="Path to the TOML config file",
        default=os.path.join(os.path.dirname(__file__), "config.toml")
    )
    return p.parse_args()



if __name__ == "__main__":
    # 1) parse command‐line and load cfg
    args = parse_args()
    cfg_path = args.config

    with open(cfg_path, "rb") as f:
        cfg = toml.load(f)

    # 2) re-bind your key variables from the TOML
    YEAR    = cfg["processing"]["YEAR"]
    PEMSDIR = cfg["paths"]["PEMSDIR"]
    OUTDIR_TPL  = cfg["paths"]["OUTDIR"]
    save_h5     = cfg["processing"].get("save_h5", False)

    # If you have other values in your TOML (like file names), pull those too:
    META_FILE = cfg["files"]["stations_meta_file"]
    monitor_loc = cfg["files"]["monitor_meta_file"]
    OUT_CSV_TPL   = cfg["output"]["df_out_meta_file"]

    # 3) create variables and directories based on the cfg values
    meta_station_path = (Path(PEMSDIR) / META_FILE)
    stations = pd.read_csv(meta_station_path, delimiter="\t")

    # monitor location dataframe
    df_monitor = pd.read_csv(monitor_loc)

    # PeMS stations in SF
    sf_stations = stations[stations["County"] == 75]

    data_type = cfg["processing"]["data_type"]
    district = 4
    ca_holidays = holidays.UnitedStates(state="CA")
    # remove imputed data below the percentage requirements
    obs_pct_min = 20  # Minimum observation percentage requirement
    sample_pct_min = 50  # Minimum sample percentage requirement

    unzip = False
    source = "gz"  # or 'zip','text','txt'
    sep = ","

    for YEAR in ([YEAR] if isinstance(YEAR, int) else list(YEAR)):
        OUTDIR = Path(OUTDIR_TPL.format(YEAR=YEAR))
        os.makedirs(OUTDIR, exist_ok=True)
        
        OUT_CSV = OUT_CSV_TPL.format(YEAR=YEAR)
        
        year_dfs = []
        path = get_dir(PEMSDIR, YEAR, data_type, district)
        contents = os.listdir(path)
        
        if source == "gz":
            # 1) pick out only the .gz files
            gz_files = [f for f in contents if f.endswith(".gz")]
            # 2) build a regex that matches "_<YEAR>_04_<DD>.txt.gz" or "_<YEAR>_05_<DD>.txt.gz"
            month_re = re.compile(rf"_{YEAR:04d}_(0[45])_\d{{2}}\.txt\.gz$")
            # 3) filter them
            files = [f for f in gz_files if month_re.search(f)]
            compression = "gzip"
        else:
            # pick plain .txt files (no date filtering)
            files = [f for f in contents if f.endswith(".txt")]
            compression = None
    
        header = 0 if data_type == "station_meta" else None

        for f in files:
            print(f)
            try:
                df = pd.read_csv(
                    os.path.join(path, f),
                    sep=sep,
                    header=header,
                    index_col=False,
                    parse_dates=[0],
                    compression=compression,
                )
            except Exception as e:
                print(e)
                print("trying no quotechar...")
                try:
                    df = pd.read_csv(
                        os.path.join(path, f),
                        sep=sep,
                        header=header,
                        index_col=False,
                        parse_dates=[0],
                        quotechar=None,
                        compression=compression,
                    )

                except Exception as e2:
                    print(e2)
                    continue

            try:
                df.columns = get_columns(data_type, len(df.columns))
            except Exception as e3:
                print(e3)
                continue
            if data_type == "station_meta":
                y, m, d = (
                    f.replace("d{:02d}_text_meta_".format(district), "")
                    .replace(".txt", "")
                    .split("_")
                )
                ts = dt.datetime(int(y), int(m), int(d))
                date = ts.date()
                df["timestamp"] = ts
                df["date"] = date
                df["year"] = y
                df["month"] = m
                df["day"] = d
                meta.append(df)
            elif data_type == "station_hour":
                df["date"] = df["timestamp"].map(lambda x: x.date())
                df["year"] = df["timestamp"].map(lambda x: x.year)
                df["month"] = df["timestamp"].map(lambda x: x.month)
                df["day"] = df["timestamp"].map(lambda x: x.day)
                df["hour"] = df["timestamp"].map(lambda x: x.hour)
                df["day_of_week"] = df["timestamp"].map(lambda x: x.weekday())
                df["is_holiday"] = df["timestamp"].map(
                    lambda x: x.date() in ca_holidays
                )
                year_dfs.append(df)
            elif data_type == "station_5min":
                df["date"] = df["timestamp"].map(lambda x: x.date())
                df["year"] = df["timestamp"].map(lambda x: x.year)
                df["month"] = df["timestamp"].map(lambda x: x.month)
                df["day"] = df["timestamp"].map(lambda x: x.day)
                df["hour"] = df["timestamp"].map(lambda x: x.hour)
                df["minute"] = df["timestamp"].map(lambda x: x.minute)
                df["day_of_week"] = df["timestamp"].map(lambda x: x.weekday())
                df["is_holiday"] = df["timestamp"].map(
                    lambda x: x.date() in ca_holidays
                )
                year_dfs.append(df)

        y = pd.concat(year_dfs)
        if save_h5:
            print("HDF writing...")
            try:
                y.to_hdf(
                    os.path.join(OUTDIR, "pems_station_5min_{}.h5".format(YEAR)), "data", mode = "w"
                )
            except Exception as e:
                print("HDF write failed:", e)

    # PeMS counts in SF
    sf_counts = y[y["station"].isin(sf_stations["ID"])].copy()
    # Get half hour period
    sf_counts["halfhour"] = np.where(sf_counts["minute"] < 30, 0, 30)
    # Aggregate from 5-min to half hour
    grpby_cols = ["station", "date", "hour", "halfhour"]
    sf_counts_halfhr = (
        sf_counts.groupby(grpby_cols)
        .agg(
            {
                "total_flow": "sum",
                "samples": "sum",
                "obs_pct": "sum",
                "timestamp": "count",
            }
        )
        .reset_index()
    )
    sf_counts_halfhr.columns = grpby_cols + [
        "total_flow",
        "samples",
        "total_obspct",
        "numofintervals",
    ]
    sf_counts_halfhr["obs_pct"] = sf_counts_halfhr["total_obspct"] / 6
    sf_counts_halfhr["total_flow"] = (
        6 * sf_counts_halfhr["total_flow"] / sf_counts_halfhr["numofintervals"]
    )
    sf_counts_halfhr = sf_counts_halfhr.merge(
        sf_stations[["ID", "Lanes"]], left_on="station", right_on="ID", how="left"
    )
    sf_counts_halfhr["sample_pct"] = (
        100 * sf_counts_halfhr["samples"] / sf_counts_halfhr["Lanes"] / 30 / 2
    )
    sf_counts_halfhr["day_of_week"] = sf_counts_halfhr["date"].map(
        lambda x: x.weekday()
    )
    sf_counts_halfhr["daytype"] = np.where(
        sf_counts_halfhr["day_of_week"] <= 4,
        "Weekdays",
        np.where(sf_counts_halfhr["day_of_week"] == 5, "Saturday", "Sunday"),
    )
    sf_counts_halfhr["is_holiday"] = sf_counts_halfhr["date"].map(
        lambda x: x in ca_holidays
    )

    # Aggregate volumes from individual days to typical day of week
    groupby_cols = ["station", "daytype", "hour", "halfhour"]
    agg_args = {"total_flow": ["mean", "count", "std"]}

    df_counts = sf_counts_halfhr.loc[
        (sf_counts_halfhr["day_of_week"] != 0)
        & (sf_counts_halfhr["day_of_week"] != 4)
        & ~sf_counts_halfhr["is_holiday"]
    ]

    df_agg = (
        df_counts.loc[
            (df_counts["obs_pct"] >= obs_pct_min)
            & (df_counts["sample_pct"] >= sample_pct_min)
        ]
        .groupby(groupby_cols)
        .agg(agg_args)
        .reset_index()
    )
    df_agg.columns = groupby_cols + ["flow_avg", "flow_count", "flow_std"]

    # Aggregate from individual stations to monitoring locations
    df_agg = df_agg.merge(df_monitor, on="station")
    df_out = (
        df_agg.groupby(["loc_id", "daytype", "hour", "halfhour"])
        .flow_avg.mean()
        .reset_index()
    )
    df_out.columns = ["loc_id", "daytype", "hour", "halfhour", "flow_avg"]
    df_out["flow_avg"] = df_out["flow_avg"].round()
    df_out.to_csv(os.path.join(OUTDIR, OUT_CSV), index=False, encoding = "utf-8")
