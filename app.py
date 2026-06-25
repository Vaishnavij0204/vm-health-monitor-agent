import os
import json
import re
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from tools import (
    get_llm,
    _get_node_metrics_impl,
    _get_postgres_health_impl,
    _get_postgres_connections_impl,
    _get_metric_trends_impl,
    _detect_anomalies_impl,
    _debug_issue_impl,
)

load_dotenv()
llm = get_llm()

SYSTEM_PROMPT = """You are a monitoring agent. Answer questions by calling tools.

When the user asks a question:
1. Decide which tool you need
2. Say: TOOL_CALL: tool_name
   OR: TOOL_CALL: tool_name:arg1:arg2
3. Wait for the result
4. Answer the user question using the result

Tools:
- TOOL_CALL: get_node_metrics          → CPU, memory, disk, load
- TOOL_CALL: get_postgres_health       → PostgreSQL status
- TOOL_CALL: get_postgres_connections  → Connection stats
- TOOL_CALL: get_metric_trends:cpu:2   → CPU trend (metric:hours)
- TOOL_CALL: detect_anomalies          → Find problems
- TOOL_CALL: debug_issue:why is it slow → Root cause

Examples:
User: "cpu usage?"
You: "I'll check. TOOL_CALL: get_node_metrics"

User: "postgres up?"
You: "I'll verify. TOOL_CALL: get_postgres_health"

User: "memory trends?"
You: "Checking. TOOL_CALL: get_metric_trends:memory:2"

Then respond with actual results and analysis.
"""

def execute_tool(tool_spec):
    """Execute a tool."""
    parts = tool_spec.split(":")
    tool_name = parts[0]

    try:
        if tool_name == "get_node_metrics":
            return _get_node_metrics_impl()
        elif tool_name == "get_postgres_health":
            return _get_postgres_health_impl()
        elif tool_name == "get_postgres_connections":
            return _get_postgres_connections_impl()
        elif tool_name == "get_metric_trends":
            metric = parts[1] if len(parts) > 1 else "cpu"
            hours = int(parts[2]) if len(parts) > 2 else 1
            return _get_metric_trends_impl(metric, hours)
        elif tool_name == "detect_anomalies":
            return _detect_anomalies_impl()
        elif tool_name == "debug_issue":
            problem = ":".join(parts[1:]) if len(parts) > 1 else "unknown"
            return _debug_issue_impl(problem)
        else:
            return {"error": f"Unknown tool: {tool_name}"}
    except Exception as e:
        return {"error": str(e)}

def invoke_agent(user_query: str, history: list = None, *args, **kwargs):
    """Simple agent loop - fresh tool call each time."""
    if history is None:
        history = []

    # Fresh context - system prompt + minimal history
    messages = [SystemMessage(content=SYSTEM_PROMPT)]

    # Only add previous user questions (not answers) to provide context
    for i in range(len(history) - 4, len(history), 2):
        if i >= 0 and i < len(history):
            if history[i].get("role") == "user":
                messages.append(HumanMessage(content=history[i]["content"]))

    # Current query with MANDATORY tool instruction
    query_with_instruction = f"""{user_query}

IMPORTANT: You MUST call exactly one tool for this question. Include TOOL_CALL: in your response."""

    messages.append(HumanMessage(content=query_with_instruction))

    print(f"\n👤 User: {user_query}")

    # Call LLM - expect tool call
    response = llm.invoke(messages)
    response_text = response.content

    print(f"🤖 LLM: {response_text[:200]}")

    # Look for TOOL_CALL: pattern
    tool_match = re.search(r'TOOL_CALL:\s*(\S+)', response_text)

    if not tool_match:
        print(f"⚠️ No tool found in: {response_text[:100]}")
        # Try again with stronger instruction
        print(f"🔄 Retrying with stronger instruction...")
        messages[-1] = HumanMessage(content=f"""{user_query}

You MUST include TOOL_CALL: followed by the tool name. Examples:
- TOOL_CALL: get_node_metrics
- TOOL_CALL: get_metric_trends:cpu:2
- TOOL_CALL: get_postgres_health

Do not answer without calling a tool.""")
        response = llm.invoke(messages)
        response_text = response.content
        tool_match = re.search(r'TOOL_CALL:\s*(\S+)', response_text)

    if tool_match:
        tool_spec = tool_match.group(1)
        print(f"🔧 Executing: {tool_spec}")

        tool_result = execute_tool(tool_spec)

        if "error" in tool_result:
            print(f"❌ {tool_result['error']}")
            final_answer = f"Error: {tool_result['error']}"
        else:
            print(f"✅ Got result: {json.dumps(tool_result)[:80]}...")

            # Ask LLM to provide final answer with tool results
            messages.append(AIMessage(content=response_text))
            analysis_prompt = f"""Tool result: {json.dumps(tool_result)}

Based on this tool result, provide a clear answer to the user's question: {user_query}

Include specific numbers, percentages, and status values from the tool result."""

            messages.append(HumanMessage(content=analysis_prompt))
            final_response = llm.invoke(messages)
            final_answer = final_response.content
            print(f"📊 Answer: {final_answer[:200]}")
    else:
        print(f"❌ Failed to get tool call")
        final_answer = response_text

    # Save to history - clean format
    history.append({"role": "user", "content": user_query})
    history.append({"role": "assistant", "content": final_answer})

    return final_answer, history