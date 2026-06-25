import os
import logging
from typing import Annotated, Sequence
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from tools import (
    get_llm,
    get_node_metrics,
    get_postgres_health,
    get_postgres_connections,
    check_endpoint,
    get_metric_trends,
    detect_anomalies,
    debug_issue,
    get_tools
)

load_dotenv()
LOGGER = logging.getLogger("agent")

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]

llm = get_llm()
tools = get_tools()
llm_with_tools = llm.bind_tools(tools)


def call_model(state: AgentState):
    """Call LLM with tool binding."""
    messages = state["messages"]

    sys_message = SystemMessage(
        content=(
            "You are a postgres-1 VM Health Monitoring Agent with advanced debugging capabilities.\n"
            "You have access to tools for:\n"
            "- Real-time system metrics (CPU, memory, disk, load)\n"
            "- PostgreSQL health and connection status\n"
            "- Historical trends and pattern analysis\n"
            "- Anomaly detection and root cause analysis\n"
            "- Deep debugging of system issues\n\n"
            "When users ask about performance, health, or issues:\n"
            "1. Use appropriate tools to gather data\n"
            "2. Analyze trends and patterns\n"
            "3. Detect anomalies\n"
            "4. Provide root cause analysis\n"
            "5. Give actionable recommendations\n\n"
            "Be concise but thorough. Focus on insights, not raw data."
        )
    )

    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [sys_message] + list(messages)

    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState):
    """Check if tools should be called."""
    last_message = state["messages"][-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


# Build the graph
workflow = StateGraph(AgentState)

workflow.add_node("agent", call_model)
workflow.add_node("tools", ToolNode(tools))

workflow.add_edge(START, "agent")

workflow.add_conditional_edges(
    "agent",
    should_continue,
    {
        "tools": "tools",
        END: END
    }
)

workflow.add_edge("tools", "agent")

app = workflow.compile()


def invoke_agent(user_query: str, history: list = None, *args, **kwargs):
    """Invoke the agent with conversation history."""
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

    #print(f"\n🤖 Agent: {response_text}\n")

    history.append({"role": "user", "content": user_query})
    history.append({"role": "assistant", "content": response_text})

    return response_text, history