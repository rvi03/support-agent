"""`python -m support_agent.mcp.it_data`: serve the it-data MCP server."""

from __future__ import annotations

import uvicorn

from support_agent.common.config import ItDataSettings, get_settings
from support_agent.common.logging import configure_logging
from support_agent.mcp.it_data.server import build_service


def main() -> None:
    settings = get_settings(ItDataSettings)
    configure_logging("it-data", settings.log_dir)
    app = build_service(settings).app()
    uvicorn.run(app, host=settings.it_data_host, port=settings.it_data_port, log_config=None)


if __name__ == "__main__":
    main()
