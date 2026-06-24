import os
from dotenv import load_dotenv

load_dotenv()

# --- Model server (relusys) ---
MODEL_SERVER_URL      = os.getenv("MODEL_SERVER_URL", "https://m-serv1.relusys.lan/v1")
MODEL_SERVER_TOKEN    = os.getenv("MODEL_SERVER_TOKEN", "")
MODEL_NAME            = os.getenv("MODEL_NAME", "qwen3:8b")
MODEL_SERVER_VERIFY_SSL = os.getenv("MODEL_SERVER_VERIFY_SSL", "false").lower() == "true"

# --- Prometheus + Loki ---
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://YOUR_MONITORING_SERVER_IP:9090")
LOKI_URL       = os.getenv("LOKI_URL",       "http://YOUR_MONITORING_SERVER_IP:3100")
VM_INSTANCE    = os.getenv("VM_INSTANCE", "")   # must match the Prometheus instance label

# --- Query windows ---
WINDOW_SHORT_HOURS = 1.0   # for status checks
WINDOW_LONG_HOURS  = 3.0   # for outage / diagnosis queries

# --- Keywords that trigger outage diagnosis mode ---
OUTAGE_KEYWORDS = [
    "wrong", "down", "outage", "crash", "fail", "issue",
    "problem", "why", "cause", "error", "died", "unreachable",
]