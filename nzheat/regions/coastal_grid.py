from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from nzheat.utils.paths import find_project_root

GRID_SPACING_DEGREES = 0.25
GRID_CENTRE_OFFSET_DEGREES = 0.125
NZTM_CRS = "EPSG:2193"
WGS84_CRS = "EPSG:4326"


@dataclass(frozen=True)
class CoastalGridConfig:
    min_lon: float = 164.0
    max_lon: float = 180.0
    min_lat: float = -48.5
    max_lat: float = -33.0
    max_distance_km: float = 100.0


def aligned_oisst_centres(min_value: float, max_value: float) -> np.ndarray:
    """Return OISST 0.25-degree grid centres within [min_value, max_value)."""
    first_index = int(
        np.ceil(
            (min_value - GRID_CENTRE_OFFSET_DEGREES)
            / GRID_SPACING_DEGREES
        )
    )
    last_index = int(
        np.floor(
            (
                (max_value - np.finfo(float).eps)
                - GRID_CENTRE_OFFSET_DEGREES
            )
            / GRID_SPACING_DEGREES
        )
    )
    indices = np.arange(first_index, last_index + 1)
    return GRID_CENTRE_OFFSET_DEGREES + GRID_SPACING_DEGREES * indices


def build_oisst_grid(config: CoastalGridConfig) -> gpd.GeoDataFrame:
    """Create candidate OISST grid-cell centres around mainland New Zealand."""
    longitudes = aligned_oisst_centres(config.min_lon, config.max_lon)
    latitudes = aligned_oisst_centres(config.min_lat, config.max_lat)

    lon_mesh, lat_mesh = np.meshgrid(longitudes, latitudes)
    frame = pd.DataFrame(
        {
            "longitude": lon_mesh.ravel(),
            "latitude": lat_mesh.ravel(),
        }
    )
    frame["cell_id"] = frame.apply(
        lambda row: f"oisst_{row['longitude']:.3f}_{row['latitude']:.3f}",
        axis=1,
    )

    return gpd.GeoDataFrame(
        frame,
        geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]),
        crs=WGS84_CRS,
    )


def load_mainland_nz_land(
    coastline_path: Path,
    config: CoastalGridConfig,
) -> gpd.GeoDataFrame:
    """Load coastline polygons within the mainland-NZ design extent."""
    if not coastline_path.exists():
        raise FileNotFoundError(f"Coastline file not found: {coastline_path}")

    land = gpd.read_file(coastline_path)
    if land.empty:
        raise ValueError(f"Coastline file contains no features: {coastline_path}")
    if land.crs is None:
        raise ValueError("Coastline dataset has no CRS; refusing to guess.")

    land = land.to_crs(WGS84_CRS)
    study_extent = box(
        config.min_lon,
        config.min_lat,
        config.max_lon,
        config.max_lat,
    )
    land = land.loc[land.geometry.intersects(study_extent)].copy()
    land["geometry"] = land.geometry.intersection(study_extent)
    land = land.loc[~land.geometry.is_empty].copy()

    invalid_count = int((~land.geometry.is_valid).sum())
    if invalid_count:
        raise ValueError(
            f"Coastline subset contains {invalid_count} invalid geometries; "
            "repair the source explicitly before building the grid."
        )

    return land


def classify_coastal_cells(
    grid: gpd.GeoDataFrame,
    land: gpd.GeoDataFrame,
    max_distance_km: float,
) -> gpd.GeoDataFrame:
    """Classify grid centres as land, offshore, or included coastal-ocean cells."""
    if max_distance_km <= 0:
        raise ValueError("max_distance_km must be positive.")

    grid_projected = grid.to_crs(NZTM_CRS)
    land_projected = land.to_crs(NZTM_CRS)
    land_union = land_projected.geometry.union_all()

    result = grid.copy()
    result["is_land"] = grid_projected.geometry.intersects(land_union).to_numpy()
    result["distance_to_land_km"] = (
        grid_projected.geometry.distance(land_union).to_numpy() / 1000.0
    )
    result["included_in_coastal_domain"] = (
        ~result["is_land"]
        & (result["distance_to_land_km"] <= max_distance_km)
    )

    return result


def make_cell_polygons(cells: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Convert OISST grid centres to exact 0.25-degree cell polygons."""
    half_cell = GRID_SPACING_DEGREES / 2.0
    result = cells.drop(columns="geometry").copy()
    result["geometry"] = [
        box(
            lon - half_cell,
            lat - half_cell,
            lon + half_cell,
            lat + half_cell,
        )
        for lon, lat in zip(result["longitude"], result["latitude"])
    ]
    return gpd.GeoDataFrame(result, geometry="geometry", crs=WGS84_CRS)


def write_outputs(
    classified_grid: gpd.GeoDataFrame,
    output_directory: Path,
) -> dict[str, Path]:
    """Write auditable tabular and map-ready outputs for human review."""
    output_directory.mkdir(parents=True, exist_ok=True)

    output_paths = {
        "audit_csv": output_directory / "coastal_grid_audit.csv",
        "all_points_geojson": output_directory / "all_candidate_grid_centres.geojson",
        "included_cells_geojson": output_directory / "candidate_coastal_cells_100km.geojson",
    }

    audit_columns = [
        "cell_id",
        "longitude",
        "latitude",
        "is_land",
        "distance_to_land_km",
        "included_in_coastal_domain",
    ]
    classified_grid[audit_columns].sort_values(
        ["latitude", "longitude"]
    ).to_csv(output_paths["audit_csv"], index=False)

    classified_grid.to_file(output_paths["all_points_geojson"], driver="GeoJSON")

    included = classified_grid.loc[
        classified_grid["included_in_coastal_domain"]
    ].copy()
    make_cell_polygons(included).to_file(
        output_paths["included_cells_geojson"],
        driver="GeoJSON",
    )

    return output_paths


def parse_args() -> argparse.Namespace:
    project_root = find_project_root()
    parser = argparse.ArgumentParser(
        description=(
            "Build a candidate 0.25-degree OISST coastal-ocean grid around "
            "mainland New Zealand and Stewart Island."
        )
    )
    parser.add_argument(
        "--coastline-file",
        type=Path,
        default=project_root / "nz-coastlines-and-islands-polygons-topo-150k.gpkg",
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=project_root / "data/reference/regions/v2",
    )
    parser.add_argument("--max-distance-km", type=float, default=100.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = CoastalGridConfig(max_distance_km=args.max_distance_km)

    print(f"Loading coastline: {args.coastline_file}")
    land = load_mainland_nz_land(args.coastline_file, config)
    print(f"Loaded {len(land):,} mainland-scope land features")

    grid = build_oisst_grid(config)
    print(f"Built {len(grid):,} OISST grid centres")

    classified = classify_coastal_cells(
        grid=grid,
        land=land,
        max_distance_km=config.max_distance_km,
    )
    output_paths = write_outputs(classified, args.output_directory)

    print("Coastal-grid summary")
    print(f"  total_grid_centres: {len(classified):,}")
    print(f"  land_centres: {int(classified['is_land'].sum()):,}")
    print(
        "  included_coastal_ocean_centres: "
        f"{int(classified['included_in_coastal_domain'].sum()):,}"
    )
    print(
        "  excluded_offshore_centres: "
        f"{int((~classified['is_land'] & ~classified['included_in_coastal_domain']).sum()):,}"
    )
    for label, path in output_paths.items():
        print(f"  {label}: {path}")


if __name__ == "__main__":
    main()
