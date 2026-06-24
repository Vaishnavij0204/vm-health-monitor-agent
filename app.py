
import os
import logging
import json
import re
from typing import Annotated, Sequence
from typing_extensions import TypedDict

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from langgraph.graph import END, StateGraph, START
from langgraph.prebuilt import ToolNode

from tools import (
    get_llm,
    get_node_metrics,
    get_postgres_health,
    get_postgres_connections,  # ← ADD THIS LINE
    get_top_processes,
    check_endpoint,
    get_disk_io_rate,
    get_memory_usage,
    get_postgres_metrics,
)


load_dotenv()
LOGGER = logging.getLogger("agent")

class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], lambda x, y: x + y]

def parse_tool_calls_from_text(text: str) -> list:
    """Extract tool calls from LLM text output in [TOOLS] ... [/TOOLS] format."""
    tool_calls = []

    # Look for [TOOLS_TO_CALL] ... [/TOOLS_TO_CALL] blocks
    match = re.search(r'\[TOOLS_TO_CALL\](.*?)\[/TOOLS_TO_CALL\]', text, re.DOTALL)

    if match:
        json_str = match.group(1).strip()
        try:
            data = json.loads(json_str)
            tools = data.get("tools", [])

            # Convert tool names to tool_call format
            for tool_name in tools:
                tool_calls.append({
                    "name": tool_name,
                    "args": {},
                    "id": f"call_{len(tool_calls)}"
                })

            print(f"✅ Parsed tool calls: {[tc['name'] for tc in tool_calls]}")
        except json.JSONDecodeError as e:
            print(f"⚠️  Failed to parse tool calls JSON: {e}")

    return tool_calls

def build_agent():
    """Build the ReAct agent with Qwen."""
    llm = get_llm()
    llm_with_tools = llm  # Qwen doesn't use bind_tools, we'll parse manually

    tools = [
    get_node_metrics,
    get_postgres_health,
    get_postgres_connections,
    get_top_processes,
    check_endpoint,
    get_disk_io_rate,
    get_memory_usage,
    get_postgres_metrics,
]

    def agent_node(state: AgentState):
        """LLM reasoning node — decides which tools to call."""
        messages = state["messages"]

        sys_message = SystemMessage(
    content=(
        "You are a postgres-1 (192.168.0.162) VM Health Monitoring Agent.\n"
        "Available tools:\n"
        "- get_node_metrics: CPU, memory, disk, load (call this ONCE per session)\n"
        "- get_postgres_health: PostgreSQL status\n"
        "- get_postgres_metrics: PostgreSQL details from exporter\n"
        "- get_top_processes: Top CPU/memory consuming processes\n"
        "- get_disk_io_rate: Disk read/write rates\n"
        "- get_memory_usage: Memory percentage only\n"
        "- check_endpoint: Service availability\n\n"
        "RULE: Only call each tool ONCE. Don't repeat.\n\n"
        "Output tool calls in this format:\n"
        "[TOOLS_TO_CALL]\n"
        '{"tools": ["tool1", "tool2"], "reasoning": "..."}\n'
        "[/TOOLS_TO_CALL]\n\n"
        "Strategy:\n"
        "1. 'server healthy?' → get_node_metrics + get_postgres_health (BOTH TOGETHER)\n"
        "2. 'cpu usage?' → get_node_metrics only\n"
        "3. 'why slow?' → get_node_metrics + get_top_processes\n"
        "4. 'disk high?' → get_node_metrics + get_disk_io_rate\n"
        "5. After getting results, SYNTHESIZE and STOP (no more tools)\n\n"
        "IMPORTANT: You have already called these tools if mentioned:\n"
        "- Previous tool calls are in the conversation history\n"
        "- Reuse those results, don't call again\n"
        "- Only call NEW tools if you need different data\n\n"
        "Be concise. Answer directly."
        "IMPORTANT: When asked about a specific postgres version:\n"
        "- get_postgres_health() returns the actual version detected\n"
        "- If version doesn't match what was asked, say it explicitly:\n"
        "  'PostgreSQL is running, but it's version X, not postgres-18'\n"
        "- Do NOT assume a version without data\n"
        "When asked about 'active connections', ALWAYS use get_postgres_connections.\n"
    )
)

        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [sys_message] + list(messages)

        response = llm_with_tools.invoke(messages)
        text = response.content

        # Parse tool calls from text
        tool_calls = parse_tool_calls_from_text(text)

        # Attach parsed tool calls to response
        response.tool_calls = tool_calls

        print(f"📝 LLM Output: {text[:150]}...")
        print(f"🔧 Tool calls extracted: {[tc['name'] for tc in tool_calls]}")

        return {"messages": [response]}

    def should_continue(state: AgentState):
        """Check if LLM has more tool calls to make."""
        last_message = state["messages"][-1]

        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            print(f"📞 Executing tools: {[tc['name'] for tc in last_message.tool_calls]}")
            return "tools"

        print("✅ Agent finished (no more tools)")
        return END

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node("tools", ToolNode(tools))

    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, {
        "tools": "tools",
        END: END
    })
    workflow.add_edge("tools", "agent")

    return workflow.compile()

app = build_agent()

def invoke_agent(user_query: str, history: list = None):
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

    # Extract final response (filter out tool calls markers)
    last_message = final_output["messages"][-1]
    response_text = last_message.content

    # Clean up tool call markers from final response
    response_text = re.sub(r'\[TOOLS_TO_CALL\].*?\[/TOOLS_TO_CALL\]', '', response_text, flags=re.DOTALL)
    response_text = response_text.strip()

    #print(f"\n🤖 Agent: {response_text}\n")

    history.append({"role": "user", "content": user_query})
    history.append({"role": "assistant", "content": response_text})

    return response_text, history

if __name__ == "__main__":
    history = []
    print("Health Monitor Agent (type 'exit' to quit)")
    print("Try: 'Is the server healthy?', 'Check disk usage', etc.\n")

    while True:
        user_input = input("You: ").strip()
        if user_input.lower() == "exit":
            break
        if not user_input:
            continue

        response, history = invoke_agent(user_input, history)