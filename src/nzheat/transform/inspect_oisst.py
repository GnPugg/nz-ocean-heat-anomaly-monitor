import xarray as xr

file_path = "data/raw/oisst/oisst_nz_subset_2026-03-01.nc"

with xr.open_dataset(file_path) as ds:
    print("\nDATASET:")
    print(ds)

    print("\nVARIABLES:")
    print(ds.data_vars)

    print("\nCOORDINATES:")
    print(ds.coords)

    print("\nSST:")
    print(ds["sst"])

    df = ds["sst"].to_dataframe().reset_index()

    print("\nDATAFRAME PREVIEW:")
    print(df.head())
