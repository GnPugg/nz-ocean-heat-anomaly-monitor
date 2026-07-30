from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
import xarray as xr
from shapely.geometry import box

from nzheat.regions.coastal_grid import (
    CoastalGridConfig,
    aligned_oisst_centres,
    apply_oisst_ocean_mask,
    build_oisst_grid,
    classify_coastal_cells,
    parse_args,
    split_by_mainland_proximity,
    split_remote_islands,
    write_outputs,
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


def test_split_remote_islands_excludes_named_remote_groups() -> None:
    land = gpd.GeoDataFrame(
        {
            "name_ascii": [
                "North Island",
                "South Island",
                "Stewart Island",
                "Campbell Island/Motu Ihupuku",
                "Muttonbird (Titi) Islands",
                None,
            ],
            "grp_ascii": [
                None,
                None,
                None,
                None,
                "Titi / Muttonbird Islands",
                "Snares Islands/Tini Heke",
            ],
        },
        geometry=[
            box(172.0, -41.0, 178.0, -34.0),
            box(166.0, -46.5, 173.0, -40.5),
            box(167.5, -47.3, 168.6, -46.6),
            box(169.0, -52.6, 169.1, -52.5),
            box(168.65, -47.0, 168.7, -46.95),
            box(166.5, -48.1, 166.6, -48.0),
        ],
        crs="EPSG:4326",
    )

    retained, excluded = split_remote_islands(land)

    assert retained["name_ascii"].fillna("").tolist() == [
        "North Island",
        "South Island",
        "Stewart Island",
        "Muttonbird (Titi) Islands",
    ]
    assert set(excluded["name_ascii"].fillna("")) == {
        "Campbell Island/Motu Ihupuku",
        "",
    }


def test_split_by_mainland_proximity_excludes_unnamed_remote_features() -> None:
    land = gpd.GeoDataFrame(
        {
            "name_ascii": [
                "North Island",
                "South Island",
                "Stewart Island",
                "Nearby unnamed island",
                None,
            ],
            "grp_ascii": [None, None, None, None, None],
        },
        geometry=[
            box(172.0, -41.0, 178.0, -34.0),
            box(166.0, -46.5, 173.0, -40.5),
            box(167.5, -47.3, 168.6, -46.6),
            box(168.65, -47.0, 168.7, -46.95),
            box(178.8, -47.8, 179.2, -47.4),
        ],
        crs="EPSG:4326",
    )

    retained, excluded = split_by_mainland_proximity(
        land,
        max_distance_km=80.0,
    )

    assert set(retained["name_ascii"].fillna("")) == {
        "North Island",
        "South Island",
        "Stewart Island",
        "Nearby unnamed island",
    }
    assert excluded["name_ascii"].fillna("").tolist() == [""]

def test_write_outputs_uses_requested_distance_in_filename(tmp_path) -> None:
    grid = gpd.GeoDataFrame(
        {
            "cell_id": ["included"],
            "longitude": [174.125],
            "latitude": [-41.125],
            "is_land": [False],
            "distance_to_land_km": [42.0],
            "included_in_coastal_domain": [True],
        },
        geometry=gpd.points_from_xy([174.125], [-41.125]),
        crs="EPSG:4326",
    )

    paths = write_outputs(grid, tmp_path, max_distance_km=75.0)

    assert paths["included_cells_geojson"].name == (
        "candidate_coastal_cells_75km.geojson"
    )
    assert paths["included_cells_geojson"].exists()


def _synthetic_oisst_dataset() -> xr.Dataset:
    return xr.Dataset(
        {
            "sst": (
                ("time", "zlev", "lat", "lon"),
                np.array([[[[15.0, np.nan], [16.0, 17.0]]]], dtype=np.float32),
            )
        },
        coords={
            "time": [0],
            "zlev": [0.0],
            "lat": [-41.125, -40.875],
            "lon": [173.875, 174.125],
        },
    )


def test_apply_oisst_ocean_mask_excludes_masked_and_missing_cells(
    tmp_path,
    monkeypatch,
) -> None:
    mask_path = tmp_path / "oisst-mask.nc"
    mask_path.touch()
    monkeypatch.setattr(
        "nzheat.regions.coastal_grid.xr.open_dataset",
        lambda *args, **kwargs: _synthetic_oisst_dataset(),
    )

    grid = gpd.GeoDataFrame(
        {
            "cell_id": ["valid", "masked", "missing-coordinate"],
            "longitude": [173.875, 174.125, 174.375],
            "latitude": [-41.125, -41.125, -41.125],
            "is_land": [False, False, False],
            "distance_to_land_km": [1.0, 2.0, 3.0],
            "included_in_coastal_domain": [True, True, True],
        },
        geometry=gpd.points_from_xy(
            [173.875, 174.125, 174.375],
            [-41.125, -41.125, -41.125],
        ),
        crs="EPSG:4326",
    )

    result = apply_oisst_ocean_mask(grid, mask_path).set_index("cell_id")

    assert bool(result.loc["valid", "oisst_coordinate_exists"])
    assert bool(result.loc["valid", "oisst_ocean_cell"])
    assert bool(result.loc["valid", "included_in_coastal_domain"])

    assert bool(result.loc["masked", "oisst_coordinate_exists"])
    assert not bool(result.loc["masked", "oisst_ocean_cell"])
    assert not bool(result.loc["masked", "included_in_coastal_domain"])

    assert not bool(result.loc["missing-coordinate", "oisst_coordinate_exists"])
    assert not bool(result.loc["missing-coordinate", "oisst_ocean_cell"])
    assert not bool(
        result.loc["missing-coordinate", "included_in_coastal_domain"]
    )


def test_apply_oisst_ocean_mask_rejects_unreadable_file(
    tmp_path,
    monkeypatch,
) -> None:
    bad_path = tmp_path / "not-netcdf.nc"
    bad_path.write_text("not a NetCDF file", encoding="utf-8")

    def fail_open(*args, **kwargs):
        raise OSError("unknown file format")

    monkeypatch.setattr(
        "nzheat.regions.coastal_grid.xr.open_dataset",
        fail_open,
    )

    grid = gpd.GeoDataFrame(
        {
            "cell_id": ["candidate"],
            "longitude": [173.875],
            "latitude": [-41.125],
            "is_land": [False],
            "distance_to_land_km": [1.0],
            "included_in_coastal_domain": [True],
        },
        geometry=gpd.points_from_xy([173.875], [-41.125]),
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="Could not open OISST mask file"):
        apply_oisst_ocean_mask(grid, bad_path)


def test_coastal_grid_config_defaults_to_75_km() -> None:
    assert CoastalGridConfig().max_distance_km == 75.0


def test_parse_args_requires_oisst_mask_file(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr("sys.argv", ["coastal-grid"])

    with pytest.raises(SystemExit) as exc_info:
        parse_args()

    assert exc_info.value.code == 2
    assert "--oisst-mask-file" in capsys.readouterr().err
