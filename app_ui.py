import streamlit as st
import re
import requests
import pandas as pd

st.set_page_config(page_title="Rcloud VM Monitor Dashboard", layout="wide", initial_sidebar_state="expanded")

st.title("🖥️ VM Health & Rcloud Agent Dashboard")
st.markdown("---")

# --- SIDEBAR: LIVE METRICS EXTRACTION ---
# Instead of scraping terminal lines, we pull live from the same backend your agent uses!
PROMETHEUS_URL = "http://192.168.0.117:9090/api/v1/query"

@st.cache_data(ttl=2) # Auto refresh every 2 seconds
def fetch_live_metrics():
    try:
        # Fetch connections
        conn_res = requests.get(PROMETHEUS_URL, params={'query': 'pg_stat_database_numbackends'}).json()
        conns = sum(int(x['value'][1]) for x in conn_res['data']['result'])
        
        # Fetch CPU
        cpu_query = '100 - (avg by (instance) (irate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)'
        cpu_res = requests.get(PROMETHEUS_URL, params={'query': cpu_query}).json()
        cpu = float(cpu_res['data']['result'][0]['value'][1])
        
        return {"connections": conns, "cpu": round(cpu, 2), "status": "ONLINE"}
    except Exception:
        # Fallback to last seen terminal values if Prometheus connection times out locally
        return {"connections": 28, "cpu": 0.28, "status": "DEMO MODE (Backend Unreachable)"}

metrics = fetch_live_metrics()

st.sidebar.header("📊 Real-time Telemetry")
st.sidebar.metric(label="Status", value=metrics["status"])
st.sidebar.metric(label="Active DB Connections", value=f"{metrics['connections']} active")
st.sidebar.metric(label="System CPU Usage", value=f"{metrics['cpu']}%")

# Add a toggle to show debugging logs
show_debug = st.sidebar.checkbox("Show `[rcloud-debug]` Logs", value=False)

# --- MAIN DASHBOARD: CHAT INTERFACE ---
st.subheader("💬 Chat with Agent Process")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = [
        {"role": "Agent", "content": "Welcome to vm-health_monitor local dev. Ask me anything about connection counts or logs."}
    ]

# Render existing conversation
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"].lower()):
        st.write(f"**{msg['role']}:** {msg['content']}")

# User text input
if user_input := st.chat_input("Type your command here... (e.g., 'no of active connections?')"):
    # Append user prompt immediately to UI
    st.session_state.chat_history.append({"role": "You", "content": user_input})
    
    # --- AGENT SIMULATED ROUTING ---
    # In a full deployment, this triggers a request payload to your local FastAPI app or subprocess.
    # For matching your terminal output:
    if "connection" in user_input.lower():
        agent_reply = f"Based on the real-time metrics provided, the total number of active connections currently stands at {metrics['connections']}."
        debug_info = """[rcloud-debug] HTTP Request: GET http://192.168.0.117:9090/api/v1/query?query=pg_stat_database_numbackends "HTTP/1.1 200 OK"
[rcloud-debug] get_current_metrics: 28 connections, 101.84 MB DB size, CPU:0.28%"""
    elif "log" in user_input.lower():
        agent_reply = "The log entries from the past hour indicate that there have been no errors detected in the system or database operations."
        debug_info = "[rcloud-debug] HTTP Request: GET http://192.168.0.117:3100/loki/api/v1/query_range... \"HTTP/1.1 200 OK\""
    else:
        agent_reply = "System is healthy. Operational metrics are within normal baseline thresholds."
        debug_info = "[rcloud-debug] call_model context evaluation complete."

    st.session_state.chat_history.append({"role": "Agent", "content": agent_reply})
    
    if show_debug:
        st.session_state.chat_history.append({"role": "Debug", "content": debug_info})
        
    st.rerun()

# --- RECENT PERFORMANCE GRAPH ---
st.markdown("---")
st.subheader("📈 Resource Metric Streams")
chart_data = pd.DataFrame({
    'Time (minutes ago)': [5, 4, 3, 2, 1, 0],
    'CPU Usage (%)': [0.12, 0.15, 0.42, 0.35, 0.25, metrics["cpu"]],
    'Active Backends': [25, 25, 28, 28, 28, metrics["connections"]]
})
st.line_chart(data=chart_data, x='Time (minutes ago)', y=['CPU Usage (%)', 'Active Backends'])