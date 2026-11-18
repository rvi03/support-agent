"""`python -m support_agent.mcp.knowledge`: serve the knowledge MCP server."""

from __future__ import annotations

import uvicorn

from support_agent.common.config import KnowledgeSettings, get_settings
from support_agent.common.logging import configure_logging
from support_agent.mcp.knowledge.server import build_service


def main() -> None:
    settings = get_settings(KnowledgeSettings)
    configure_logging("knowledge", settings.log_dir)
    app = build_service(settings).app()
    uvicorn.run(app, host=settings.knowledge_host, port=settings.knowledge_port, log_config=None)


if __name__ == "__main__":
    main()
