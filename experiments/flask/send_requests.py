import requests
import random
import logging
import time
# Setup Python logging (OTel log injection will capture these if OTEL_PYTHON_LOG_CORRELATION=true)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

import os

APP1_HOST = os.environ.get("APP1_HOST", "localhost")
APP2_HOST = os.environ.get("APP2_HOST", "localhost")

apps = [
    (f"http://{APP1_HOST}:9001/", f"http://{APP1_HOST}:9001/error"),
    (f"http://{APP2_HOST}:9002/", f"http://{APP2_HOST}:9002/error"),
]

cached_urls = [
    f"http://{APP2_HOST}:9002/cached",
]

def send_request():
    for app in apps:
        url = random.choice(app)
        try:
            resp = requests.get(url, timeout=2)
            logging.info(f"Sent to {url} - Status: {resp.status_code}")
        except Exception as e:
            logging.error(f"Request to {url} failed: {e}")

    for url in cached_urls:
        try:
            resp = requests.get(url, timeout=2)
            source = resp.json().get("source", "unknown")
            logging.info(f"Sent to {url} - Status: {resp.status_code} - Source: {source}")
        except Exception as e:
            logging.error(f"Request to {url} failed: {e}")

if __name__ == "__main__":
    while(True):
        send_request()
        # Sleep for a short duration to avoid overwhelming the server
        time.sleep(2)

