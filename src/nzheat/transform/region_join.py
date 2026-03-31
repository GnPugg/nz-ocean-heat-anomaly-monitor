from __future__ import annotations

from pathlib import Path
import argparse

import geopandas as gpd
import pandas as pd
import xarray as xr
from shapely.geometry import Point


DEFAULT_OISST_FILE = Path("data/raw/oisst/oisst_nz_subset_2026-03-01.nc")
DEFAULT_REGIONS_FILE = Path("assets/regions/nz_coastal_regions.geojson")
DEFAULT_OUTPUT_FILE = Path("data/interim/oisst_points_with_regions.parquet")


def load_oisst_as_dataframe(nc_path: Path) -> pd.DataFrame:
    """
    Open one OISST NetCDF file and convert the SST variable into a flat dataframe.

    Expected output columns are roughly:
    - time
    - depth
    - latitude
    - longitude
    - sst
    """
    with xr.open_dataset(nc_path) as ds:
        df = ds["sst"].to_dataframe().reset_index()

    # Remove rows where SST is missing.
    df = df.dropna(subset=["sst"]).copy()

    # Rename columns for cleaner downstream handling.
    df = df.rename(
        columns={
            "latitude": "lat",
            "longitude": "lon",
        }
    )

    # OISST subset is surface-only for this project, so depth is not useful here.
    if "depth" in df.columns:
        df = df.drop(columns=["depth"])

    return df


def make_points_geodataframe(df: pd.DataFrame) -> gpd.GeoDataFrame:
    """Convert the SST dataframe into a GeoDataFrame of point geometries."""
    geometry = [Point(xy) for xy in zip(df["lon"], df["lat"])]
    gdf = gpd.GeoDataFrame(df.copy(), geometry=geometry, crs="EPSG:4326")
    return gdf


def load_regions(regions_path: Path) -> gpd.GeoDataFrame:
    """
    Load the region polygons from GeoJSON.

    The GeoJSON should contain one row per coastal region. Ideally it should include
    columns such as:
    - region_id
    - region_code
    - region_name
    """
    regions = gpd.read_file(regions_path)

    if regions.crs is None:
        regions = regions.set_crs("EPSG:4326")
    else:
        regions = regions.to_crs("EPSG:4326")

    return regions


def spatially_assign_regions(
    points_gdf: gpd.GeoDataFrame,
    regions_gdf: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Spatially join SST grid-cell points to region polygons.

    Uses the 'within' predicate so that each SST point is matched to the polygon
    it falls inside.
    """
    joined = gpd.sjoin(points_gdf, regions_gdf, how="left", predicate="within")
    return joined


def keep_useful_columns(joined_gdf: gpd.GeoDataFrame) -> pd.DataFrame:
    """
    Keep a concise set of columns for the next transformation stage.

    This function is flexible: it keeps core SST columns and preserves common region
    fields when they exist.
    """
    preferred_columns = [
        "time",
        "lat",
        "lon",
        "sst",
        "region_id",
        "region_code",
        "region_name",
        "geometry",
    ]

    available_columns = [col for col in preferred_columns if col in joined_gdf.columns]
    return joined_gdf[available_columns].copy()


def save_output(df: pd.DataFrame, output_path: Path) -> None:
    """Save the joined result to parquet for the next pipeline step."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)


def main(nc_path: Path, regions_path: Path, output_path: Path) -> None:
    print(f"Opening OISST file: {nc_path}")
    sst_df = load_oisst_as_dataframe(nc_path)
    print(f"Loaded {len(sst_df):,} SST rows")

    print("Converting SST rows to spatial points...")
    points_gdf = make_points_geodataframe(sst_df)

    print(f"Loading region polygons: {regions_path}")
    regions_gdf = load_regions(regions_path)
    print(f"Loaded {len(regions_gdf):,} regions")

    print("Assigning SST points to regions...")
    joined_gdf = spatially_assign_regions(points_gdf, regions_gdf)

    result_df = keep_useful_columns(joined_gdf)

    matched_rows = (
        result_df["region_name"].notna().sum()
        if "region_name" in result_df.columns
        else 0
    )
    print(f"Matched {matched_rows:,} SST rows to a region")

    print("Preview:")
    print(result_df.head())

    save_output(result_df, output_path)
    print(f"Saved joined output to: {output_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assign one OISST daily subset of SST grid cells to NZ coastal regions.",
    )
    parser.add_argument(
        "--nc-file",
        default=str(DEFAULT_OISST_FILE),
        help="Path to the downloaded OISST NetCDF subset.",
    )
    parser.add_argument(
        "--regions-file",
        default=str(DEFAULT_REGIONS_FILE),
        help="Path to the GeoJSON file containing NZ coastal regions.",
    )
    parser.add_argument(
        "--output-file",
        default=str(DEFAULT_OUTPUT_FILE),
        help="Where to save the joined point-to-region output as parquet.",
    )
    args = parser.parse_args()

    main(
        nc_path=Path(args.nc_file),
        regions_path=Path(args.regions_file),
        output_path=Path(args.output_file),
    )
