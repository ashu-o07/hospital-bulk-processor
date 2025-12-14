# Hospital Bulk Processor

Hospital Bulk Processor is a FastAPI-based service that processes hospital records in bulk from CSV files and integrates with an existing Hospital Directory API. The system supports CSV validation, bulk creation, batch activation, progress tracking, retrying failed rows, and batch deletion. The solution is designed to be lightweight, testable, and easy to run locally or in Docker.

Features:
- Bulk CSV upload for hospital creation (POST /hospitals/bulk)
- CSV validation-only endpoint (POST /hospitals/bulk/validate)
- Automatic batch activation after successful creation
- In-memory progress tracking with polling support
- Real-time progress updates via WebSocket
- Resume failed bulk operations
- Delete bulk batches
- Dockerized setup for local execution
- Automated unit and integration tests using pytest and respx

Tech Stack:
- Language: Python 3.8+
- Framework: FastAPI
- HTTP Client: httpx (async)
- Testing: pytest, pytest-asyncio, respx
- Containerization: Docker

Quickstart (Local):

1. Clone the repository and create a virtual environment
git clone https://github.com/ashu-o07/hospital-bulk-processor.git
cd hospital-bulk-processor
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

2. Install runtime dependencies
pip install -r requirements.txt

3. Run the FastAPI application
macOS / Linux:
export HOSPITAL_API_BASE=http://127.0.0.1:9000
uvicorn main:app --reload

Windows (PowerShell):
$env:HOSPITAL_API_BASE="http://127.0.0.1:9000"
uvicorn main:app --reload

API documentation is available at:
http://127.0.0.1:8000/docs

API Endpoints:

POST /hospitals/bulk  
Accepts a CSV file with columns: name,address,phone (phone optional).  
Creates hospitals in bulk, assigns a batch ID, activates the batch, and returns a detailed processing summary.

POST /hospitals/bulk/validate  
Validates the CSV format and content without creating hospitals.  
Returns row-level validation errors if present.

GET /bulk/status/{batch_id}  
Polls the current processing status of a bulk operation, including per-row progress.

WebSocket /ws/progress/{batch_id}  
Provides near real-time progress updates for an in-progress bulk job.

POST /hospitals/bulk/{batch_id}/resume  
Retries only the failed rows from a previous bulk operation and reattempts batch activation.

DELETE /hospitals/bulk/{batch_id}  
Deletes a batch and removes all hospitals in that batch using the upstream API.

Running Tests:

Install development dependencies:
pip install -r requirements-dev.txt

Run tests:
pytest -q

Test Coverage:
- CSV parsing and strict validation
- Validation-only endpoint
- Bulk create flow with mocked upstream API
- Batch lifecycle error handling (status, resume, delete)

External HTTP calls are mocked using respx. WebSocket progress updates were verified manually during local and Docker runs.

Docker:

Build and run the service:
docker build -t hospital-bulk-processor .
docker run -p 8000:8000 hospital-bulk-processor

Or using docker-compose:
docker compose up --build

Design Notes & Limitations:
- All batch metadata and progress state is stored in memory.
- Data is lost on application restart.
- WebSocket connections are process-local and not shared across workers.
- For production-scale usage, Redis or a database should be used for persistence and pub/sub messaging.

License:
MIT