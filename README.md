# Hospital Bulk Processor

A small FastAPI service to process hospital records in bulk from CSV files and send them to an upstream Hospital Directory API.  
Features:
- CSV upload endpoint for bulk create (`/hospitals/bulk`)
- CSV validate-only endpoint (`/hospitals/bulk/validate`)
- Batch activation after creation (`PATCH /hospitals/batch/{batch_id}/activate`)
- In-memory progress tracking + polling endpoint (`/bulk/status/{batch_id}`)
- WebSocket real-time progress updates (`/ws/progress/{batch_id}`)
- Dockerfile and docker-compose for easy local runs
- Test suite with `pytest` and `respx` for upstream mocking

---

## Quickstart (local)

### 1. Clone & create venv
```bash
git clone https://github.com/YOUR_USERNAME/hospital-bulk-processor.git
cd hospital-bulk-processor
python -m venv venv
source venv/bin/activate   # Windows: venv\\Scripts\\activate
2. Install (runtime)
bash
Copy code
pip install -r requirements.txt
3. (Optional) Start a local mock upstream to test safely
Create and run mock_upstream.py (a tiny Flask app) that exposes:

POST /hospitals/

PATCH /hospitals/batch/<batch_id>/activate
Run it:

bash
Copy code
pip install flask
python mock_upstream.py
4. Run the FastAPI app (point to mock)
bash
Copy code
# on mac/linux
export HOSPITAL_API_BASE=http://127.0.0.1:9000
uvicorn main:app --reload
# on Windows (PowerShell)
# $env:HOSPITAL_API_BASE="http://127.0.0.1:9000"
# uvicorn main:app --reload
Open API docs: http://127.0.0.1:8000/docs

Endpoints
POST /hospitals/bulk
Multipart form data: file (CSV - columns: name,address,phone)

Returns a JSON processing summary with batch_id.

POST /hospitals/bulk/validate
Validate CSV only — returns {"valid": true, "rows": N}

GET /bulk/status/{batch_id}
Poll processing progress and row-level statuses.

WebSocket /ws/progress/{batch_id}
Subscribe to near-real-time updates for in-progress batches.

Running tests
bash
Copy code
pip install -r requirements-dev.txt
pytest -q
Tests use respx to mock outgoing httpx calls to the upstream API.

Docker
Build & run:

bash
Copy code
docker build -t bulk-processor .
docker run -p 8000:8000 bulk-processor
# or docker compose up --build
Notes & next steps
Current progress store is in-memory (works per process only). For durable/resumable jobs and multi-process/scale, use Redis or a DB.

The WebSocket registry is process-local. For multi-worker deployments, use pub/sub (Redis).

For production, add authentication, rate-limiting, input size limits, and logging/monitoring.

License
MIT