import os
import logging
import httpx
import socket
import time
from datetime import datetime, timedelta
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

LOGGER = logging.getLogger("agent")

# Configuration
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.168.0.117:9090")
NODE_EXPORTER_URL = os.getenv("NODE_EXPORTER_URL", "http://192.168.0.162:9100/metrics")
POSTGRES_EXPORTER_URL = os.getenv("POSTGRES_EXPORTER_URL", "http://192.168.0.162:9187/metrics")
VM_HOST = os.getenv("VM_HOST", "192.168.0.162")
DEBUG_TOOLS = os.getenv("DEBUG_TOOLS", "true").lower() == "true"


def debug_tools_enabled() -> bool:
    return DEBUG_TOOLS


def _debug(message: str) -> None:
    if debug_tools_enabled():
        LOGGER.info(f"🔍 [TOOL DEBUG]: {message}")


def get_llm():
    """Initialize LLM with tool-calling support."""
    base_url = os.getenv("MODEL_SERVER_URL")
    api_key = os.getenv("MODEL_SERVER_TOKEN", "dummy-token")
    model_name = os.getenv("MODEL_NAME", "qwen3.6:27b")
    verify_ssl = os.getenv("MODEL_SERVER_VERIFY_SSL", "true").lower() == "true"

    if not base_url:
        raise ValueError("MODEL_SERVER_URL must be configured in environment")

    custom_headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
    }

    http_client = httpx.Client(verify=verify_ssl, headers=custom_headers)

    if not verify_ssl:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    return ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0,
        max_tokens=2048,
        http_client=http_client
    )


def query_prometheus(query: str, start: int = None, end: int = None, step: str = "60s") -> dict:
    """Execute a PromQL query. Can be instant or range query."""
    _debug(f"Querying Prometheus: {query[:50]}...")
    try:
        with httpx.Client(verify=False) as client:
            if start and end:
                response = client.get(
                    f"{PROMETHEUS_URL}/api/v1/query_range",
                    params={"query": query, "start": start, "end": end, "step": step},
                    timeout=15.0
                )
            else:
                response = client.get(
                    f"{PROMETHEUS_URL}/api/v1/query",
                    params={"query": query},
                    timeout=10.0
                )

            if response.status_code != 200:
                return {"error": f"Prometheus query failed: {response.status_code}"}

            data = response.json()
            if data.get("status") != "success":
                return {"error": f"Query error: {data.get('error', 'Unknown')}"}

            return data.get("data", {})
    except Exception as e:
        _debug(f"Prometheus query failed: {str(e)}")
        return {"error": str(e)}


def fetch_metrics_endpoint(url: str) -> str:
    """Fetch raw Prometheus metrics from an endpoint."""
    _debug(f"Fetching metrics from {url}")
    try:
        with httpx.Client(verify=False, timeout=10.0) as client:
            response = client.get(url)
            if response.status_code != 200:
                return f"Error: Failed to fetch metrics (status {response.status_code})"
            return response.text
    except Exception as e:
        return f"Error: {str(e)}"


def parse_prometheus_metrics(metrics_text: str, metric_names: list = None) -> dict:
    """Parse Prometheus text format metrics."""
    parsed = {}
    lines = metrics_text.split('\n')

    for line in lines:
        if line.startswith('#') or not line.strip():
            continue

        try:
            if '{' in line:
                metric_name = line.split('{')[0]
                value = float(line.split()[-1])
                labels = {}
                label_str = line.split('{')[1].split('}')[0]
                for pair in label_str.split(','):
                    key, val = pair.split('=')
                    labels[key.strip()] = val.strip('"')
            else:
                parts = line.split()
                if len(parts) < 2:
                    continue
                metric_name = parts[0]
                value = float(parts[1])
                labels = {}

            if metric_names and not any(name in metric_name for name in metric_names):
                continue

            if metric_name not in parsed:
                parsed[metric_name] = []
            parsed[metric_name].append({"value": value, "labels": labels})

        except (ValueError, IndexError, KeyError):
            continue

    return parsed


# ============================================================================
# CORE MONITORING TOOLS - INTERNAL IMPLEMENTATIONS
# ============================================================================

def _get_node_metrics_impl() -> dict:
    """Internal: Fetch comprehensive system metrics."""
    _debug("Fetching node metrics from Prometheus")

    queries = {
        "cpu_usage": '100 - (avg(rate(node_cpu_seconds_total{mode="idle",job="node-postgres-1"}[1m])) * 100)',
        "memory_used_percent": '(1 - (node_memory_MemAvailable_bytes{job="node-postgres-1"} / node_memory_MemTotal_bytes{job="node-postgres-1"})) * 100',
        "memory_used_gb": '(node_memory_MemTotal_bytes{job="node-postgres-1"} - node_memory_MemAvailable_bytes{job="node-postgres-1"}) / 1000000000',
        "memory_total_gb": 'node_memory_MemTotal_bytes{job="node-postgres-1"} / 1000000000',
        "disk_used_percent": '(1 - (node_filesystem_avail_bytes{job="node-postgres-1",mountpoint="/"} / node_filesystem_size_bytes{job="node-postgres-1",mountpoint="/"})) * 100',
        "disk_used_gb": '(node_filesystem_size_bytes{job="node-postgres-1",mountpoint="/"} - node_filesystem_avail_bytes{job="node-postgres-1",mountpoint="/"}) / 1000000000',
        "disk_total_gb": 'node_filesystem_size_bytes{job="node-postgres-1",mountpoint="/"} / 1000000000',
        "load_1min": 'node_load1{job="node-postgres-1"}',
        "load_5min": 'node_load5{job="node-postgres-1"}',
        "load_15min": 'node_load15{job="node-postgres-1"}',
        "uptime_days": '(time() - node_boot_time_seconds{job="node-postgres-1"}) / 86400',
    }

    results = {}
    for metric_name, query in queries.items():
        result = query_prometheus(query)
        if "error" not in result and "result" in result:
            values = result.get("result", [])
            if values:
                value = float(values[0].get("value", [0, 0])[1])
                results[metric_name] = round(value, 2)
            else:
                results[metric_name] = 0
        else:
            results[metric_name] = 0

    return {
        "cpu_percent": results.get("cpu_usage", 0),
        "memory": {
            "used_percent": results.get("memory_used_percent", 0),
            "used_gb": results.get("memory_used_gb", 0),
            "total_gb": results.get("memory_total_gb", 0),
        },
        "disk": {
            "used_percent": results.get("disk_used_percent", 0),
            "used_gb": results.get("disk_used_gb", 0),
            "total_gb": results.get("disk_total_gb", 0),
        },
        "load": {
            "1min": results.get("load_1min", 0),
            "5min": results.get("load_5min", 0),
            "15min": results.get("load_15min", 0),
        },
        "uptime_days": results.get("uptime_days", 0),
    }


@tool
def get_node_metrics() -> dict:
    """Fetch comprehensive system metrics: CPU, memory, disk, load, network."""
    return _get_node_metrics_impl()


def _get_postgres_health_impl() -> dict:
    """Internal: Check PostgreSQL health."""
    _debug("Checking PostgreSQL health")

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((VM_HOST, 5432))
        sock.close()

        if result == 0:
            return {
                "postgres_status": "ONLINE",
                "port": 5432,
                "message": "PostgreSQL is accepting connections"
            }
        else:
            return {
                "postgres_status": "OFFLINE",
                "port": 5432,
                "message": "PostgreSQL is not responding on port 5432"
            }

    except Exception as e:
        return {
            "postgres_status": "ERROR",
            "error": str(e)
        }


@tool
def get_postgres_health() -> dict:
    """Check if PostgreSQL is running and accepting connections."""
    return _get_postgres_health_impl()


def _get_postgres_connections_impl() -> dict:
    """Internal: Get PostgreSQL connection metrics."""
    _debug("Fetching PostgreSQL connection metrics")

    try:
        queries = {
            "active": 'sum(pg_stat_activity_count{state="active"})',
            "idle": 'sum(pg_stat_activity_count{state="idle"})',
            "max": 'pg_settings_max_connections',
        }

        results = {}
        for name, query in queries.items():
            result = query_prometheus(query)
            if "result" in result and result["result"]:
                value = float(result["result"][0].get("value", [0, 0])[1])
                results[name] = int(value)

        active = results.get("active", 0)
        idle = results.get("idle", 0)
        max_conn = results.get("max", 100)
        total = active + idle
        usage_percent = round((total / max_conn * 100), 2) if max_conn > 0 else 0

        return {
            "active_connections": active,
            "idle_connections": idle,
            "total_connections": total,
            "max_connections": max_conn,
            "usage_percent": usage_percent,
        }
    except Exception as e:
        _debug(f"Failed to get connections: {e}")
        return {"error": f"Failed to query connection metrics: {str(e)}"}


@tool
def get_postgres_connections() -> dict:
    """Get PostgreSQL connection metrics."""
    return _get_postgres_connections_impl()


@tool
def check_endpoint(url: str) -> dict:
    """Check if a service endpoint is reachable."""
    _debug(f"Checking endpoint: {url}")

    try:
        with httpx.Client(timeout=5.0, verify=False) as client:
            response = client.get(url)
            is_online = response.status_code < 400
            return {
                "url": url,
                "status_code": response.status_code,
                "online": is_online,
                "message": "Online" if is_online else "Offline"
            }
    except Exception as e:
        return {
            "url": url,
            "online": False,
            "error": str(e),
            "message": "Connection failed"
        }


# ============================================================================
# FEATURE 1: HISTORICAL TRENDS
# ============================================================================

def _get_metric_trends_impl(metric: str = "cpu", hours: int = 1) -> dict:
    """Internal: Analyze historical trends."""
    _debug(f"Analyzing {metric} trends for past {hours} hours")

    if hours < 1 or hours > 24:
        return {"error": "Hours must be between 1 and 24"}

    now = int(time.time())
    start = now - (hours * 3600)

    metric_queries = {
        "cpu": '100 - (avg(rate(node_cpu_seconds_total{mode="idle",job="node-postgres-1"}[1m])) * 100)',
        "memory": '(1 - (node_memory_MemAvailable_bytes{job="node-postgres-1"} / node_memory_MemTotal_bytes{job="node-postgres-1"})) * 100',
        "disk": '(1 - (node_filesystem_avail_bytes{job="node-postgres-1",mountpoint="/"} / node_filesystem_size_bytes{job="node-postgres-1",mountpoint="/"})) * 100',
        "load": 'node_load1{job="node-postgres-1"}',
    }

    if metric not in metric_queries:
        return {"error": f"Unknown metric: {metric}. Supported: cpu, memory, disk, load"}

    query = metric_queries[metric]
    result = query_prometheus(query, start=start, end=now, step="60s")

    if "error" in result or "result" not in result:
        return {"error": "Failed to fetch historical data"}

    series = result.get("result", [])
    if not series or not series[0].get("values"):
        return {"error": "No historical data available"}

    values = [float(v[1]) for v in series[0]["values"]]

    if not values:
        return {"error": "No valid data points"}

    min_val = min(values)
    max_val = max(values)
    avg_val = sum(values) / len(values)
    current_val = values[-1]

    if len(values) > 1:
        first_half_avg = sum(values[:len(values)//2]) / (len(values)//2)
        second_half_avg = sum(values[len(values)//2:]) / (len(values) - len(values)//2)
        trend = "📈 Increasing" if second_half_avg > first_half_avg else "📉 Decreasing"
        rate_of_change = round(((second_half_avg - first_half_avg) / first_half_avg * 100), 2) if first_half_avg > 0 else 0
    else:
        trend = "➡️ Stable"
        rate_of_change = 0

    return {
        "metric": metric,
        "hours": hours,
        "current_value": round(current_val, 2),
        "min_value": round(min_val, 2),
        "max_value": round(max_val, 2),
        "avg_value": round(avg_val, 2),
        "trend": trend,
        "rate_of_change_percent": rate_of_change,
        "data_points": len(values),
    }


@tool
def get_metric_trends(metric: str = "cpu", hours: int = 1) -> dict:
    """Analyze historical trends for a metric over the past N hours. Metrics: cpu, memory, disk, load"""
    return _get_metric_trends_impl(metric, hours)


# ============================================================================
# FEATURE 2: SMART ANOMALY DETECTION
# ============================================================================

def _detect_anomalies_impl() -> dict:
    """Internal: Detect unusual patterns."""
    _debug("Running anomaly detection")

    current = _get_node_metrics_impl()
    cpu_trend = _get_metric_trends_impl("cpu", hours=6)
    mem_trend = _get_metric_trends_impl("memory", hours=6)
    disk_trend = _get_metric_trends_impl("disk", hours=6)
    load_trend = _get_metric_trends_impl("load", hours=6)

    anomalies = []
    severity_score = 0

    if not cpu_trend.get("error"):
        cpu_current = current["cpu_percent"]
        cpu_avg = cpu_trend.get("avg_value", 0)

        if cpu_current > cpu_avg + (cpu_avg * 0.5):
            anomalies.append({
                "type": "CPU_SPIKE",
                "severity": "HIGH" if cpu_current > 80 else "MEDIUM",
                "current": cpu_current,
                "baseline": cpu_avg,
                "message": f"CPU usage ({cpu_current}%) is significantly higher than baseline ({cpu_avg}%)"
            })
            severity_score += 3 if cpu_current > 80 else 2

    if not mem_trend.get("error"):
        mem_current = current["memory"]["used_percent"]
        mem_avg = mem_trend.get("avg_value", 0)

        if mem_current > mem_avg + (mem_avg * 0.3):
            anomalies.append({
                "type": "MEMORY_SPIKE",
                "severity": "HIGH" if mem_current > 85 else "MEDIUM",
                "current": mem_current,
                "baseline": mem_avg,
                "message": f"Memory usage ({mem_current}%) is abnormally high compared to baseline ({mem_avg}%)"
            })
            severity_score += 3 if mem_current > 85 else 2

    if not disk_trend.get("error"):
        disk_current = current["disk"]["used_percent"]

        if disk_current > 90:
            anomalies.append({
                "type": "DISK_CRITICAL",
                "severity": "CRITICAL",
                "current": disk_current,
                "message": f"Disk usage ({disk_current}%) is critical. Immediate action needed."
            })
            severity_score += 5

    if not load_trend.get("error"):
        load_current = current["load"]["1min"]
        load_avg = load_trend.get("avg_value", 0)

        if load_current > load_avg * 2:
            anomalies.append({
                "type": "LOAD_SPIKE",
                "severity": "HIGH",
                "current": load_current,
                "baseline": load_avg,
                "message": f"System load ({load_current}) is 2x higher than baseline ({load_avg})"
            })
            severity_score += 3

    if current["cpu_percent"] > 70 and current["memory"]["used_percent"] > 70:
        anomalies.append({
            "type": "RESOURCE_PRESSURE",
            "severity": "HIGH",
            "message": "Both CPU (>70%) and Memory (>70%) are under heavy load simultaneously"
        })
        severity_score += 2

    return {
        "anomalies_detected": len(anomalies),
        "severity_score": severity_score,
        "overall_health": "CRITICAL" if severity_score >= 8 else "WARNING" if severity_score >= 5 else "HEALTHY",
        "anomalies": anomalies,
        "timestamp": datetime.now().isoformat(),
    }


@tool
def detect_anomalies() -> dict:
    """Detect unusual patterns in system metrics using statistical analysis."""
    return _detect_anomalies_impl()


# ============================================================================
# FEATURE 3: DEEP DEBUGGING
# ============================================================================

def _debug_issue_impl(problem: str) -> str:
    """Internal: Deep debugging analysis."""
    _debug(f"Deep debugging: {problem}")

    current_metrics = _get_node_metrics_impl()
    postgres_health = _get_postgres_health_impl()
    postgres_conns = _get_postgres_connections_impl()
    anomalies = _detect_anomalies_impl()
    cpu_trends = _get_metric_trends_impl("cpu", hours=2)
    mem_trends = _get_metric_trends_impl("memory", hours=2)

    analysis = []
    analysis.append("🔍 ROOT CAUSE ANALYSIS\n")

    if current_metrics["cpu_percent"] > 70 and postgres_conns.get("total_connections", 0) > 100:
        analysis.append(f"🚨 DATABASE OVERLOAD: High CPU ({current_metrics['cpu_percent']}%) + High connections ({postgres_conns['total_connections']})")
        analysis.append("   → Consider killing idle connections or optimizing slow queries\n")

    if mem_trends.get("trend") == "📈 Increasing":
        analysis.append(f"💾 MEMORY LEAK DETECTED: Memory increasing at {mem_trends.get('rate_of_change_percent')}%/hour")
        analysis.append("   → Check for unbounded caches or query result sets\n")

    if postgres_health.get("postgres_status") == "OFFLINE":
        analysis.append("❌ POSTGRESQL DOWN: Connection refused on port 5432")
        analysis.append("   → Restart PostgreSQL service or check firewall rules\n")

    if current_metrics["disk"]["used_percent"] > 90:
        analysis.append(f"💿 DISK CRITICAL: {current_metrics['disk']['used_percent']}% full")
        analysis.append("   → Clean up logs/temp files or add storage\n")

    if cpu_trends.get("trend") == "📈 Increasing":
        analysis.append(f"📊 TREND: CPU load increasing ({cpu_trends.get('rate_of_change_percent')}% over time)")
        analysis.append("   → Check for new workloads or resource competition\n")

    analysis.append("\n💡 RECOMMENDATIONS:\n")

    if anomalies.get("severity_score", 0) >= 8:
        analysis.append("1. URGENT: Execute incident response plan")
        analysis.append("2. Notify on-call team immediately")
        analysis.append("3. Start collecting diagnostics (logs, traces)")
    elif anomalies.get("severity_score", 0) >= 5:
        analysis.append("1. Monitor the situation closely")
        analysis.append("2. Start investigating root cause")
        analysis.append("3. Prepare for potential mitigation")
    else:
        analysis.append("1. System appears healthy overall")
        analysis.append("2. Continue normal monitoring")
        analysis.append("3. Address any minor anomalies")

    return "\n".join(analysis)


@tool
def debug_issue(problem: str) -> str:
    """Deep debugging: Analyze system state to find root cause. Examples: 'Why is postgres slow?', 'Database is crashing'"""
    return _debug_issue_impl(problem)


# ============================================================================
# GET TOOLS LIST
# ============================================================================

def get_tools() -> list:
    """Return the list of tools available to the agent."""
    return [
        get_node_metrics,
        get_postgres_health,
        get_postgres_connections,
        check_endpoint,
        get_metric_trends,
        detect_anomalies,
        debug_issue,
    ]


if __name__ == "__main__":
    print("Testing anomaly detection...")
    result = _detect_anomalies_impl()
    print(result)

    print("\nTesting metric trends...")
    result = _get_metric_trends_impl("cpu", hours=2)
    print(result)

    print("\nTesting deep debugging...")
    result = _debug_issue_impl("Why is the system slow?")
    print(result)

