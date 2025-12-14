# main.py
import uuid
import csv
import io
import time
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, File, UploadFile, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import asyncio
import httpx
from pydantic import BaseModel

# Config
HOSPITAL_API_BASE = "https://hospital-directory.onrender.com"  # upstream
MAX_HOSPITALS = 20
CONCURRENT_REQUESTS = 8
REQUEST_TIMEOUT = 15.0  # seconds
RETRY_ATTEMPTS = 2
RETRY_BACKOFF = 0.5  # seconds
POLL_UPDATE_INTERVAL = 0.8  # seconds for WS ping

app = FastAPI(title="Hospital Bulk Processor (with progress)")

class RowResult(BaseModel):
    row: int
    hospital_id: Optional[int] = None
    name: str
    status: str
    error: Optional[str] = None

# --- In-memory status store (process-lifetime only) ---
# Structure:
# BATCH_STATUS[batch_id] = {
#   "total": int,
#   "done": int,
#   "failed": int,
#   "status": "processing"|"done"|"error",
#   "started_at": float,
#   "rows": [ { "index": i, "name":..., "status": "pending"|"created"|"failed", "hospital_id": optional, "error": optional } ]
# }
BATCH_STATUS: Dict[str, Dict[str, Any]] = {}

# Simple registry for websocket connections per batch
WS_CONNECTIONS: Dict[str, List[WebSocket]] = {}

def _broadcast_ws(batch_id: str, payload: Dict[str, Any]):
    conns = WS_CONNECTIONS.get(batch_id, [])
    # fire-and-forget, don't block main processing
    for ws in list(conns):
        asyncio.create_task(_safe_send(ws, payload))

async def _safe_send(ws: WebSocket, payload: Dict[str, Any]):
    try:
        await ws.send_json(payload)
    except Exception:
        # remove closed / broken websockets
        try:
            WS_CONNECTIONS[ws.scope["path"].split("/")[-1]].remove(ws)
        except Exception:
            pass

def _init_batch_status(batch_id: str, rows: List[Dict[str, str]]):
    BATCH_STATUS[batch_id] = {
        "total": len(rows),
        "done": 0,
        "failed": 0,
        "status": "processing",
        "started_at": time.time(),
        "rows": [{"index": i, "name": r["name"], "status": "pending", "hospital_id": None, "error": None} for i, r in enumerate(rows)]
    }

def _update_row_status(batch_id: str, idx: int, status: str, hospital_id: Optional[int] = None, error: Optional[str] = None):
    st = BATCH_STATUS.get(batch_id)
    if not st:
        return
    row_entry = st["rows"][idx]
    prev_status = row_entry["status"]
    # adjust counters
    if prev_status not in ("created", "created_and_activated") and status == "created":
        st["done"] += 1
    if prev_status not in ("failed",) and status == "failed":
        st["failed"] += 1
    row_entry["status"] = status
    row_entry["hospital_id"] = hospital_id
    row_entry["error"] = error
    # broadcast to websockets
    _broadcast_ws(batch_id, {
        "batch_id": batch_id,
        "total": st["total"],
        "done": st["done"],
        "failed": st["failed"],
        "status": st["status"],
        "row": {"index": idx, "status": status, "hospital_id": hospital_id, "error": error}
    })

def _finalize_batch(batch_id: str, success: bool = True):
    st = BATCH_STATUS.get(batch_id)
    if not st:
        return
    st["status"] = "done" if success else "error"
    st["finished_at"] = time.time()
    # final broadcast
    _broadcast_ws(batch_id, {
        "batch_id": batch_id,
        "total": st["total"],
        "done": st["done"],
        "failed": st["failed"],
        "status": st["status"]
    })

# --- CSV parsing & validation ---
def _validate_and_parse_csv(file_bytes: bytes) -> List[Dict[str, str]]:
    try:
        text = file_bytes.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")
    reader = csv.reader(io.StringIO(text))
    rows: List[Dict[str,str]] = []
    line_no = 0
    for r in reader:
        line_no += 1
        if not r or all(not cell.strip() for cell in r):
            continue
        if len(r) < 2:
            raise HTTPException(status_code=400, detail=f"CSV row {line_no} must have at least name and address")
        name = r[0].strip()
        address = r[1].strip()
        phone = r[2].strip() if len(r) >= 3 else ""
        if not name or not address:
            raise HTTPException(status_code=400, detail=f"CSV row {line_no} missing name or address")
        rows.append({"name": name, "address": address, "phone": phone})
        if len(rows) > MAX_HOSPITALS:
            raise HTTPException(status_code=400, detail=f"CSV has more than allowed {MAX_HOSPITALS} hospitals")
    if not rows:
        raise HTTPException(status_code=400, detail="CSV contained no valid hospital rows")
    return rows

# --- Validation-only endpoint (quick check) ---
@app.post("/hospitals/bulk/validate")
async def validate_csv(file: UploadFile = File(...)):
    contents = await file.read()
    rows = _validate_and_parse_csv(contents)  # will raise on invalid
    return {"valid": True, "rows": len(rows)}

# --- HTTP helper with retry/backoff ---
async def _post_hospital(client: httpx.AsyncClient, payload: Dict[str, Any], batch_id: str) -> Dict[str, Any]:
    body = {
        "name": payload["name"],
        "address": payload["address"],
        "phone": payload.get("phone", ""),
        "creation_batch_id": batch_id
    }
    url = f"{HOSPITAL_API_BASE}/hospitals/"
    last_exc: Optional[Exception] = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = await client.post(url, json=body, timeout=REQUEST_TIMEOUT)
            if r.status_code in (200, 201):
                return r.json()
            last_exc = Exception(f"status={r.status_code}, body={r.text}")
        except Exception as e:
            last_exc = e
        await asyncio.sleep(RETRY_BACKOFF * attempt)
    raise last_exc or Exception("unknown error during POST")

# --- Bulk processing endpoint (main) ---
@app.post("/hospitals/bulk")
async def bulk_create_hospitals(file: UploadFile = File(...)):
    if file.filename and not file.filename.lower().endswith(('.csv', '.txt')):
        # allow but warn
        print(f"Warning: uploaded filename {file.filename} doesn't end with .csv/.txt")

    contents = await file.read()
    rows = _validate_and_parse_csv(contents)
    total = len(rows)
    batch_id = str(uuid.uuid4())
    start_ts = time.time()

    # initialize status store
    _init_batch_status(batch_id, rows)

    semaphore = asyncio.Semaphore(CONCURRENT_REQUESTS)

    async with httpx.AsyncClient() as client:
        async def worker(idx: int, payload: Dict[str,str]):
            async with semaphore:
                try:
                    resp_json = await _post_hospital(client, payload, batch_id)
                    hospital_id = resp_json.get("id") or resp_json.get("hospital_id")
                    # update in-memory status
                    _update_row_status(batch_id, idx, "created", hospital_id=hospital_id)
                    return {"row": idx+1, "hospital_id": hospital_id, "name": payload["name"], "status": "created"}
                except Exception as e:
                    _update_row_status(batch_id, idx, "failed", hospital_id=None, error=str(e))
                    return {"row": idx+1, "hospital_id": None, "name": payload["name"], "status": "failed", "error": str(e)}

        tasks = [worker(i, r) for i, r in enumerate(rows)]
        results = await asyncio.gather(*tasks)

        # attempt activation if at least one created
        created_count = sum(1 for x in results if x["status"] == "created")
        batch_activated = False
        activation_error = None
        if created_count > 0:
            try:
                act = await client.patch(f"{HOSPITAL_API_BASE}/hospitals/batch/{batch_id}/activate", timeout=REQUEST_TIMEOUT)
                batch_activated = act.status_code in (200,204)
                if not batch_activated:
                    activation_error = f"activation_status={act.status_code}, body={act.text}"
            except Exception as e:
                activation_error = str(e)

    # if activated, update row statuses to reflect activation
    if batch_activated:
        st = BATCH_STATUS.get(batch_id)
        if st:
            for i, row in enumerate(st["rows"]):
                if row["status"] == "created":
                    row["status"] = "created_and_activated"
            # broadcast final statuses
            _broadcast_ws(batch_id, {"batch_id": batch_id, "status": "activated"})

    elapsed = round(time.time() - start_ts, 3)

    # finalize batch status
    _finalize_batch(batch_id, success=True)

    # build response
    hospitals_out = []
    for r in results:
        hospitals_out.append(r)

    response = {
        "batch_id": batch_id,
        "total_hospitals": total,
        "processed_hospitals": sum(1 for r in hospitals_out if r["status"].startswith("created")),
        "failed_hospitals": sum(1 for r in hospitals_out if r["status"].startswith("failed")),
        "processing_time_seconds": elapsed,
        "batch_activated": batch_activated,
        "activation_error": activation_error,
        "hospitals": hospitals_out
    }
    return JSONResponse(status_code=200, content=response)

# --- Polling endpoint to get batch status ---
@app.get("/bulk/status/{batch_id}")
async def bulk_status(batch_id: str):
    st = BATCH_STATUS.get(batch_id)
    if not st:
        raise HTTPException(status_code=404, detail="batch not found")
    return {
        "batch_id": batch_id,
        "total": st["total"],
        "done": st["done"],
        "failed": st["failed"],
        "status": st["status"],
        "rows": st["rows"]
    }

# --- WebSocket endpoint for real-time updates ---
@app.websocket("/ws/progress/{batch_id}")
async def ws_progress(websocket: WebSocket, batch_id: str):
    await websocket.accept()
    # register
    WS_CONNECTIONS.setdefault(batch_id, []).append(websocket)
    try:
        # send initial snapshot if available
        st = BATCH_STATUS.get(batch_id)
        if st:
            await websocket.send_json({
                "batch_id": batch_id,
                "total": st["total"],
                "done": st["done"],
                "failed": st["failed"],
                "status": st["status"]
            })
        else:
            await websocket.send_json({"batch_id": batch_id, "status": "not_found"})
        # keep connection alive until batch done or client disconnects
        while True:
            # simple keep-alive heartbeat and snapshot every POLL_UPDATE_INTERVAL
            st = BATCH_STATUS.get(batch_id)
            if st:
                await websocket.send_json({
                    "batch_id": batch_id,
                    "total": st["total"],
                    "done": st["done"],
                    "failed": st["failed"],
                    "status": st["status"]
                })
                if st["status"] == "done":
                    await websocket.close()
                    return
            await asyncio.sleep(POLL_UPDATE_INTERVAL)
    except WebSocketDisconnect:
        # cleanup
        try:
            WS_CONNECTIONS[batch_id].remove(websocket)
        except Exception:
            pass
    finally:
        # ensure cleanup if connection still present
        try:
            WS_CONNECTIONS[batch_id].remove(websocket)
        except Exception:
            pass
