from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4
from zipfile import BadZipFile, ZipFile

import fiona
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from pyproj import CRS, Transformer
from shapely import transform
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from app.models import FeatureMeasurement, FileSummary
from app.repository import ProcessedFile

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 100
KML_NS = "{http://www.opengis.net/kml/2.2}"


class ProcessingError(ValueError):
    pass


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


def _crs_label(crs: CRS | None) -> str | None:
    if crs is None:
        return None
    authority = crs.to_authority()
    return f"{authority[0]}:{authority[1]}" if authority else crs.to_string()


def _measurement_crs(geometry: BaseGeometry, source_crs: CRS) -> CRS:
    """Choose a metre-based CRS. Geographic data is projected into local UTM."""
    if not source_crs.is_geographic:
        axis = source_crs.axis_info[0] if source_crs.axis_info else None
        if axis and axis.unit_conversion_factor and abs(axis.unit_conversion_factor - 1) < 1e-9:
            return source_crs

    to_wgs84 = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)
    geometry_wgs84 = transform(geometry, to_wgs84.transform, interleaved=False)
    min_lon, _, max_lon, _ = geometry_wgs84.bounds
    if max_lon - min_lon > 180:
        raise ProcessingError("Geometry crosses the antimeridian; local UTM measurement is unavailable.")
    min_zone = max(1, min(60, int((min_lon + 180) / 6) + 1))
    max_zone = max(1, min(60, int((max_lon + 180) / 6) + 1))
    if min_zone != max_zone:
        raise ProcessingError("Geometry spans multiple UTM zones; local UTM measurement is unavailable.")
    lon, lat = geometry_wgs84.representative_point().coords[0]
    zone = max(1, min(60, int((lon + 180) / 6) + 1))
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def _measure(geometry: BaseGeometry, source_crs: CRS | None) -> tuple[dict[str, float | str] | None, str | None, str, str | None]:
    geometry_type = geometry.geom_type
    if geometry_type not in {"Polygon", "MultiPolygon", "LineString", "MultiLineString"}:
        return None, None, "NOT_APPLICABLE", "No measurement is defined for this geometry type."
    if source_crs is None:
        return None, None, "UNAVAILABLE", "Source CRS is missing, so a reliable measurement cannot be calculated."
    try:
        target_crs = _measurement_crs(geometry, source_crs)
        projected = transform(geometry, Transformer.from_crs(source_crs, target_crs, always_xy=True).transform, interleaved=False)
        if geometry_type in {"Polygon", "MultiPolygon"}:
            measurement = {"type": "area", "value": round(projected.area, 3), "unit": "m²", "status": "COMPLETED"}
        else:
            measurement = {"type": "length", "value": round(projected.length, 3), "unit": "m", "status": "COMPLETED"}
        return measurement, _crs_label(target_crs), "COMPLETED", None
    except Exception as exc:  # Individual bad geometries should never fail the upload.
        return None, None, "UNAVAILABLE", f"Measurement could not be calculated: {exc}"


def _feature(feature_id: str | int, geometry_data: dict[str, Any] | None, properties: dict[str, Any], crs: CRS | None) -> FeatureMeasurement:
    source_crs = _crs_label(crs)
    if geometry_data is None:
        return FeatureMeasurement(feature_id=feature_id, geometry_type=None, geometry=None, crs=source_crs, source_crs=source_crs, properties=properties, measurement_status="MISSING", message="Feature has no geometry.")
    try:
        geometry = shape(geometry_data)
        if geometry.is_empty:
            return FeatureMeasurement(feature_id=feature_id, geometry_type=geometry.geom_type, geometry=geometry_data, crs=source_crs, source_crs=source_crs, properties=properties, measurement_status="EMPTY", message="Geometry is empty.")
        if not geometry.is_valid:
            return FeatureMeasurement(feature_id=feature_id, geometry_type=geometry.geom_type, geometry=geometry_data, crs=source_crs, source_crs=source_crs, properties=properties, measurement_status="INVALID", message="Geometry is invalid and was not measured.")
        measurement, measurement_crs, status, message = _measure(geometry, crs)
        return FeatureMeasurement(feature_id=feature_id, geometry_type=geometry.geom_type, geometry=geometry_data, crs=source_crs, source_crs=source_crs, properties=properties, measurement=measurement, measurement_crs=measurement_crs, measurement_status=status, message=message)
    except Exception as exc:
        return FeatureMeasurement(feature_id=feature_id, geometry_type=geometry_data.get("type"), geometry=geometry_data, crs=source_crs, source_crs=source_crs, properties=properties, measurement_status="INVALID", message=f"Invalid geometry: {exc}")


def _read_shapefile(directory: Path) -> tuple[list[FeatureMeasurement], CRS | None]:
    shapefiles = list(directory.rglob("*.shp"))
    if len(shapefiles) != 1:
        raise ProcessingError("The ZIP must contain exactly one .shp file.")
    with fiona.open(shapefiles[0]) as source:
        try:
            crs = CRS.from_user_input(source.crs_wkt or source.crs) if (source.crs_wkt or source.crs) else None
        except Exception:
            crs = None
        features = [_feature(record.get("id", index), record.get("geometry"), {key: _json_value(value) for key, value in dict(record.get("properties") or {}).items()}, crs) for index, record in enumerate(source)]
    return features, crs


def _coordinates(text: str | None) -> list[tuple[float, float, float | None]]:
    if not text or not text.strip():
        raise ProcessingError("KML geometry has no coordinates.")
    values = []
    for token in text.split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ProcessingError("KML coordinates are malformed.")
        values.append((float(parts[0]), float(parts[1]), float(parts[2]) if len(parts) > 2 else None))
    return values


def _position(value: tuple[float, float, float | None]) -> list[float]:
    return [value[0], value[1]] + ([value[2]] if value[2] is not None else [])


def _kml_geometries(element: ET.Element) -> Iterator[dict[str, Any]]:
    tag = element.tag.rsplit("}", 1)[-1]
    if tag == "Point":
        yield {"type": "Point", "coordinates": _position(_coordinates(element.findtext(f"{KML_NS}coordinates"))[0])}
    elif tag == "LineString":
        yield {"type": "LineString", "coordinates": [_position(point) for point in _coordinates(element.findtext(f"{KML_NS}coordinates"))]}
    elif tag == "Polygon":
        rings = []
        for boundary in list(element.findall(f"{KML_NS}outerBoundaryIs")) + list(element.findall(f"{KML_NS}innerBoundaryIs")):
            rings.append([_position(point) for point in _coordinates(boundary.findtext(f".//{KML_NS}coordinates"))])
        yield {"type": "Polygon", "coordinates": rings}
    elif tag == "MultiGeometry":
        for child in element:
            yield from _kml_geometries(child)


def _read_kml(path: Path) -> tuple[list[FeatureMeasurement], CRS]:
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, DefusedXmlException) as exc:
        raise ProcessingError(f"Invalid or unsafe KML: {exc}") from exc
    crs = CRS.from_epsg(4326)  # KML 2.2 coordinates are longitude/latitude WGS 84.
    features: list[FeatureMeasurement] = []
    for placemark_index, placemark in enumerate(root.findall(f".//{KML_NS}Placemark")):
        properties: dict[str, Any] = {}
        name = placemark.findtext(f"{KML_NS}name")
        description = placemark.findtext(f"{KML_NS}description")
        if name:
            properties["name"] = name
        if description:
            properties["description"] = description
        for data in placemark.findall(f".//{KML_NS}Data"):
            if data.get("name"):
                properties[data.get("name")] = data.findtext(f"{KML_NS}value")
        geometries = [geometry for child in placemark for geometry in _kml_geometries(child)]
        if not geometries:
            features.append(_feature(placemark.get("id", placemark_index), None, properties, crs))
        else:
            for geometry_index, geometry in enumerate(geometries):
                feature_id = placemark.get("id", str(placemark_index))
                if len(geometries) > 1:
                    feature_id = f"{feature_id}-{geometry_index}"
                features.append(_feature(feature_id, geometry, properties, crs))
    return features, crs


def _extract_zip(upload_path: Path, destination: Path) -> None:
    try:
        with ZipFile(upload_path) as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise ProcessingError("ZIP contains too many files.")
            if any(Path(member.filename).is_absolute() or ".." in Path(member.filename).parts for member in members):
                raise ProcessingError("ZIP contains an unsafe path.")
            if sum(member.file_size for member in members) > MAX_UPLOAD_BYTES * 4:
                raise ProcessingError("Uncompressed ZIP content is too large.")
            archive.extractall(destination)
    except BadZipFile as exc:
        raise ProcessingError("The uploaded ZIP is invalid.") from exc


def process_upload(filename: str, contents: bytes, storage_root: Path) -> ProcessedFile:
    suffix = Path(filename).suffix.lower()
    if suffix not in {".kml", ".zip"}:
        raise ProcessingError("Only .kml files and .zip Shapefile archives are accepted.")
    if not contents:
        raise ProcessingError("The uploaded file is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ProcessingError("The uploaded file exceeds the 50 MB limit.")
    file_id = uuid4().hex
    workdir = storage_root / file_id
    workdir.mkdir(parents=True, exist_ok=False)
    try:
        upload_path = workdir / f"upload{suffix}"
        upload_path.write_bytes(contents)
        if suffix == ".kml":
            features, crs = _read_kml(upload_path)
        else:
            extracted = workdir / "extracted"
            extracted.mkdir()
            _extract_zip(upload_path, extracted)
            features, crs = _read_shapefile(extracted)
        summary = FileSummary(id=file_id, filename=Path(filename).name, feature_count=len(features), crs=_crs_label(crs), status="COMPLETED")
        return ProcessedFile(summary=summary, features=features)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
