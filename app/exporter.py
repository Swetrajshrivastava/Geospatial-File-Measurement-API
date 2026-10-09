from __future__ import annotations

import csv
import json
from io import StringIO
from typing import Literal

from app.repository import ProcessedFile

ExportFormat = Literal["csv", "geojson"]


def build_csv_report(item: ProcessedFile) -> str:
    """Create a spreadsheet-friendly report without dropping feature properties."""
    output = StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "feature_id",
            "geometry_type",
            "source_crs",
            "measurement_crs",
            "measurement_type",
            "measurement_value",
            "measurement_unit",
            "measurement_status",
            "message",
            "properties",
        ],
        lineterminator="\n",
    )
    writer.writeheader()
    for feature in item.features:
        measurement = feature.measurement or {}
        writer.writerow(
            {
                "feature_id": feature.feature_id,
                "geometry_type": feature.geometry_type,
                "source_crs": feature.source_crs,
                "measurement_crs": feature.measurement_crs,
                "measurement_type": measurement.get("type"),
                "measurement_value": measurement.get("value"),
                "measurement_unit": measurement.get("unit"),
                "measurement_status": feature.measurement_status,
                "message": feature.message,
                "properties": json.dumps(feature.properties, ensure_ascii=False, sort_keys=True),
            }
        )
    return output.getvalue()


def build_geojson_report(item: ProcessedFile) -> dict[str, object]:
    """Preserve source geometry and attach auditable measurement metadata."""
    features: list[dict[str, object]] = []
    for feature in item.features:
        features.append(
            {
                "type": "Feature",
                "id": feature.feature_id,
                "geometry": feature.geometry,
                "properties": {
                    "source_properties": feature.properties,
                    "geometry_type": feature.geometry_type,
                    "source_crs": feature.source_crs,
                    "measurement_crs": feature.measurement_crs,
                    "measurement": feature.measurement,
                    "measurement_status": feature.measurement_status,
                    "message": feature.message,
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "metadata": {
            "file_id": item.summary.id,
            "filename": item.summary.filename,
            "feature_count": item.summary.feature_count,
            "geometry_crs": item.summary.crs,
            "geometry_crs_note": "Geometries are preserved in their source CRS. GeoJSON clients commonly expect WGS 84 coordinates.",
        },
        "features": features,
    }
