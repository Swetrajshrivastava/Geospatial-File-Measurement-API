import csv
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

import fiona
import httpx
import pytest
from pyproj import CRS

from app.main import app
from app.processor import ProcessingError, _feature, process_upload

KML = b'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
  <Placemark id="park"><name>Park</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
    77.59,12.97 77.60,12.97 77.60,12.98 77.59,12.98 77.59,12.97
  </coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
  <Placemark id="road"><LineString><coordinates>77.59,12.97 77.60,12.98</coordinates></LineString></Placemark>
  <Placemark id="marker"><Point><coordinates>77.59,12.97</coordinates></Point></Placemark>
</Document></kml>'''

MULTI_ZONE_KML = b'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>
5.99,10.0 6.01,10.0 6.01,10.01 5.99,10.01 5.99,10.0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></kml>'''


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client() -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api_client:
        yield api_client


@pytest.mark.anyio
async def test_upload_and_measure_kml(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/files/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 201
    summary = response.json()
    assert summary["feature_count"] == 3
    assert summary["crs"] == "EPSG:4326"

    measurements = await client.get(f"/api/files/{summary['id']}/measurements/")
    assert measurements.status_code == 200
    features = measurements.json()["features"]
    assert features[0]["measurement"]["type"] == "area"
    assert features[0]["measurement"]["value"] > 0
    assert features[0]["source_crs"] == "EPSG:4326"
    assert features[0]["measurement_crs"] == "EPSG:32643"
    assert features[0]["measurement"]["status"] == "COMPLETED"
    assert features[1]["measurement"]["type"] == "length"
    assert features[2]["measurement_status"] == "NOT_APPLICABLE"


@pytest.mark.anyio
async def test_rejects_unsupported_extension(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/files/", files={"file": ("data.geojson", b"{}", "application/json")})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_rejects_malformed_kml(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/files/", files={"file": ("broken.kml", b"<kml><Placemark>", "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 422
    assert "Invalid or unsafe KML" in response.json()["detail"]


@pytest.mark.anyio
async def test_rejects_unsafe_zip_path(client: httpx.AsyncClient) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("../outside.shp", b"not a shapefile")
    response = await client.post("/api/files/", files={"file": ("unsafe.zip", archive.getvalue(), "application/zip")})
    assert response.status_code == 422
    assert "unsafe path" in response.json()["detail"]


@pytest.mark.anyio
async def test_measurements_include_metric_units(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/files/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    file_id = response.json()["id"]
    features = (await client.get(f"/api/files/{file_id}/measurements/")).json()["features"]
    assert features[0]["measurement"]["unit"] == "m²"
    assert features[1]["measurement"]["unit"] == "m"


@pytest.mark.anyio
async def test_unknown_file_id_returns_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/files/does-not-exist/")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_rejects_incomplete_shapefile_archive(client: httpx.AsyncClient) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        zip_file.writestr("incomplete.shp", b"not a valid shapefile")
    response = await client.post("/api/files/", files={"file": ("incomplete.zip", archive.getvalue(), "application/zip")})
    assert response.status_code == 422


@pytest.mark.anyio
async def test_uploads_and_measures_zipped_shapefile(client: httpx.AsyncClient) -> None:
    temporary_root = Path("data/test-tmp")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary_root) as directory:
        shapefile = Path(directory) / "parcel.shp"
        schema = {"geometry": "Polygon", "properties": {"name": "str"}}
        with fiona.open(shapefile, "w", driver="ESRI Shapefile", schema=schema, crs="EPSG:4326") as source:
            source.write({"geometry": {"type": "Polygon", "coordinates": [[[77.59, 12.97], [77.60, 12.97], [77.60, 12.98], [77.59, 12.98], [77.59, 12.97]]]}, "properties": {"name": "Parcel A"}})
        archive = BytesIO()
        with ZipFile(archive, "w") as zip_file:
            for component in Path(directory).glob("parcel.*"):
                zip_file.write(component, component.name)

        response = await client.post("/api/files/", files={"file": ("parcel.zip", archive.getvalue(), "application/zip")})
    assert response.status_code == 201
    assert response.json()["crs"] == "EPSG:4326"
    features = (await client.get(f"/api/files/{response.json()['id']}/measurements/")).json()["features"]
    assert features[0]["properties"]["name"] == "Parcel A"
    assert features[0]["measurement"]["type"] == "area"
    assert features[0]["measurement"]["unit"] == "m²"
    assert features[0]["measurement"]["value"] > 0


@pytest.mark.anyio
async def test_multi_zone_geometry_has_no_misleading_measurement(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/files/", files={"file": ("multi-zone.kml", MULTI_ZONE_KML, "application/vnd.google-earth.kml+xml")})
    file_id = response.json()["id"]
    feature = (await client.get(f"/api/files/{file_id}/measurements/")).json()["features"][0]
    assert feature["measurement"] is None
    assert feature["measurement_crs"] is None
    assert feature["measurement_status"] == "UNAVAILABLE"
    assert "multiple UTM zones" in feature["message"]


@pytest.mark.parametrize(
    ("geometry", "crs", "expected_status"),
    [
        ({"type": "Polygon", "coordinates": []}, CRS.from_epsg(4326), "EMPTY"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}, CRS.from_epsg(4326), "INVALID"),
        ({"type": "Point", "coordinates": [0, 0]}, CRS.from_epsg(4326), "NOT_APPLICABLE"),
        ({"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]}, None, "UNAVAILABLE"),
    ],
)
def test_feature_validation_statuses(geometry: dict, crs: CRS | None, expected_status: str) -> None:
    feature = _feature("test", geometry, {}, crs)
    assert feature.measurement_status == expected_status
    assert feature.measurement is None
    assert feature.measurement_crs is None


def test_multipart_geometry_totals_and_measurement_crs() -> None:
    crs = CRS.from_epsg(3857)
    polygon = _feature("polygons", {"type": "MultiPolygon", "coordinates": [[[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]], [[[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]]]}, {}, crs)
    line = _feature("lines", {"type": "MultiLineString", "coordinates": [[[0, 0], [3, 4]], [[10, 0], [10, 7]]]}, {}, crs)
    assert polygon.measurement == {"type": "area", "value": 200.0, "unit": "m²", "status": "COMPLETED"}
    assert line.measurement == {"type": "length", "value": 12.0, "unit": "m", "status": "COMPLETED"}
    assert polygon.measurement_crs == "EPSG:3857"
    assert line.measurement_crs == "EPSG:3857"


@pytest.mark.anyio
async def test_rejects_upload_larger_than_limit(client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 8)
    response = await client.post("/api/files/", files={"file": ("large.kml", b"123456789", "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 413


def test_processing_failure_cleans_up_workspace() -> None:
    temporary_root = Path("data/test-tmp")
    temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temporary_root) as directory:
        storage_root = Path(directory) / "uploads"
        with pytest.raises(ProcessingError):
            process_upload("broken.kml", b"<kml><Placemark>", storage_root)
        assert list(storage_root.iterdir()) == []


@pytest.mark.anyio
async def test_exports_csv_measurement_report(client: httpx.AsyncClient) -> None:
    upload = await client.post("/api/files/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    response = await client.get(f"/api/files/{upload.json()['id']}/measurements/export/?format=csv")
    rows = list(csv.DictReader(response.text.splitlines()))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].endswith('.csv"')
    assert len(rows) == 3
    assert rows[0]["source_crs"] == "EPSG:4326"
    assert rows[0]["measurement_type"] == "area"
    assert rows[0]["measurement_unit"] == "m²"
    assert rows[2]["measurement_status"] == "NOT_APPLICABLE"
    assert rows[2]["measurement_crs"] == ""


@pytest.mark.anyio
async def test_exports_geojson_with_geometry_and_measurement_metadata(client: httpx.AsyncClient) -> None:
    upload = await client.post("/api/files/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    response = await client.get(f"/api/files/{upload.json()['id']}/measurements/export/?format=geojson")
    document = response.json()
    point = document["features"][2]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/geo+json")
    assert response.headers["content-disposition"].endswith('.geojson"')
    assert document["type"] == "FeatureCollection"
    assert document["metadata"]["geometry_crs"] == "EPSG:4326"
    assert len(document["features"]) == 3
    assert document["features"][0]["geometry"]["type"] == "Polygon"
    assert document["features"][0]["properties"]["source_properties"]["name"] == "Park"
    assert point["geometry"] == {"type": "Point", "coordinates": [77.59, 12.97]}
    assert point["properties"]["measurement"] is None
    assert point["properties"]["measurement_crs"] is None


@pytest.mark.anyio
async def test_export_rejects_unknown_file_or_format(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/files/does-not-exist/measurements/export/?format=csv")
    upload = await client.post("/api/files/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    invalid_format = await client.get(f"/api/files/{upload.json()['id']}/measurements/export/?format=xlsx")
    assert missing.status_code == 404
    assert invalid_format.status_code == 422


@pytest.mark.anyio
async def test_job_processes_kml_and_persists_results(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/jobs/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "QUEUED"

    status_response = await client.get(f"/api/jobs/{job['job_id']}/")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "COMPLETED"
    assert status_body["feature_count"] == 3
    assert status_body["processed_count"] == 3
    assert status_body["successful_count"] == 2
    assert status_body["progress_percent"] == 100.0

    measurements = await client.get(f"/api/jobs/{job['job_id']}/measurements/")
    assert measurements.status_code == 200
    assert measurements.json()["features"][0]["measurement"]["type"] == "area"


@pytest.mark.anyio
async def test_job_failure_is_persisted(client: httpx.AsyncClient) -> None:
    response = await client.post("/api/jobs/", files={"file": ("broken.kml", b"<kml><Placemark>", "application/vnd.google-earth.kml+xml")})
    job_id = response.json()["job_id"]
    job = (await client.get(f"/api/jobs/{job_id}/")).json()
    assert job["status"] == "FAILED"
    assert job["error_message"]
    measurements = await client.get(f"/api/jobs/{job_id}/measurements/")
    assert measurements.status_code == 409


@pytest.mark.anyio
async def test_job_export_and_unknown_job(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/jobs/does-not-exist/")
    upload = await client.post("/api/jobs/", files={"file": ("survey.kml", KML, "application/vnd.google-earth.kml+xml")})
    response = await client.get(f"/api/jobs/{upload.json()['job_id']}/measurements/export/?format=geojson")
    assert missing.status_code == 404
    assert response.status_code == 200
    assert response.json()["type"] == "FeatureCollection"
