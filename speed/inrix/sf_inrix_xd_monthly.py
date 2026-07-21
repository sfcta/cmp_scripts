import argparse
import json
import tomllib
from pathlib import Path

from core import (
    glob_inrix_xd_zips_directory,
    read_and_process_speed_to_los_and_reliability,
)


def modify_aggregate_config(json_file_path, hourly_file, weekly_file):
    """
    Modify the specified JSON configuration file to include names of the output files
    for aggregation processing. This function updates the configuration file in-place,
    adding entries for the hourly and weekly aggregation output files.

    Args:
        json_file_path (Path): Path to the JSON config file that will be modified.
        hourly_file (str): Name of the file where hourly aggregated data will be saved.
        weekly_file (str): Name of the file where weekly aggregated data will be saved.
    """

    with open(json_file_path, "r") as file:
        config_json = json.load(file)
    if hourly_file not in config_json["hourly_files"]:
        config_json["hourly_files"].append(hourly_file)
        print("Add hourly file into aggregation configuration file")
    else:
        print("Hourly file already added to the aggregation configuration file.")
    if weekly_file not in config_json["weekly_files"]:
        config_json["weekly_files"].append(weekly_file)
        print("Add weekly file into aggregation configuration file")
    else:
        print("Weekly file already added to the aggregation configuration file.")
    with open(json_file_path, "w") as config_file:
        json.dump(config_json, config_file, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("toml_filepath")
    args = parser.parse_args()
    with open(args.toml_filepath, "rb") as f:
        config = tomllib.load(f)

    # sample size thresholds
    peak_min_sample_size_threshold = 10  # AM/PM peak monitoring period
    hourly_min_sample_size_threshold = 10  # Miniumum sample size for hourly
    spatial_coverage_thresholds = [99, 95, 90, 85, 80, 75, 70]
    output_file_stem = Path(config["output"]["version"]) / (
        f"{config['input']['year']}{config['input']['month']}"
        f"_{config['output']['filename_stem']}"
    )

    zip_filepaths = glob_inrix_xd_zips_directory(
        Path(config["input"]["dir"])
        / config["input"]["map-version"]
        / config["input"]["speeds-version"]
        / config["input"]["year"]
        / config["input"]["month"],
        f"*{config['input']['end_date']}*.zip",
    )

    read_and_process_speed_to_los_and_reliability(
        zip_filepaths,
        Path(config["output"]["base_dir"]) / output_file_stem,
        Path(config["geo"]["network_conflation_correspondence_filepath"]),
        Path(config["geo"]["cmp_shp"]),
        spatial_coverage_thresholds,
        config["input"]["year"],
        peak_min_sample_size_threshold,
        monthly_update=True,
        hourly_min_sample_size_threshold=hourly_min_sample_size_threshold,
    )
    weekly_file = str(output_file_stem) + "_AMPM.csv"
    hourly_file = str(output_file_stem) + "_Hourly.csv"
    modify_aggregate_config(
        Path(config["aggregate_config"]["config_dir"])
        / config["aggregate_config"]["config_file"],
        hourly_file,
        weekly_file,
    )
