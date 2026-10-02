import os
import sys
import json
import asyncio
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------------------------------------------------------
# Load environment variables
# ---------------------------------------------------------

load_dotenv()


client = OpenAI(
    api_key=os.getenv("GAPGPT_API_KEY"),
    base_url=os.getenv("GAPGPT_BASE_URL")
)

MODEL = os.getenv("GAPGPT_MODEL")


# ---------------------------------------------------------
# Convert MCP tools to LLM-compatible tools
# ---------------------------------------------------------

def convert_mcp_tools(mcp_tools):

    llm_tools = []

    for tool in mcp_tools:

        llm_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            }
        )

    return llm_tools


# ---------------------------------------------------------
# Execute MCP tool
# ---------------------------------------------------------

async def execute_tool(
    session,
    tool_name,
    arguments
):

    print(f"\n[Tool Call] {tool_name}")
    print(f"[Arguments] {arguments}")

    result = await session.call_tool(
        tool_name,
        arguments=arguments
    )

    result_text = ""

    for block in result.content:

        if hasattr(block, "text"):
            result_text += block.text

    print(f"[Tool Result] {result_text}")

    return result_text


# ---------------------------------------------------------
# Agent loop
# ---------------------------------------------------------

async def run_agent(
    session,
    llm_tools,
    user_query,
    max_iterations=10
):

    messages = [
        {
            "role": "system",
            "content": (
                "You are a research assistant with access to MCP tools. "
                "You can search arXiv, inspect paper details, save papers "
                "to a reading list, list saved papers, update reading status, "
                "and add notes. "
                "Use tools whenever they are needed. "
                "You may call multiple tools across multiple iterations. "
                "Never invent paper IDs or tool results. "
                "Use only information returned by tools. "
                "When the task is complete, provide a concise final answer."
            )
        },
        {
            "role": "user",
            "content": user_query
        }
    ]

    for iteration in range(max_iterations):

        print(
            f"\n========== Agent Iteration {iteration + 1} =========="
        )

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=llm_tools
        )

        assistant_message = (
            response
            .choices[0]
            .message
        )

        # -------------------------------------------------
        # No tool call -> final answer
        # -------------------------------------------------

        if not assistant_message.tool_calls:

            print("\nAssistant:")
            print(assistant_message.content)

            return

        # Preserve assistant tool request
        messages.append(
            assistant_message
        )

        # -------------------------------------------------
        # Execute requested tools
        # -------------------------------------------------

        for tool_call in assistant_message.tool_calls:

            tool_name = (
                tool_call
                .function
                .name
            )

            arguments = json.loads(
                tool_call
                .function
                .arguments
            )

            result_text = await execute_tool(
                session=session,
                tool_name=tool_name,
                arguments=arguments
            )

            # Return tool result to LLM
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result_text
                }
            )

    print(
        "\nAgent stopped because maximum iterations were reached."
    )


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

async def main():

    server_path = (
        Path(__file__)
        .resolve()
        .with_name("research_server.py")
    )

    print("Python:", sys.executable)
    print("Server:", server_path)

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)]
    )

    async with stdio_client(
        server_params
    ) as (read, write):

        async with ClientSession(
            read,
            write
        ) as session:

            # ---------------------------------------------
            # Connect to MCP server
            # ---------------------------------------------

            await session.initialize()

            print("\nConnected to MCP server.")

            # ---------------------------------------------
            # Discover tools
            # ---------------------------------------------

            response = await session.list_tools()

            mcp_tools = response.tools

            print("\nAvailable MCP tools:")

            for tool in mcp_tools:
                print("-", tool.name)

            # ---------------------------------------------
            # Convert tools for LLM
            # ---------------------------------------------

            llm_tools = convert_mcp_tools(
                mcp_tools
            )

            # ---------------------------------------------
            # Chat loop
            # ---------------------------------------------

            print("\nResearch Agent Ready.")
            print("Type 'quit' to exit.")

            while True:

                user_query = input(
                    "\nYou: "
                ).strip()

                if user_query.lower() in {
                    "quit",
                    "exit"
                }:
                    break

                await run_agent(
                    session=session,
                    llm_tools=llm_tools,
                    user_query=user_query
                )


if __name__ == "__main__":
    asyncio.run(main())
