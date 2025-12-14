import re
import respx
from httpx import Response
from fastapi.testclient import TestClient
from main import app, HOSPITAL_API_BASE

client = TestClient(app)


@respx.mock
def test_bulk_create_success(tmp_path):
    respx.post(f"{HOSPITAL_API_BASE}/hospitals/").mock(
        return_value=Response(201, json={"id": 101})
    )

    respx.patch(
        re.compile(f"{HOSPITAL_API_BASE}/hospitals/batch/.*/activate")
    ).mock(
        return_value=Response(200, json={"activated": True})
    )

    csv_file = tmp_path / "test.csv"
    csv_file.write_text(
        "Hospital A,Addr A,123\nHospital B,Addr B,456\n"
    )

    with open(csv_file, "rb") as f:
        response = client.post(
            "/hospitals/bulk",
            files={"file": ("test.csv", f, "text/csv")}
        )

    assert response.status_code == 200
    body = response.json()

    assert body["total_hospitals"] == 2
    assert body["failed_hospitals"] == 0
    assert body["batch_activated"] is True
