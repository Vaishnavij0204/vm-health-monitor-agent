VM Health Monitor - LLM-Based Agent

A fully LLM-based autonomous agent that monitors PostgreSQL VM health, system metrics, and database performance in real-time using natural language queries.

🎯 What It Does

Instead of running manual commands, just ask questions in natural language:

You: cpu usage?
Agent: The CPU usage is currently at 0.24%. This is a low percentage, indicating the system is not under heavy load.

You: why is the system slow?
Agent: The system load is 2x higher than baseline. This indicates a significant increase in load, potentially causing slowness.

You: memory trends over 2 hours
Agent: Memory usage has remained stable over the past 2 hours, ranging from 11.5% to 12.5%.

The agent autonomously decides which monitoring tools to use based on your question.

✅ YES - It's Fully LLM-Based!

Here's the exact flow:

1. User asks: "cpu usage?" (natural language)
2. LLM decides: "I need CPU metrics, so I'll call TOOL_CALL: get_node_metrics"
3. Agent executes: Calls Prometheus to get real-time data
4. LLM analyzes: Receives {"cpu_percent": 0.24, "memory": {...}}
5. LLM responds: "CPU is 0.24%. Memory is 11.81%. System is healthy."

The LLM is the decision-maker - it understands user intent, decides which tools to use, and generates insights.

📊 Architecture

User Query (Natural Language)
    ↓
LLM (Qwen3.6:27b) - Understands & Decides
    ↓
LLM outputs: "TOOL_CALL: get_node_metrics"
    ↓
Agent - Parses & Executes Tool
    ↓
Tool gets Real Data from Prometheus
    ↓
LLM Analyzes Results
    ↓
Natural Language Response with Insights

🔧 Available Tools (LLM Can Call)

┌──────────────────────────┬───────────────────┬──────────────────────┐
│           Tool           │      Purpose      │    Example Query     │
├──────────────────────────┼───────────────────┼──────────────────────┤
│ get_node_metrics         │ CPU, memory,      │ "cpu usage?",        │
│                          │ disk, load        │ "system metrics?"    │
├──────────────────────────┼───────────────────┼──────────────────────┤
│ get_postgres_health      │ PostgreSQL        │ "postgres status?",  │
│                          │ running status    │ "is db up?"          │
├──────────────────────────┼───────────────────┼──────────────────────┤
│ get_postgres_connections │ Active/idle       │ "connection stats?", │
│                          │ connections       │  "db load?"          │
├──────────────────────────┼───────────────────┼──────────────────────┤
│                          │ Historical trends │ "cpu trends?",       │
│ get_metric_trends        │  (1-24 hrs)       │ "memory over 2       │
│                          │                   │ hours?"              │
├──────────────────────────┼───────────────────┼──────────────────────┤
│ detect_anomalies         │ Find unusual      │ "any anomalies?",    │
│                          │ patterns          │ "problems?"          │
├──────────────────────────┼───────────────────┼──────────────────────┤
│ debug_issue              │ Root cause        │ "why is it slow?",   │
│                          │ analysis          │ "debug"              │
└──────────────────────────┴───────────────────┴──────────────────────┘

🚀 Quick Start

cd ~/Rcloud_CLI/vm-health_monitor
source .env
rcloud agent dev

Then ask questions:
You: cpu usage?
Agent: The CPU usage is currently at 0.24%. System is healthy.

You: postgres status?
Agent: PostgreSQL status is ONLINE and accepting connections.

You: are there anomalies?
Agent: No anomalies detected. Overall health is HEALTHY.

📁 Files

- agent.py - LLM agent (decides what tools to use)
- tools.py - Monitoring functions (queries Prometheus, PostgreSQL)
- .env - Configuration (MODEL_SERVER_URL, PROMETHEUS_URL, etc)

🔌 Configuration

.env variables needed:
MODEL_SERVER_URL=https://m-serv1.relusys.lan/v1
MODEL_SERVER_TOKEN=your_token
MODEL_NAME=qwen3.6:27b
PROMETHEUS_URL=http://192.168.0.117:9090
LOKI_URL=http://192.168.0.117:3100
VM_INSTANCE=192.168.0.162:9187
DEBUG_TOOLS=true

💡 Key Points

✅ Fully LLM-Based - LLM decides everything
✅ Real Data - Gets actual metrics from Prometheus
✅ Autonomous - No manual tool selection needed
✅ Natural Language - Ask questions in English
✅ Intelligent - LLM analyzes patterns and trends
✅ Conversation Aware - Remembers context

📊 Example Queries & Responses

You: cpu usage?
Agent: CPU is 0.24%, very low. System not under heavy load.

You: postgres status?
Agent: PostgreSQL ONLINE on port 5432, accepting connections.

You: memory trends over 2 hours
Agent: Memory stable at 11-12% usage, no concerning trend.

You: why is system slow?
Agent: System load 2x higher than baseline (0.09). Check background processes.

You: are there anomalies?
Agent: No anomalies detected. System HEALTHY overall.

🛠️ How It Works (Technical)

1. User enters query → Agent receives it
2. System prompt tells LLM about available tools
3. LLM reads the query and decides: "I need get_node_metrics"
4. LLM outputs: TOOL_CALL: get_node_metrics
5. Agent parses TOOL_CALL: and executes the tool
6. Tool queries Prometheus/PostgreSQL, returns real data
7. Agent sends tool result back to LLM
8. LLM analyzes the real data and writes response
9. User gets insight based on actual metrics

Zero hallucination - every response uses real tool results.

---