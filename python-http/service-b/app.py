from flask import Flask, request, jsonify
import time
import logging
import json
import uuid
import requests

SERVICE_NAME = "service-b"
SERVICE_A = "http://127.0.0.1:8080"
TIMEOUT_SECS = 1.0

# Option C: structured JSON logs
logging.basicConfig(level=logging.INFO, format="%(message)s")
app = Flask(__name__)

# Option D: super tiny metrics (in-memory counters)
METRICS = {
    "requests_total": 0,
    "protected_action_requests": 0,
    "provider_failures": 0,
    "provider_timeouts": 0,
    "provider_connection_errors": 0,
    "provider_other_errors": 0,
    "retries_used": 0,
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

def call_provider_token(username: str, password: str, delay_ms: int, request_id: str, enable_retry: bool):
    """
    Calls Service A /token with timeout.
    Option F: retry once on transient failures (timeout/connection).
    """
    url = f"{SERVICE_A}/token"
    headers = {"X-Request-ID": request_id}
    payload = {"username": username, "password": password, "delay_ms": delay_ms}

    attempts = 2 if enable_retry else 1
    last_exc = None

    for attempt in range(attempts):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT_SECS)
            # If provider returns 401, treat as auth failure, not service failure
            if r.status_code == 401:
                return ("auth_failed", None, None)

            r.raise_for_status()
            return ("ok", r.json(), None)

        except requests.exceptions.Timeout as e:
            METRICS["provider_failures"] += 1
            METRICS["provider_timeouts"] += 1
            last_exc = e
            log_json("ERROR", {
                "service": SERVICE_NAME,
                "event": "provider_call_failed",
                "error": "timeout",
                "timeout_secs": TIMEOUT_SECS,
                "attempt": attempt + 1,
                "request_id": request_id
            })

        except requests.exceptions.ConnectionError as e:
            METRICS["provider_failures"] += 1
            METRICS["provider_connection_errors"] += 1
            last_exc = e
            log_json("ERROR", {
                "service": SERVICE_NAME,
                "event": "provider_call_failed",
                "error": "connection_error",
                "details": str(e),
                "attempt": attempt + 1,
                "request_id": request_id
            })

        except requests.exceptions.RequestException as e:
            METRICS["provider_failures"] += 1
            METRICS["provider_other_errors"] += 1
            last_exc = e
            log_json("ERROR", {
                "service": SERVICE_NAME,
                "event": "provider_call_failed",
                "error": "request_exception",
                "details": str(e),
                "attempt": attempt + 1,
                "request_id": request_id
            })
            break  # don't retry on non-transient unless you want to

        if enable_retry and attempt == 0:
            METRICS["retries_used"] += 1
            # quick small backoff
            time.sleep(0.05)

    return ("provider_failed", None, str(last_exc) if last_exc else "unknown error")

@app.post("/protected-action")
def protected_action():
    METRICS["protected_action_requests"] += 1

    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    action = body.get("action") or "ping"

    # Option A: simulate slowness in provider via delay_ms forwarded to Service A
    delay_ms = body.get("delay_ms") or 0
    try:
        delay_ms = int(delay_ms)
    except Exception:
        delay_ms = 0

    # Option F: allow turning retry on/off (default True)
    enable_retry = body.get("retry") if body.get("retry") is not None else True
    enable_retry = bool(enable_retry)

    # Option B/E: request id tracing — use incoming header if present, otherwise generate
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())

    status, provider_json, err = call_provider_token(
        username=username,
        password=password,
        delay_ms=delay_ms,
        request_id=request_id,
        enable_retry=enable_retry
    )

    if status == "auth_failed":
        return jsonify(error="invalid credentials"), 401

    if status != "ok":
        return jsonify(error="provider unavailable", details=err), 503

    # Combined response (consumer + provider)
    return jsonify(
        consumer="ok",
        action=action,
        user=provider_json.get("user"),
        token=provider_json.get("token"),
        request_id=request_id
    ), 200

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8081, debug=False)
