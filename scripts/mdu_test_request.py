import os
import sys
import time
import secrets
from datetime import datetime, timezone, timedelta
import requests

# Step 1 & 2: Load environment variables using project's existing configuration approach
env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' not in line:
                continue
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

# Configuration check
raw_base_url = os.getenv('MDU_BASE_URL', '')
base_url = raw_base_url.rstrip('/')
api_key = os.getenv('MDU_API_KEY')

api_key_configured = bool(api_key and len(api_key.strip()) > 0)
api_key_len = len(api_key) if api_key else 0

if not api_key_configured:
    print("ERROR: MDU_API_KEY is missing or empty. Aborting request.")
    sys.exit(1)

if not base_url:
    print("ERROR: MDU_BASE_URL is missing or empty. Aborting request.")
    sys.exit(1)

# Step 3: Generate fresh cryptographically random 32-character hex trace ID
trace_id = secrets.token_hex(16)

# Step 4: Execute authenticated request
target_url = f"{base_url}/api/v1/discovery/summary"
headers = {
    'X-API-Key': api_key,
    'X-Trace-Id': trace_id,
}

tz_ist = timezone(timedelta(hours=5, minutes=30))
start_time = time.perf_counter()
exec_timestamp_ist = datetime.now(tz_ist).strftime('%Y-%m-%d %H:%M:%S IST')

status_code = None
body_first_100 = ""
completed_successfully = False
error_msg = None

try:
    response = requests.get(
        target_url,
        headers=headers,
        timeout=30,
        verify=True,
    )
    duration = time.perf_counter() - start_time
    status_code = response.status_code
    body_first_100 = response.text[:100]
    completed_successfully = True
except Exception as e:
    duration = time.perf_counter() - start_time
    error_msg = str(e)
    body_first_100 = f"Exception: {error_msg}"[:100]
    completed_successfully = False

# Step 5: Output captured verification results
print(f"MDU endpoint URL: {target_url}")
print(f"API key configured: {'YES' if api_key_configured else 'NO'}")
print(f"API key length: {api_key_len}")
print(f"Fresh trace ID: {trace_id}")
print(f"HTTP status code: {status_code}")
print(f"Response body (first 100 characters): {body_first_100}")
print(f"Exact execution timestamp in IST (Asia/Kolkata): {exec_timestamp_ist}")
print(f"Request duration: {duration:.3f}s")
print(f"Request completed successfully: {'YES' if completed_successfully else 'NO'}")


