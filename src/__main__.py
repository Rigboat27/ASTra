import logging
import os
import click
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from dotenv import load_dotenv
from code_analysis_agent import create_agent  # type: ignore[import-not-found]
from openai_agent_executor import OpenAIAgentExecutor  # type: ignore[import-untyped]
from starlette.applications import Starlette

load_dotenv()
logging.basicConfig()

@click.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=5000, show_default=True)
def main(host: str, port: int) -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError("OPENAI_API_KEY environment variable not set")

    skill = AgentSkill(
        id="omni_code_reviewer",
        name="Omni-Language SAST & Code Review",
        description="Fetches code from GitHub/Files, parses AST with tree-sitter, and outputs a strict JSON report covering Security, Bugs, and Performance with hardened code patches.",
        tags=["code", "review", "security", "sast", "ast", "tree-sitter", "github"],
        examples=[
            "Review src/auth.py from GitHub repo acme/backend",
            "Analyse this pasted Python function for bugs and security",
            "Check /home/user/project/utils.cpp for performance and memory issues",
        ],
    )

    agent_card = AgentCard(
        name="Omni-Analyzer Agent",
        description="Unified AST-driven code review and SAST agent. Outputs strict JSON.",
        url=f"http://{host}:{port}/",
        version="2.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )

    agent_data = create_agent()

    # Pass Azure URL if available in environment
    agent_executor = OpenAIAgentExecutor(
        card=agent_card,
        tools=agent_data["tools"],
        api_key=os.getenv("OPENAI_API_KEY"),
        system_prompt=agent_data["system_prompt"],
        base_url=custom_url if custom_url else None
    )

    request_handler = DefaultRequestHandler(
        agent_executor=agent_executor,
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AStarletteApplication(agent_card=agent_card, http_handler=request_handler)
    app = Starlette(routes=a2a_app.routes())
    uvicorn.run(app, host=host, port=port)

if __name__ == "__main__":
    main()
