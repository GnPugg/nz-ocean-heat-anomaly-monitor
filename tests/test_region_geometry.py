from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pytest
from shapely import make_valid
from shapely.geometry import Point, Polygon
from shapely.validation import explain_validity

from nzheat.transform.region_join import spatially_assign_regions


REGIONS_FILE = Path("assets/regions/nz_coastal_regions.geojson")
REQUIRED_REGION_COLUMNS = {"region_id", "region_code", "region_name", "geometry"}


def load_project_regions() -> gpd.GeoDataFrame:
    """Load the real project region file used by the SST spatial join."""
    assert REGIONS_FILE.exists(), f"Missing region file: {REGIONS_FILE}"
    return gpd.read_file(REGIONS_FILE)


def test_region_file_has_complete_unique_identifiers() -> None:
    regions = load_project_regions()

    assert REQUIRED_REGION_COLUMNS.issubset(regions.columns)
    assert not regions.empty

    for column in ("region_id", "region_code", "region_name"):
        assert regions[column].notna().all(), f"Null values found in {column}"
        assert regions[column].is_unique, f"Duplicate values found in {column}"

    assert regions.crs is not None
    assert regions.to_crs("EPSG:4326").crs.to_epsg() == 4326


@pytest.mark.xfail(
    strict=True,
    reason="The current East North Island polygon is geometrically invalid.",
)
def test_region_file_contains_only_valid_geometries() -> None:
    regions = load_project_regions().to_crs("EPSG:4326")

    invalid = [
        f"{row.region_name}: {explain_validity(row.geometry)}"
        for row in regions.itertuples()
        if not row.geometry.is_valid
    ]

    assert not invalid, "Invalid region geometries: " + "; ".join(invalid)


@pytest.mark.xfail(
    strict=True,
    reason="The current region polygons contain substantial interior overlaps.",
)
def test_region_polygons_have_no_substantial_interior_overlaps() -> None:
    regions = load_project_regions().to_crs("EPSG:4326").copy()

    # Repair only in the diagnostic test so intersections can be measured even
    # while the source file still contains an invalid polygon.
    regions["geometry"] = regions.geometry.map(make_valid)
    projected = regions.to_crs("EPSG:2193")

    overlaps: list[str] = []
    minimum_overlap_area_m2 = 1_000_000  # Ignore boundary-only contacts and tiny slivers.

    for left_index in range(len(projected)):
        for right_index in range(left_index + 1, len(projected)):
            left = projected.iloc[left_index]
            right = projected.iloc[right_index]
            overlap_area_m2 = left.geometry.intersection(right.geometry).area

            if overlap_area_m2 > minimum_overlap_area_m2:
                overlaps.append(
                    f"{left.region_name} / {right.region_name}: "
                    f"{overlap_area_m2 / 1_000_000:.2f} km2"
                )

    assert not overlaps, "Substantial region overlaps: " + "; ".join(overlaps)


@pytest.mark.xfail(
    strict=True,
    reason="The current spatial join does not reject points matched to multiple regions.",
)
def test_spatial_assignment_rejects_multiple_region_matches() -> None:
    points = gpd.GeoDataFrame(
        {"point_id": [1]},
        geometry=[Point(1.5, 1.5)],
        crs="EPSG:4326",
    )
    overlapping_regions = gpd.GeoDataFrame(
        {
            "region_id": [1, 2],
            "region_code": ["A", "B"],
            "region_name": ["Region A", "Region B"],
        },
        geometry=[
            Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            Polygon([(1, 1), (3, 1), (3, 3), (1, 3)]),
        ],
        crs="EPSG:4326",
    )

    with pytest.raises(ValueError, match="multiple regions"):
        spatially_assign_regions(points, overlapping_regions)
