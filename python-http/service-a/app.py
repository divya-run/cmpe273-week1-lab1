from flask import Flask, request, jsonify
import time
import logging
import json

SERVICE_NAME = "service-a"

# Option C: structured JSON logs
logging.basicConfig(level=logging.INFO, format="%(message)s")
app = Flask(__name__)

# Option D: super tiny metrics (in-memory counters)
METRICS = {
    "requests_total": 0,
    "token_requests": 0,
}

def log_json(level: str, payload: dict):
    payload["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    payload["level"] = level
    print(json.dumps(payload))

@app.before_request
def start_timer():
    request._start_time = time.perf_counter()

@app.after_request
def log_request(response):
    METRICS["requests_total"] += 1

    start = getattr(request, "_start_time", None)
    latency_ms = (time.perf_counter() - start) * 1000 if start else -1

    # Option B/E: request id tracing (header)
    req_id = request.headers.get("X-Request-ID", "")

    log_json("INFO", {
        "service": SERVICE_NAME,
        "endpoint": f"{request.method} {request.path}",
        "status": response.status_code,
        "latency_ms": round(latency_ms, 2),
        "request_id": req_id
    })
    return response

@app.get("/health")
def health():
    return jsonify(status="ok"), 200

# Option D: metrics endpoint
@app.get("/metrics")
def metrics():
    return jsonify(METRICS), 200

# Option A / Best minimal: delay_ms support (slow simulation)
def maybe_delay_from_query_or_json(delay_ms: int):
    if delay_ms and delay_ms > 0:
        time.sleep(delay_ms / 1000.0)

@app.post("/token")
def token():
    METRICS["token_requests"] += 1

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""

    # allow optional slow simulation (either query or body)
    delay_ms = body.get("delay_ms") or request.args.get("delay_ms") or 0
    try:
        delay_ms = int(delay_ms)
    except Exception:
        delay_ms = 0

    maybe_delay_from_query_or_json(delay_ms)

    # Simple fixed credential check (no DB)
    if username == "divya" and password == "pass123":
        # deterministic token (easy to debug)
        return jsonify(token=f"token-{username}", user=username), 200

    return jsonify(error="invalid credentials"), 401

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
