
import os
import logging
from typing import Annotated, Sequence
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import END, StateGraph, START

from tools import (
    get_llm,
    get_memory_usage,
    get_postgres1_node_metrics,
    get_postgres1_top_processes,
    check_internal_service_endpoint,
    check_postgres_health,
    check_postgres_exporter_health
)


load_dotenv()
LOGGER = logging.getLogger("rcloud.agent")

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]

llm = get_llm()

def estimate_tokens(text: str) -> int:
    """Rough estimate: ~1 token per 4 characters"""
    return max(1, len(text) // 4)


def call_model(state: AgentState):
    """Call Qwen with instructions to print command keywords."""
    messages = state["messages"]

    sys_message = SystemMessage(
        content=(
            "You are a postgres-1 (192.168.0.162) VM Health Monitoring Agent.\n"
            "You ONLY monitor the postgres-1 server at 192.168.0.162.\n\n"
            "To gather system information, print EXACTLY one of these command keywords on its own line:\n\n"
            "1. GET_POSTGRES1_METRICS - For: CPU, memory, disk, network, load, connections, uptime, processes\n"
            "2. GET_TOP_PROCESSES - For: top processes consuming resources\n"
            "3. CHECK_ENDPOINT http://URL - For: HTTP services (web, APIs, etc)\n"
            "4. CHECK_POSTGRES_HEALTH - For: checking if PostgreSQL database is running on 192.168.0.162:5432\n"
            "5. CHECK_POSTGRES_EXPORTER - For: checking if postgres metrics exporter is running on 192.168.0.162:9187\n\n"
            "6. GET_MEMORY_USAGE - For: memory usage percentage only (simple and clear)\n"
            "ROUTING GUIDE:\n"
            "- 'is postgres running?' → CHECK_POSTGRES_HEALTH\n"
            "- 'is postgres exporter running?' → CHECK_POSTGRES_EXPORTER\n"
            "- 'is prometheus running?' → CHECK_ENDPOINT http://192.168.0.117:9090\n"
            "- Other servers → Say: 'I only monitor postgres-1. Specify the IP/endpoint.'\n\n"
            "Answer ONLY what was asked, be brief."
            "After receiving the tool output, answer ONLY what was asked. Be concise.\n"
            "For memory: always report the 'used_percent' field, not 'used_gb'\n"
            "When reporting memory: use the 'summary' section with 'memory_used_percent' field.\n"
            "For memory usage question, report: 'Memory usage is X%' where X is from memory_used_percent.\n"
        )
    )

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [sys_message] + list(messages)

    response = llm.invoke(messages)
    return {"messages": [response]}


def text_router(state: AgentState):
    """Route based on text output from Qwen."""
    last_message = state["messages"][-1]
    text = last_message.content if last_message.content else ""

    if "GET_POSTGRES1_METRICS" in text:
        return "execute_metrics"
    elif "GET_TOP_PROCESSES" in text:
        return "execute_processes"
    elif "CHECK_POSTGRES_HEALTH" in text:
        return "execute_postgres_check"
    elif "CHECK_POSTGRES_EXPORTER" in text:
        return "execute_exporter_check"
    elif "CHECK_ENDPOINT" in text:
        return "execute_endpoint"
    elif "GET_MEMORY_USAGE" in text:
        return "execute_memory"

    return END


def run_metrics_tool(state: AgentState):
    """Execute the metrics tool with visibility."""
    tool_name = "get_postgres1_node_metrics"
    print(f"\n🔧 Tool Called: {tool_name}")
    print(f"📋 Purpose: Fetching comprehensive system metrics (CPU, memory, disk, network, load)")
    print(f"⏳ Executing...\n")

    LOGGER.info(f"🔧 Executing: {tool_name}")
    result = get_postgres1_node_metrics.invoke({})

    import time; time.sleep(2)

    print(f"✅ Tool executed successfully\n")

    tool_msg = ToolMessage(
        content=f"Tool Output:\n{str(result)}",
        name=tool_name,
        tool_call_id="text_routing"
    )
    return {"messages": [tool_msg]}

def run_processes_tool(state: AgentState):
    """Execute the top processes tool with visibility."""
    tool_name = "get_postgres1_top_processes"
    print(f"\n🔧 Tool Called: {tool_name}")
    print(f"📋 Purpose: Fetching top CPU consuming processes")
    print(f"⏳ Executing...\n")

    LOGGER.info(f"🔧 Executing: {tool_name}")
    result = get_postgres1_top_processes.invoke({"limit": 5})

    import time; time.sleep(2)

    print(f"✅ Tool executed successfully\n")

    tool_msg = ToolMessage(
        content=f"Tool Output:\n{result}",
        name=tool_name,
        tool_call_id="text_routing"
    )
    return {"messages": [tool_msg]}

def run_memory_tool(state: AgentState):
    tool_name = "get_memory_usage"
    print(f"\n🔧 Tool Called: {tool_name}")
    print(f"⏳ Executing...\n")

    result = get_memory_usage.invoke({})

    import time; time.sleep(1)
    print(f"✅ Tool executed successfully\n")

    tool_msg = ToolMessage(
        content=f"{result['message']}",
        name=tool_name,
        tool_call_id="text_routing"
    )
    return {"messages": [tool_msg]}


def run_postgres_check(state: AgentState):
    """Check if PostgreSQL is running."""
    tool_name = "check_postgres_health"
    print(f"\n🔧 Tool Called: {tool_name}")
    print(f"🌐 Target: 192.168.0.162:5432")
    print(f"⏳ Executing...\n")

    LOGGER.info(f"🔧 Executing: {tool_name}")
    result = check_postgres_health.invoke({})

    import time; time.sleep(2)

    status = "🟢 ONLINE" if result.get("status") == "ONLINE" else "🔴 OFFLINE"
    print(f"✅ Tool executed successfully")
    print(f"📊 Status: {status}\n")

    tool_msg = ToolMessage(
        content=f"Tool Output:\n{str(result)}",
        name=tool_name,
        tool_call_id="text_routing"
    )
    return {"messages": [tool_msg]}

def run_exporter_check(state: AgentState):
    """Check if Postgres exporter is running."""
    tool_name = "check_postgres_exporter_health"
    print(f"\n🔧 Tool Called: {tool_name}")
    print(f"🌐 Target: 192.168.0.162:9187")
    print(f"⏳ Executing...\n")

    LOGGER.info(f"🔧 Executing: {tool_name}")
    result = check_postgres_exporter_health.invoke({})

    import time; time.sleep(2)

    status = "🟢 ONLINE" if result.get("status") == "ONLINE" else "🔴 OFFLINE"
    print(f"✅ Tool executed successfully")
    print(f"📊 Status: {status}\n")

    tool_msg = ToolMessage(
        content=f"Tool Output:\n{str(result)}",
        name=tool_name,
        tool_call_id="text_routing"
    )
    return {"messages": [tool_msg]}


def run_endpoint_tool(state: AgentState):
    """Execute the endpoint check tool with visibility."""
    last_message = state["messages"][-1]
    text = last_message.content

    url = None
    for line in text.split('\n'):
        if 'http' in line.lower():
            url = line.split()[-1]
            break

    if not url:
        url = "http://192.168.0.162:9100"

    tool_name = "check_internal_service_endpoint"
    print(f"\n🔧 Tool Called: {tool_name}")
    print(f"🌐 Target: {url}")
    print(f"⏳ Executing...\n")

    LOGGER.info(f"🔧 Executing: {tool_name} for {url}")
    result = check_internal_service_endpoint.invoke({"url": url})

    import time; time.sleep(2)

    print(f"✅ Tool executed successfully\n")

    tool_msg = ToolMessage(
        content=f"Tool Output:\n{str(result)}",
        name=tool_name,
        tool_call_id="text_routing"
    )
    return {"messages": [tool_msg]}

# Build graph
workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("execute_metrics", run_metrics_tool)
workflow.add_node("execute_processes", run_processes_tool)
workflow.add_node("execute_endpoint", run_endpoint_tool)
workflow.add_node("execute_postgres_check", run_postgres_check)
workflow.add_node("execute_exporter_check", run_exporter_check)
workflow.add_node("execute_memory", run_memory_tool)
workflow.add_edge("execute_memory", "agent")

workflow.add_edge(START, "agent")

workflow.add_conditional_edges(
    "agent",
    text_router,
    {
        "execute_metrics": "execute_metrics",
        "execute_processes": "execute_processes",
        "execute_endpoint": "execute_endpoint",
        "execute_postgres_check": "execute_postgres_check",
        "execute_exporter_check": "execute_exporter_check",
        "execute_memory": "execute_memory",
        END: END
    }
)

workflow.add_edge("execute_metrics", "agent")
workflow.add_edge("execute_processes", "agent")
workflow.add_edge("execute_endpoint", "agent")
workflow.add_edge("execute_postgres_check", "agent")
workflow.add_edge("execute_exporter_check", "agent")
workflow.add_edge("execute_memory", "agent")

app = workflow.compile()

def invoke_agent(user_query: str, history: list = None, *args, **kwargs):
    """Invoke the agent with conversation history and token counting."""
    if history is None:
        history = []

    messages = []
    for msg in history:
        if isinstance(msg, dict):
            if msg.get("role") == "user":
                messages.append(HumanMessage(content=msg["content"]))
            elif msg.get("role") == "assistant":
                messages.append(AIMessage(content=msg["content"]))
        else:
            messages.append(msg)

    #print(f"\n👤 You: {user_query}")
    messages.append(HumanMessage(content=str(user_query)))

    final_output = app.invoke({"messages": messages})

    last_message = final_output["messages"][-1]
    response_text = last_message.content

    # Calculate total tokens
    all_text = user_query + response_text + str([m.content for m in messages if hasattr(m, 'content')])
    total_tokens = estimate_tokens(all_text)

    #print(f"\n🤖 Agent: {response_text}")
    
    print(f"\n💾 Total tokens: ~{total_tokens}\n")

    history.append({"role": "user", "content": user_query})
    history.append({"role": "assistant", "content": response_text})

    return response_text, history