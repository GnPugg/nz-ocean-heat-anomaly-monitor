from __future__ import annotations

import geopandas as gpd
import numpy as np
from shapely.geometry import box

from nzheat.regions.coastal_grid import (
    CoastalGridConfig,
    aligned_oisst_centres,
    build_oisst_grid,
    classify_coastal_cells,
)


def test_aligned_oisst_centres_uses_quarter_degree_cell_centres() -> None:
    centres = aligned_oisst_centres(164.0, 165.0)
    np.testing.assert_allclose(centres, [164.125, 164.375, 164.625, 164.875])


def test_build_oisst_grid_has_unique_cell_ids_and_expected_size() -> None:
    config = CoastalGridConfig(
        min_lon=164.0,
        max_lon=165.0,
        min_lat=-48.0,
        max_lat=-47.0,
    )
    grid = build_oisst_grid(config)

    assert len(grid) == 16
    assert grid["cell_id"].is_unique
    assert grid.crs.to_epsg() == 4326


def test_classify_coastal_cells_excludes_land_and_distant_ocean() -> None:
    grid = gpd.GeoDataFrame(
        {
            "cell_id": ["land", "near", "far"],
            "longitude": [174.0, 174.2, 177.0],
            "latitude": [-41.0, -41.0, -41.0],
        },
        geometry=gpd.points_from_xy(
            [174.0, 174.2, 177.0],
            [-41.0, -41.0, -41.0],
        ),
        crs="EPSG:4326",
    )
    land = gpd.GeoDataFrame(
        {"name": ["synthetic land"]},
        geometry=[box(173.9, -41.1, 174.1, -40.9)],
        crs="EPSG:4326",
    )

    result = classify_coastal_cells(grid, land, max_distance_km=100.0).set_index(
        "cell_id"
    )

    assert bool(result.loc["land", "is_land"])
    assert not bool(result.loc["land", "included_in_coastal_domain"])
    assert not bool(result.loc["near", "is_land"])
    assert bool(result.loc["near", "included_in_coastal_domain"])
    assert not bool(result.loc["far", "included_in_coastal_domain"])
