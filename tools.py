import os
import logging
import httpx
import socket
import time
from langchain_core.tools import tool

LOGGER = logging.getLogger("agent")

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://192.168.0.117:9090")


# Read instance names from .env
NODE_INSTANCE = os.getenv("NODE_INSTANCE", "postgres-1:9100")
POSTGRES_EXPORTER_INSTANCE = os.getenv("POSTGRES_EXPORTER_INSTANCE", "postgres-exporter:9187")

# For direct endpoint hits, extract IP from NODE_INSTANCE
VM_HOST = NODE_INSTANCE.split(":")[0]  # "postgres-1" → won't work for URL

# Better: hardcode IPs or read from .env
NODE_EXPORTER_IP = "192.168.0.162"  # The actual VM IP
POSTGRES_EXPORTER_IP = "192.168.0.162"

NODE_EXPORTER_URL = f"http://{NODE_EXPORTER_IP}:9100/metrics"
POSTGRES_EXPORTER_URL = f"http://{POSTGRES_EXPORTER_IP}:9187/metrics"



def get_llm():
    """Initialize LLM with tool-calling support."""
    base_url = os.getenv("MODEL_SERVER_URL")
    api_key = os.getenv("MODEL_SERVER_TOKEN", "dummy-token")
    model_name = os.getenv("MODEL_NAME", "qwen3:14b")
    verify_ssl = os.getenv("MODEL_SERVER_VERIFY_SSL", "true").lower() == "true"

    if not base_url:
        raise ValueError("MODEL_SERVER_URL must be configured in environment")

    from langchain_openai import ChatOpenAI

    custom_headers = {
        "Authorization": f"Bearer {api_key}",
        "X-API-Key": api_key,
    }

    http_client = httpx.Client(
        verify=verify_ssl,
        headers=custom_headers
    )

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

def query_prometheus(query: str) -> dict:
    """Execute a PromQL query against Prometheus."""
    try:
        with httpx.Client(verify=False) as client:
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
        return {"error": str(e)}

def fetch_metrics_endpoint(url: str) -> str:
    """Fetch raw Prometheus metrics from an endpoint."""
    try:
        with httpx.Client(verify=False, timeout=10.0) as client:
            response = client.get(url)
            if response.status_code != 200:
                return f"Error: Failed to fetch metrics from {url}"
            return response.text
    except Exception as e:
        return f"Error: {str(e)}"

def parse_prometheus_metrics(metrics_text: str, metric_names: list = None) -> dict:
    """Parse Prometheus text format metrics, optionally filtering by names."""
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
                # Extract labels
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

            # Filter by metric names if specified
            if metric_names and not any(name in metric_name for name in metric_names):
                continue

            if metric_name not in parsed:
                parsed[metric_name] = []
            parsed[metric_name].append({"value": value, "labels": labels})

        except (ValueError, IndexError, KeyError):
            continue

    return parsed

@tool
def get_node_metrics() -> dict:
    """Fetch comprehensive system metrics: CPU, memory, disk, load, network from Node Exporter."""
    instance = f"{VM_HOST}:9100"

    # Try Prometheus first
    queries = {
        "cpu_usage": f'100 - (avg(rate(node_cpu_seconds_total{{mode="idle",instance="{instance}"}}[1m])) * 100)',
        "memory_used_percent": f'(1 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} / node_memory_MemTotal_bytes{{instance="{instance}"}}) ) * 100',
        "memory_used_gb": f'(node_memory_MemTotal_bytes{{instance="{instance}"}} - node_memory_MemAvailable_bytes{{instance="{instance}"}}) / 1000000000',
        "memory_total_gb": f'node_memory_MemTotal_bytes{{instance="{instance}"}} / 1000000000',
        "disk_used_percent": f'(1 - (node_filesystem_avail_bytes{{instance="{instance}",mountpoint="/"}} / node_filesystem_size_bytes{{instance="{instance}",mountpoint="/"}})) * 100',
        "disk_used_gb": f'(node_filesystem_size_bytes{{instance="{instance}",mountpoint="/"}} - node_filesystem_avail_bytes{{instance="{instance}",mountpoint="/"}}) / 1000000000',
        "disk_total_gb": f'node_filesystem_size_bytes{{instance="{instance}",mountpoint="/"}} / 1000000000',
        "load_1min": f'node_load1{{instance="{instance}"}}',
        "load_5min": f'node_load5{{instance="{instance}"}}',
        "load_15min": f'node_load15{{instance="{instance}"}}',
        "network_receive_bytes_rate": f'rate(node_network_receive_bytes_total{{instance="{instance}",device!="lo"}}[1m])',
        "network_transmit_bytes_rate": f'rate(node_network_transmit_bytes_total{{instance="{instance}",device!="lo"}}[1m])',
        "uptime_days": f'(time() - node_boot_time_seconds{{instance="{instance}"}}) / 86400',
    }

    results = {}
    for metric_name, query in queries.items():
        result = query_prometheus(query)
        if "error" not in result:
            values = result.get("result", [])
            if values:
                if metric_name.startswith("network"):
                    # Network metrics have per-interface data
                    results[metric_name] = {}
                    for v in values:
                        device = v.get("metric", {}).get("device", "unknown")
                        val = float(v.get("value", [0, 0])[1])
                        results[metric_name][device] = round(val / 1000000, 2)  # Convert to Mbps
                else:
                    value = float(values[0].get("value", [0, 0])[1])
                    results[metric_name] = round(value, 2)
        else:
            # Fallback to direct Node Exporter endpoint
            LOGGER.info(f"Prometheus query failed for {metric_name}, falling back to Node Exporter endpoint")
            metrics_text = fetch_metrics_endpoint(NODE_EXPORTER_URL)
            if "Error" not in metrics_text:
                parsed = parse_prometheus_metrics(metrics_text)
                results[f"{metric_name}_fallback"] = "Using direct endpoint"

    return results

@tool
def get_postgres_health() -> dict:
    """Check if PostgreSQL is running and get version info."""
    try:
        # First check: is port 5432 open?
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((VM_HOST, 5432))
        sock.close()

        if result != 0:
            return {
                "postgres_status": "OFFLINE",
                "port_5432_status": "NOT_RESPONDING",
                "message": "No service responding on port 5432"
            }

        # Second check: query postgres exporter for actual version
        try:
            with httpx.Client(verify=False, timeout=5.0) as client:
                response = client.get(POSTGRES_EXPORTER_URL)
                metrics_text = response.text

                # Look for postgres version metric
                version = None
                for line in metrics_text.split('\n'):
                    if 'pg_version' in line and not line.startswith('#'):
                        try:
                            value = float(line.split()[-1])
                            version = int(value)
                            break
                        except:
                            pass

                if version:
                    return {
                        "postgres_status": "ONLINE",
                        "port_5432_status": "OPEN",
                        "version": version,
                        "message": f"PostgreSQL version {version} is accepting connections"
                    }
                else:
                    return {
                        "postgres_status": "UNKNOWN",
                        "port_5432_status": "OPEN",
                        "message": "Port 5432 is open but could not determine PostgreSQL version"
                    }
        except:
            return {
                "postgres_status": "PORT_OPEN_BUT_UNKNOWN",
                "port_5432_status": "OPEN",
                "message": "Port 5432 is responding but PostgreSQL version could not be determined"
            }

    except Exception as e:
        return {
            "postgres_status": "ERROR",
            "error": str(e)
        }


@tool
def get_postgres_metrics() -> dict:
    """Fetch PostgreSQL-specific metrics from Postgres Exporter at 192.168.0.162:9187."""
    metrics_text = fetch_metrics_endpoint(POSTGRES_EXPORTER_URL)

    if "Error" in metrics_text:
        return {"error": metrics_text}

    # Parse relevant postgres metrics
    parsed = parse_prometheus_metrics(
        metrics_text,
        metric_names=[
            "pg_stat_database",
            "pg_connections",
            "pg_replication",
            "pg_wal",
            "pg_cache"
        ]
    )

    results = {}
    for metric_name, values in parsed.items():
        results[metric_name] = values[:5]  # Top 5 values

    return {
        "source": POSTGRES_EXPORTER_URL,
        "metrics": results,
        "total_metrics_found": len(parsed)
    }

@tool
def get_top_processes(limit: int = 5) -> dict:
    """Get top processes by resource usage."""
    instance = f"{VM_HOST}:9100"

    # Try Prometheus first
    cpu_query = f'topk({limit}, rate(process_cpu_seconds_total{{instance="{instance}"}}[1m]) * 100)'
    mem_query = f'topk({limit}, process_resident_memory_bytes{{instance="{instance}"}}) / 1000000'

    cpu_result = query_prometheus(cpu_query)
    mem_result = query_prometheus(mem_query)

    top_cpu = []
    if "result" in cpu_result:
        for item in cpu_result["result"]:
            labels = item.get("metric", {})
            value = float(item.get("value", [0, 0])[1])
            top_cpu.append({
                "job": labels.get("job", "unknown"),
                "cpu_percent": round(value, 2)
            })

    top_mem = []
    if "result" in mem_result:
        for item in mem_result["result"]:
            labels = item.get("metric", {})
            value = float(item.get("value", [0, 0])[1])
            top_mem.append({
                "job": labels.get("job", "unknown"),
                "memory_mb": round(value, 2)
            })

    return {
        "top_by_cpu": top_cpu[:limit],
        "top_by_memory": top_mem[:limit],
    }

@tool
def check_endpoint(url: str) -> dict:
    """Check if a service endpoint is reachable."""
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
        return {"url": url, "online": False, "error": str(e)}

@tool
def get_disk_io_rate() -> dict:
    """Get disk I/O rate from Prometheus."""
    instance = f"{VM_HOST}:9100"

    read_query = f'rate(node_disk_read_bytes_total{{instance="{instance}"}}[1m])'
    write_query = f'rate(node_disk_written_bytes_total{{instance="{instance}"}}[1m])'

    read_result = query_prometheus(read_query)
    write_result = query_prometheus(write_query)

    read_rates = {}
    if "result" in read_result:
        for item in read_result["result"]:
            device = item.get("metric", {}).get("device", "unknown")
            value = float(item.get("value", [0, 0])[1])
            read_rates[device] = round(value / 1000000, 2)  # Convert to MB/s

    write_rates = {}
    if "result" in write_result:
        for item in write_result["result"]:
            device = item.get("metric", {}).get("device", "unknown")
            value = float(item.get("value", [0, 0])[1])
            write_rates[device] = round(value / 1000000, 2)

    return {
        "read_mb_per_sec": read_rates,
        "write_mb_per_sec": write_rates,
    }

@tool
def get_memory_usage() -> dict:
    """Get current memory usage percentage."""
    instance = f"{VM_HOST}:9100"

    query = f'(1 - (node_memory_MemAvailable_bytes{{instance="{instance}"}} / node_memory_MemTotal_bytes{{instance="{instance}"}}) ) * 100'
    result = query_prometheus(query)

    if "error" in result:
        return {"error": result["error"]}

    values = result.get("result", [])
    if values:
        memory_used_percent = float(values[0].get("value", [0, 0])[1])
        return {
            "memory_used_percent": round(memory_used_percent, 2),
            "message": f"Memory usage is {round(memory_used_percent, 2)}%"
        }
    else:
        return {"error": "No data returned"}