from pathlib import Path
import argparse

import xarray as xr


def inspect_oisst(file_path: Path) -> None:
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    with xr.open_dataset(file_path) as ds:
        print("\nDATASET:")
        print(ds)

        print("\nVARIABLES:")
        print(ds.data_vars)

        print("\nCOORDINATES:")
        print(ds.coords)

        if "sst" not in ds:
            raise KeyError("Variable 'sst' was not found in this dataset.")

        print("\nSST:")
        print(ds["sst"])

        print("\nFIRST NON-NULL SST VALUES:")
        sst_df = ds["sst"].to_dataframe().reset_index()
        print(sst_df.dropna(subset=["sst"]).head())

        print("\nNZ-LIKE AREA PREVIEW:")
        nz_sst = ds["sst"].sel(
            lat=slice(-50, -30),
            lon=slice(160, 180),
        )

        nz_df = nz_sst.to_dataframe().reset_index()
        nz_df = nz_df.dropna(subset=["sst"])

        print(nz_df.head())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect a NOAA OISST NetCDF file used by the NZ ocean heat project."
    )

    parser.add_argument(
        "file_path",
        type=Path,
        help="Path to the NetCDF file to inspect.",
    )

    args = parser.parse_args()
    inspect_oisst(args.file_path)


if __name__ == "__main__":
    main()
