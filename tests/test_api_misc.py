from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_validate_endpoint_success():
    data = b"Hospital A,Addr A,123\n"
    response = client.post(
        "/hospitals/bulk/validate", files={"file": ("test.csv", data, "text/csv")}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["valid_rows"] == 1
    assert body["errors"] == []


def test_bulk_status_not_found():
    response = client.get("/bulk/status/unknown-batch-id")
    assert response.status_code == 404


def test_resume_batch_not_found():
    response = client.post("/hospitals/bulk/unknown-batch-id/resume")
    assert response.status_code == 404


def test_delete_batch_not_found():
    response = client.delete("/hospitals/bulk/unknown-batch-id")
    assert response.status_code == 404
