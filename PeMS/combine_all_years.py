from os.path import join

import pandas as pd

BASE_DIR = r"Q:\CMP\LOS Monitoring 2023\PeMS"

YEAR_LIST = ["2019", "2020", "2021", "2023"]  # 2022 to be added

out_df = pd.DataFrame()
out_list = []

for yr in YEAR_LIST:
    df = pd.read_csv(join(BASE_DIR, "cmp%s_pems_volumes.csv" % yr))
    df["year"] = yr
    df["timep"] = "Other"
    df.loc[(df["hour"] >= 7) & (df["hour"] < 9), "timep"] = "AM"
    df.loc[
        ((df["hour"] == 16) & (df["halfhour"] == 30))
        | (df["hour"] == 17)
        | ((df["hour"] == 18) & (df["halfhour"] == 0)),
        "timep",
    ] = "PM"
    out_list.append(df)
    print(f"{yr} is combined")

out_df = pd.concat(out_list)

out_df.to_csv(join(BASE_DIR, "cmp_pems_volumes_all.csv"), index=False)
out_df.to_csv(join(BASE_DIR, "cmp_pems_volumes_all.csv"), index=False)
