# VM Health Monitor

An intelligent VM health diagnostic assistant powered by LangGraph and LLMs. This agent proactively monitors Prometheus metrics and Loki logs to diagnose VM health issues, detect outages, and provide root-cause analysis in natural language.

## Overview

The VM Health Monitor is a LangGraph-based agent that:
- Continuously monitors VM metrics (CPU, memory, disk, network, load averages) from Prometheus
- Fetches error, kernel, and authentication logs from Loki
- Detects VM outages and downtime events
- Provides intelligent analysis and troubleshooting guidance via an LLM
- Operates with multiple LLM providers (Relusys, OpenAI, Google Gemini, Anthropic)

## Features

- **Real-Time Metrics**: Fetch current and historical CPU%, memory%, disk%, and network throughput from Prometheus
- **Log Analysis**: Query error logs, kernel logs, and authentication failure logs from Loki
- **Outage Detection**: Scan 6-hour history to detect VM crashes, downtime, and recovery events
- **Trend Analysis**: View metric trends over configurable time windows (1h, 3h, etc.)
- **Smart Context Injection**: Automatically fetches relevant VM data based on user intent
- **Web Search**: Integrates web search for current information (when using Relusys provider)
- **Multi-Provider Support**: Works with Relusys, OpenAI, Google Gemini, or Anthropic LLMs
- **Docker Deployment**: Ready-to-run containerized deployment
- **Proactive Analysis**: Injects freshly-fetched Prometheus/Loki data into prompts so the LLM always has ground truth

## Architecture

```
User Query
    ↓
app.py: invoke_agent()
    ↓
Intent Classification (metrics/outage/auth/trends)
    ↓
tools.py: augment_prompt_with_vm_context()
    ├─ Fetch current metrics (Prometheus)
    ├─ Fetch error logs (Loki)
    ├─ Detect outages (Prometheus up metric)
    ├─ Fetch kernel/auth logs (Loki)
    └─ Inject all data into system context
    ↓
LangGraph Agent (qwen3:8b via Relusys)
    ↓
LLM Analysis & Response
    ↓
Return answer + message history
```

## Requirements

- Python 3.9+
- Prometheus instance (for metrics)
- Loki instance (for logs)
- LLM Provider credentials (Relusys, OpenAI, Gemini, or Anthropic)
- Docker & Docker Compose (optional, for containerized deployment)

## Installation

### Local Setup

1. **Clone and navigate to the project**:
   ```bash
   cd vm-health_monitor
   ```

2. **Create and activate a Python virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Create a `.env` file** with your configuration (see Configuration section below)

### Docker Setup

Build and run with Docker Compose:
```bash
docker-compose up --build
```

The agent will be available at `http://localhost:8000`.

## Configuration

Create a `.env` file in the project root with the following variables:

### Core Configuration
```env
# LLM Provider: relusys, openai, gemini, anthropic
RCLOUD_PROVIDER=relusys

# Model override (defaults to qwen3:8b for relusys)
RCLOUD_MODEL_OVERRIDE=qwen3:8b

# Relusys Configuration
MODEL_SERVER_URL=http://your-model-server:8000/v1
MODEL_SERVER_TOKEN=your-api-token
MODEL_SERVER_VERIFY_SSL=false

# OR OpenAI Configuration
OPENAI_API_KEY=sk-...

# OR Google Gemini Configuration
GOOGLE_API_KEY=...

# OR Anthropic Configuration
ANTHROPIC_API_KEY=...
```

### Monitoring Configuration
```env
# Prometheus endpoint
PROMETHEUS_URL=http://localhost:9090

# Loki endpoint
LOKI_URL=http://localhost:3100

# VM instance filter (regex pattern)
# If set, only metrics from matching instances are queried
VM_INSTANCE=prod-vm-01

# Debug mode
RCLOUD_DEBUG_TOOLS=false
```

### Server Configuration
```env
HOST=0.0.0.0
PORT=8000
```

## Usage

### Python API

```python
from app import invoke_agent

# Single query
answer, history = invoke_agent("What is the current CPU usage?")
print(answer)

# Multi-turn conversation
history = []
while True:
    query = input("Ask about VM health: ")
    answer, history = invoke_agent(query, history)
    print(f"Agent: {answer}\n")
```

### Dev Mode

```bash
python dev.py
```

Starts an interactive shell for multi-turn conversations with the agent.

### Docker

```bash
docker-compose up
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Is the VM healthy?"}'
```

## Tools

### Metric Tools

- **`get_current_metrics()`**: Fetch point-in-time health metrics (CPU%, memory%, disk%, load, network)
- **`get_metric_trends(hours=1.0)`**: Fetch CPU/memory/disk trends over N hours, sampled every 60 seconds

### Log Analysis Tools

- **`get_error_logs(hours=1.0)`**: Query error-level log lines from syslog/systemd
- **`get_kernel_logs(hours=1.0)`**: Query kernel logs (OOM kills, hardware errors, panics)
- **`get_auth_logs(hours=1.0)`**: Query authentication failure logs

### Diagnostic Tools

- **`detect_outage()`**: Scan 6 hours of 'up' metric to find when VM went down and when it recovered

### Utility Tools

- **`web_search(query)`**: Search the web for current information (Relusys provider only)
- **`calculator(expression)`**: Evaluate mathematical expressions

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `RCLOUD_DEBUG_TOOLS` | `false` | Enable debug logging |
| `RCLOUD_MODEL_OVERRIDE` | `qwen3:8b` | LLM model name |
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus endpoint |
| `LOKI_URL` | `http://localhost:3100` | Loki endpoint |
| `VM_INSTANCE` | `` (empty) | VM instance filter regex |
| `MODEL_SERVER_URL` | `{{MODEL_SERVER_URL}}` | Model server URL (Relusys) |
| `MODEL_SERVER_TOKEN` | `{{MODEL_SERVER_TOKEN}}` | Model server API token |
| `MODEL_SERVER_VERIFY_SSL` | `false` | Verify SSL certificates |
| `HOST` | `0.0.0.0` | Server host address |
| `PORT` | `8000` | Server port |

## Examples

### Check Current VM Health
```
User: "Is my VM healthy?"

Agent analyzes:
- Current CPU%, memory%, disk% from Prometheus
- Recent error logs from Loki
- VM up/down status

Response: "Your VM is running healthy with 42% CPU usage, 68% memory utilization, 
and 55% disk usage. No errors detected in the last hour."
```

### Diagnose an Outage
```
User: "Why did my VM go down 2 hours ago?"

Agent fetches:
- Outage detection (when it went down)
- 3-hour metric trends (leading up to the outage)
- 3-hour error, kernel, and auth logs

Response: "Your VM went down at 14:23 UTC due to an Out-Of-Memory (OOM) condition. 
Memory usage climbed to 95% over 30 minutes before the system was killed. 
The kernel log shows: '[kernel] Out of memory: Kill process...'"
```

### Performance Analysis
```
User: "Show me CPU and memory trends over the last 3 hours"

Agent returns:
- Hourly CPU% and memory% samples over 3 hours
- Identifies periods of high utilization
- Correlates with any error events in logs

Response: "CPU usage was stable around 30% for the first 2 hours, 
then spiked to 85% at 14:50 UTC and remained high for 20 minutes. 
Memory remained steady at 60-70% throughout."
```

## Project Structure

```
vm-health_monitor/
├── app.py              # LangGraph agent & entry point
├── tools.py            # VM health tools & Prometheus/Loki queries
├── config.py           # Configuration management
├── agent.py            # Agent orchestration (if present)
├── dev.py              # Development/interactive shell
├── requirements.txt    # Python dependencies
├── pyproject.toml      # Project metadata
├── Dockerfile          # Container image definition
├── docker-compose.yml  # Docker Compose configuration
└── README.md           # This file
```

## Troubleshooting

### "Search error" or empty results
- Verify `PROMETHEUS_URL` and `LOKI_URL` are correctly configured
- Check that Prometheus and Loki instances are reachable and running
- Ensure metrics are being scraped and logs are being shipped

### Model not responding
- Verify LLM provider credentials in `.env`
- Check `MODEL_SERVER_URL` and `MODEL_SERVER_TOKEN` for Relusys
- Enable debug mode: `RCLOUD_DEBUG_TOOLS=true`

### No data from VM instance
- Set `VM_INSTANCE` env var to match your VM's Prometheus instance label
- Verify the `job="vm-node"` label exists in Prometheus for your VM

### SSL Certificate Errors
- Set `MODEL_SERVER_VERIFY_SSL=false` if using self-signed certificates
- Or provide proper CA certificates for `httpx.Client`


