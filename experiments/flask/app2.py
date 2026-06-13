from flask import Flask, jsonify
import logging
import random
import time
import threading
import redis

from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor

OTEL_ENDPOINT = "http://0.0.0.0:4317"
resource = Resource(attributes={"service.name": "flask"})

# Traces
tracer_provider = TracerProvider(resource=resource)
tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
trace.set_tracer_provider(tracer_provider)

# Logs
logger_provider = LoggerProvider(resource=resource)
logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_ENDPOINT, insecure=True)))
set_logger_provider(logger_provider)

handler = LoggingHandler(logger_provider=logger_provider)
logging.getLogger().addHandler(handler)

# Flask application setup
app = Flask(__name__)
FlaskInstrumentor().instrument_app(app)

# Redis client
r = redis.Redis(host="localhost", port=6379, decode_responses=True)

@app.route("/")
def home():
    logging.info("Handled / request")
    return jsonify({"message": "Hello from App 1"}), 200

@app.route("/cached")
def cached():
    cached_value = r.get("cached_response")
    if cached_value:
        logging.info("Cache hit for /cached")
        return jsonify({"message": cached_value, "source": "cache"}), 200

    value = "Hello from App 2 (computed)"
    r.setex("cached_response", 30, value)  # expires in 30s
    logging.info("Cache miss for /cached — stored in Redis")
    return jsonify({"message": value, "source": "computed"}), 200

@app.route("/error")
def error():
    logging.error("Handled /error request")
    return jsonify({"error": "Something went wrong in App 1"}), 500

# Background thread to generate dummy logs
dummy_messages = [
    "Starting process",
    "Processing request",
    "Warning: potential issue detected",
    "Error: simulated error occurred",
    "Completed successfully"
]

def generate_dummy_logs():
    while True:
        msg = random.choice(dummy_messages)
        level = random.choice([logging.INFO, logging.WARNING, logging.ERROR])
        logging.log(level, msg)
        time.sleep(0.5)  #

threading.Thread(target=generate_dummy_logs, daemon=True).start()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=9002)
