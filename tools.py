import os
import logging
from typing import Optional
import httpx
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI



LOGGER = logging.getLogger("rcloud.agent")

def debug_tools_enabled() -> bool:
    return os.getenv("DEBUG_TOOLS", "false").lower() == "true"

def _debug(message: str) -> None:
    if debug_tools_enabled():
        LOGGER.info(f"🔍 [TOOL DEBUG]: {message}")

def get_llm():
    """Initializes the LLM with tool-calling support."""
    base_url = os.getenv("MODEL_SERVER_URL")
    api_key = os.getenv("MODEL_SERVER_TOKEN", "dummy-token")
    model_name = os.getenv("MODEL_NAME", "qwen3.6:27b")
    verify_ssl = os.getenv("MODEL_SERVER_VERIFY_SSL", "true").lower() == "true"

    if not base_url:
        raise ValueError("MODEL_SERVER_URL must be configured in environment")

    LOGGER.info(f"Initializing {model_name} at {base_url}")

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

@tool
def get_postgres1_node_metrics() -> dict:
    """Fetches comprehensive system metrics from postgres-1 node exporter endpoint."""
    _debug("Querying postgres-1 node exporter at 192.168.0.162:9100/metrics")

    try:
        with httpx.Client(timeout=10.0, verify=False) as client:
            response = client.get("http://192.168.0.162:9100/metrics")
            if response.status_code != 200:
                return {"error": f"Failed to fetch metrics: {response.status_code}"}

            metrics_text = response.text
            metrics = parse_node_exporter_metrics(metrics_text)
            return metrics
    except Exception as e:
        return {"error": str(e)}

def parse_node_exporter_metrics(metrics_text: str) -> dict:
    """Comprehensive parsing of all node exporter metrics with fixes for memory and load."""
    lines = metrics_text.split('\n')
    parsed = {}

    for line in lines:
        if line.startswith('#') or not line.strip():
            continue

        try:
            if '{' in line:
                metric_name = line.split('{')[0]
                value = float(line.split()[-1])
            else:
                parts = line.split()
                if len(parts) < 2:
                    continue
                metric_name = parts[0]
                value = float(parts[1])

            # ===== CPU METRICS =====
            if 'node_cpu_seconds_total' in metric_name:
                if 'cpu_modes' not in parsed:
                    parsed['cpu_modes'] = {}
                for mode in ['user', 'system', 'idle', 'iowait', 'irq', 'softirq', 'steal', 'nice']:
                    if mode in line:
                        if mode not in parsed['cpu_modes']:
                            parsed['cpu_modes'][mode] = []
                        parsed['cpu_modes'][mode].append(value)

            # ===== MEMORY METRICS (FIX) =====
            elif metric_name == 'node_memory_MemTotal_bytes':
                parsed['memory_total_bytes'] = value
            elif metric_name == 'node_memory_MemFree_bytes':
                parsed['memory_free_bytes'] = value
            elif metric_name == 'node_memory_MemAvailable_bytes':
                parsed['memory_available_bytes'] = value
            elif metric_name == 'node_memory_Buffers_bytes':
                parsed['memory_buffers_bytes'] = value
            elif metric_name == 'node_memory_Cached_bytes':
                parsed['memory_cached_bytes'] = value
            elif metric_name == 'node_memory_Dirty_bytes':
                parsed['memory_dirty_bytes'] = value
            elif metric_name == 'node_memory_Slab_bytes':
                parsed['memory_slab_bytes'] = value
            elif 'node_memory_Swap' in metric_name:
                if 'SwapTotal' in metric_name:
                    parsed['swap_total_bytes'] = value
                elif 'SwapFree' in metric_name:
                    parsed['swap_free_bytes'] = value

            # ===== DISK FILESYSTEM METRICS =====
            elif 'node_filesystem_size_bytes' in metric_name and 'mountpoint="/"' in line:
                parsed['disk_total_bytes'] = value
            elif 'node_filesystem_avail_bytes' in metric_name and 'mountpoint="/"' in line:
                parsed['disk_available_bytes'] = value
            elif 'node_filesystem_files_free' in metric_name and 'mountpoint="/"' in line:
                parsed['disk_inodes_free'] = value
            elif 'node_filesystem_files' in metric_name and 'mountpoint="/"' in line and 'free' not in metric_name:
                parsed['disk_inodes_total'] = value

            # ===== DISK I/O METRICS =====
            elif 'node_disk_io_time_seconds_total' in metric_name:
                if 'disk_io_time' not in parsed:
                    parsed['disk_io_time'] = {}
                device = line.split('device="')[1].split('"')[0] if 'device=' in line else 'unknown'
                parsed['disk_io_time'][device] = value
            elif 'node_disk_reads_completed_total' in metric_name:
                if 'disk_reads' not in parsed:
                    parsed['disk_reads'] = {}
                device = line.split('device="')[1].split('"')[0] if 'device=' in line else 'unknown'
                parsed['disk_reads'][device] = value
            elif 'node_disk_writes_completed_total' in metric_name:
                if 'disk_writes' not in parsed:
                    parsed['disk_writes'] = {}
                device = line.split('device="')[1].split('"')[0] if 'device=' in line else 'unknown'
                parsed['disk_writes'][device] = value
            elif 'node_disk_read_bytes_total' in metric_name:
                if 'disk_read_bytes' not in parsed:
                    parsed['disk_read_bytes'] = {}
                device = line.split('device="')[1].split('"')[0] if 'device=' in line else 'unknown'
                parsed['disk_read_bytes'][device] = value
            elif 'node_disk_written_bytes_total' in metric_name:
                if 'disk_written_bytes' not in parsed:
                    parsed['disk_written_bytes'] = {}
                device = line.split('device="')[1].split('"')[0] if 'device=' in line else 'unknown'
                parsed['disk_written_bytes'][device] = value

            # ===== NETWORK METRICS =====
            elif 'node_network_receive_bytes_total' in metric_name:
                if 'device=' in line:
                    device = line.split('device="')[1].split('"')[0]
                    if 'network_interfaces' not in parsed:
                        parsed['network_interfaces'] = {}
                    if device not in parsed['network_interfaces']:
                        parsed['network_interfaces'][device] = {}
                    parsed['network_interfaces'][device]['receive_bytes'] = value

            elif 'node_network_transmit_bytes_total' in metric_name:
                if 'device=' in line:
                    device = line.split('device="')[1].split('"')[0]
                    if 'network_interfaces' not in parsed:
                        parsed['network_interfaces'] = {}
                    if device not in parsed['network_interfaces']:
                        parsed['network_interfaces'][device] = {}
                    parsed['network_interfaces'][device]['transmit_bytes'] = value

            elif 'node_network_receive_errs_total' in metric_name:
                if 'device=' in line:
                    device = line.split('device="')[1].split('"')[0]
                    if 'network_interfaces' not in parsed:
                        parsed['network_interfaces'] = {}
                    if device not in parsed['network_interfaces']:
                        parsed['network_interfaces'][device] = {}
                    parsed['network_interfaces'][device]['receive_errors'] = value
            elif 'node_network_transmit_errs_total' in metric_name:
                if 'device=' in line:
                    device = line.split('device="')[1].split('"')[0]
                    if 'network_interfaces' not in parsed:
                        parsed['network_interfaces'] = {}
                    if device not in parsed['network_interfaces']:
                        parsed['network_interfaces'][device] = {}
                    parsed['network_interfaces'][device]['transmit_errors'] = value
            elif 'node_network_receive_drop_total' in metric_name:
                if 'device=' in line:
                    device = line.split('device="')[1].split('"')[0]
                    if 'network_interfaces' not in parsed:
                        parsed['network_interfaces'] = {}
                    if device not in parsed['network_interfaces']:
                        parsed['network_interfaces'][device] = {}
                    parsed['network_interfaces'][device]['receive_dropped'] = value
            elif 'node_network_transmit_drop_total' in metric_name:
                if 'device=' in line:
                    device = line.split('device="')[1].split('"')[0]
                    if 'network_interfaces' not in parsed:
                        parsed['network_interfaces'] = {}
                    if device not in parsed['network_interfaces']:
                        parsed['network_interfaces'][device] = {}
                    parsed['network_interfaces'][device]['transmit_dropped'] = value
            # ===== PROCESS METRICS =====
            elif 'node_processes_running' in metric_name:
                parsed['processes_running'] = int(value)
            elif 'node_processes_blocked' in metric_name:
                parsed['processes_blocked'] = int(value)

            # ===== SYSTEM METRICS =====
            elif 'node_boot_time_seconds' in metric_name:
                parsed['boot_time_seconds'] = int(value)
            elif 'node_context_switches_total' in metric_name:
                parsed['context_switches'] = int(value)
            elif 'node_intr_total' in metric_name:
                parsed['interrupts_total'] = int(value)

            # ===== LOAD METRICS (FIX) =====
            elif metric_name == 'node_load1':
                parsed['load_1min'] = value
            elif metric_name == 'node_load5':
                parsed['load_5min'] = value
            elif metric_name == 'node_load15':
                parsed['load_15min'] = value

            # ===== FILE DESCRIPTOR METRICS =====
            elif 'node_filefd_allocated' in metric_name:
                parsed['filefd_allocated'] = int(value)
            elif 'node_filefd_maximum' in metric_name:
                parsed['filefd_maximum'] = int(value)

            # ===== NETWORK CONNECTIONS =====
            elif 'node_sockstat_TCP_inuse' in metric_name:
                parsed['tcp_connections_inuse'] = int(value)
            elif 'node_sockstat_TCP_tw' in metric_name:
                parsed['tcp_connections_timewait'] = int(value)
            elif 'node_sockstat_UDP_inuse' in metric_name:
                parsed['udp_connections_inuse'] = int(value)

        except (ValueError, IndexError, KeyError):
            continue

    # ===== CALCULATE DERIVED METRICS =====

    # CPU Usage %
    cpu_usage = 0
    cpu_modes = parsed.get('cpu_modes', {})
    if cpu_modes:
        idle_total = sum(cpu_modes.get('idle', [0]))
        non_idle = sum(cpu_modes.get('user', [0])) + sum(cpu_modes.get('system', [0])) + \
                   sum(cpu_modes.get('iowait', [0])) + sum(cpu_modes.get('irq', [0])) + \
                   sum(cpu_modes.get('softirq', [0])) + sum(cpu_modes.get('steal', [0]))
        total = idle_total + non_idle
        if total > 0:
            cpu_usage = (non_idle / total) * 100

    # Memory calculations - FIXED
    mem_total = parsed.get('memory_total_bytes', 0)
    mem_available = parsed.get('memory_available_bytes', 0)
    mem_used = mem_total - mem_available if mem_total > 0 else 0
    mem_percent = (mem_used / mem_total * 100) if mem_total > 0 else 0

    mem_cached = parsed.get('memory_cached_bytes', 0)
    mem_buffers = parsed.get('memory_buffers_bytes', 0)

    # Swap calculations
    swap_total = parsed.get('swap_total_bytes', 0)
    swap_free = parsed.get('swap_free_bytes', 0)
    swap_used = swap_total - swap_free if swap_total > 0 else 0
    swap_percent = (swap_used / swap_total * 100) if swap_total > 0 else 0

    # Disk calculations
    disk_total = parsed.get('disk_total_bytes', 0)
    disk_available = parsed.get('disk_available_bytes', 0)
    disk_used = disk_total - disk_available if disk_total > 0 else 0
    disk_percent = (disk_used / disk_total * 100) if disk_total > 0 else 0

    disk_inodes_total = parsed.get('disk_inodes_total', 0)
    disk_inodes_free = parsed.get('disk_inodes_free', 0)
    disk_inodes_used = disk_inodes_total - disk_inodes_free if disk_inodes_total > 0 else 0
    disk_inodes_percent = (disk_inodes_used / disk_inodes_total * 100) if disk_inodes_total > 0 else 0

    # Uptime calculation
    import time
    boot_time = parsed.get('boot_time_seconds', 0)
    uptime_seconds = int(time.time()) - boot_time if boot_time > 0 else 0
    uptime_days = uptime_seconds / 86400
    uptime_hours = (uptime_seconds % 86400) / 3600

    # File descriptor usage
    filefd_allocated = parsed.get('filefd_allocated', 0)
    filefd_maximum = parsed.get('filefd_maximum', 1)
    filefd_percent = (filefd_allocated / filefd_maximum * 100) if filefd_maximum > 0 else 0

    return {
        "server": "postgres-1 (192.168.0.162)",
        "timestamp": time.time(),

        # CPU Section
        "cpu": {
            "usage_percent": round(cpu_usage, 2),
            "idle_percent": round(100 - cpu_usage, 2),
        },

        # Memory Section (SI units: GB = 1000^3)
        "memory": {
            "total_gb": round(mem_total / (1000**3), 2),
            "used_gb": round(mem_used / (1000**3), 2),
            "available_gb": round(mem_available / (1000**3), 2),
            "cached_gb": round(mem_cached / (1000**3), 2),
            "buffers_gb": round(mem_buffers / (1000**3), 2),
            "used_percent": round(mem_percent, 2),  # Keep this last
            "free_percent": round(100 - mem_percent, 2),
        },

        # Swap Section (SI units)
        "swap": {
            "total_gb": round(swap_total / (1000**3), 2),
            "used_gb": round(swap_used / (1000**3), 2),
            "free_gb": round(swap_free / (1000**3), 2),
            "used_percent": round(swap_percent, 2) if swap_total > 0 else 0,
        },

        # Disk Section (SI units)
        "disk": {
            "total_gb": round(disk_total / (1000**3), 2),
            "used_gb": round(disk_used / (1000**3), 2),
            "available_gb": round(disk_available / (1000**3), 2),
            "used_percent": round(disk_percent, 2),
            "inodes_total": int(disk_inodes_total),
            "inodes_used": int(disk_inodes_used),
            "inodes_free": int(disk_inodes_free),
            "inodes_used_percent": round(disk_inodes_percent, 2),
        },

        # Disk I/O Section (SI units)
        "disk_io": {
            "io_time": parsed.get('disk_io_time', {}),
            "reads": parsed.get('disk_reads', {}),
            "writes": parsed.get('disk_writes', {}),
            "read_bytes_gb": {k: round(v / (1000**3), 2) for k, v in parsed.get('disk_read_bytes', {}).items()},
            "written_bytes_gb": {k: round(v / (1000**3), 2) for k, v in parsed.get('disk_written_bytes', {}).items()},
        },

        # Network Section (SI units)
        "network": {
            "interfaces": {
                iface: {
                    "receive_gb": round(data.get('receive_bytes', 0) / (1000**3), 2),
                    "transmit_gb": round(data.get('transmit_bytes', 0) / (1000**3), 2),
                }
                for iface, data in parsed.get('network_interfaces', {}).items()
            },
            "receive_errors": int(parsed.get('network_receive_errors', 0)),
            "transmit_errors": int(parsed.get('network_transmit_errors', 0)),
            "receive_dropped": int(parsed.get('network_receive_dropped', 0)),
            "transmit_dropped": int(parsed.get('network_transmit_dropped', 0)),
        },
        
        # Process Section
        "processes": {
            "running": parsed.get('processes_running', 0),
            "blocked": parsed.get('processes_blocked', 0),
        },

        # System Section
        "system": {
            "uptime_days": round(uptime_days, 2),
            "uptime_hours": round(uptime_hours, 2),
            "context_switches": int(parsed.get('context_switches', 0)),
            "interrupts": int(parsed.get('interrupts_total', 0)),
        },

        # Load Section
        "load": {
            "1min": round(parsed.get('load_1min', 0), 2),
            "5min": round(parsed.get('load_5min', 0), 2),
            "15min": round(parsed.get('load_15min', 0), 2),
        },

        # File Descriptors Section
        "file_descriptors": {
            "allocated": int(parsed.get('filefd_allocated', 0)),
            "maximum": int(parsed.get('filefd_maximum', 0)),
            "used_percent": round(filefd_percent, 2),
        },

        # Network Connections Section
        "connections": {
            "tcp_inuse": int(parsed.get('tcp_connections_inuse', 0)),
            "tcp_timewait": int(parsed.get('tcp_connections_timewait', 0)),
            "udp_inuse": int(parsed.get('udp_connections_inuse', 0)),
        },
        "summary": {
            "memory_used_percent": round(mem_percent, 2),
            "memory_used_gb": round(mem_used / (1000**3), 2),
            "memory_total_gb": round(mem_total / (1000**3), 2),
        },
    }



@tool
def get_postgres1_top_processes(limit: int = 5) -> str:
    """Lists top CPU-consuming processes on postgres-1."""
    _debug(f"Fetching top {limit} processes from postgres-1")

    try:
        with httpx.Client(timeout=10.0, verify=False) as client:
            # Query node exporter for process metrics
            response = client.get("http://192.168.0.162:9100/metrics")
            metrics_text = response.text

            # Parse process metrics
            processes = {}
            for line in metrics_text.split('\n'):
                if 'node_processes_' in line or 'ps_' in line:
                    continue

            # Fallback: return top processes from /proc parsing
            return "Top processes on postgres-1:\n(Requires SSH access for detailed process info)\n\nYou can use: ps aux --sort=-%cpu | head -10"
    except Exception as e:
        return f"Error fetching process info: {str(e)}"


@tool
def check_postgres_health(host: str = "192.168.0.162", port: int = 5432) -> dict:
    """Check if PostgreSQL database server is responding on port 5432."""
    _debug(f"Checking PostgreSQL on {host}:{port}")
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return {
                "server": f"{host}:{port}",
                "status": "ONLINE",
                "service": "PostgreSQL",
                "message": "PostgreSQL is accepting connections"
            }
        else:
            return {
                "server": f"{host}:{port}",
                "status": "OFFLINE",
                "service": "PostgreSQL",
                "message": "PostgreSQL is not accepting connections on port 5432"
            }
    except Exception as e:
        return {
            "server": f"{host}:{port}",
            "status": "ERROR",
            "service": "PostgreSQL",
            "message": f"Connection error: {str(e)}"
        }

@tool
def check_postgres_exporter_health(host: str = "192.168.0.162", port: int = 9187) -> dict:
    """Check if Postgres exporter (metrics collector) is running on port 9187."""
    _debug(f"Checking Postgres exporter on {host}:{port}")
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return {
                "server": f"{host}:{port}",
                "status": "ONLINE",
                "service": "Postgres Exporter",
                "message": "Metrics exporter is running and accepting connections"
            }
        else:
            return {
                "server": f"{host}:{port}",
                "status": "OFFLINE",
                "service": "Postgres Exporter",
                "message": "Metrics exporter is not responding on port 9187"
            }
    except Exception as e:
        return {
            "server": f"{host}:{port}",
            "status": "ERROR",
            "service": "Postgres Exporter",
            "message": f"Connection error: {str(e)}"
        }
        
        
@tool
def check_internal_service_endpoint(url: str) -> dict:
    """Pings an internal service endpoint to check availability."""
    _debug(f"Checking endpoint: {url}")
    try:
        with httpx.Client(timeout=5.0, verify=False, follow_redirects=True) as client:
            response = client.get(url)
            is_online = response.status_code < 400  # Accept 2xx and 3xx
            return {
                "url": url,
                "status_code": response.status_code,
                "online": is_online,
                "message": "Online" if is_online else "Offline or unreachable"
            }
    except httpx.RequestError as exc:
        return {"url": url, "online": False, "error": str(exc), "message": "Connection failed"}

@tool
def get_memory_usage() -> dict:
    """Get only memory usage percentage. Simple and clear for the agent."""
    _debug("Fetching memory usage percentage")

    try:
        with httpx.Client(timeout=10.0, verify=False) as client:
            response = client.get("http://192.168.0.162:9100/metrics")
            metrics_text = response.text

            mem_total = 0
            mem_available = 0

            for line in metrics_text.split('\n'):
                if line.startswith('#') or not line.strip():
                    continue
                if 'node_memory_MemTotal_bytes' in line and '{' not in line:
                    mem_total = float(line.split()[-1])
                elif 'node_memory_MemAvailable_bytes' in line and '{' not in line:
                    mem_available = float(line.split()[-1])

            if mem_total > 0:
                used = mem_total - mem_available
                used_percent = (used / mem_total) * 100
                return {
                    "memory_used_percent": round(used_percent, 2),
                    "message": f"Memory usage is {round(used_percent, 2)}% of {round(mem_total / (1000**3), 2)} GB total"
                }
            else:
                return {"error": "Could not fetch memory metrics"}
    except Exception as e:
        return {"error": str(e)}


def get_tools() -> list:
    return [get_postgres1_node_metrics, get_postgres1_top_processes,
            check_internal_service_endpoint, check_postgres_health,
            check_postgres_exporter_health, get_memory_usage]
