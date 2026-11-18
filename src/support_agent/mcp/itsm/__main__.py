"""`python -m support_agent.mcp.itsm`: serve the itsm-actions MCP server."""

from __future__ import annotations

import uvicorn

from support_agent.common.config import ItsmSettings, get_settings
from support_agent.common.logging import configure_logging
from support_agent.mcp.itsm.server import build_service


def main() -> None:
    settings = get_settings(ItsmSettings)
    configure_logging("itsm-actions", settings.log_dir)
    app = build_service(settings).app()
    uvicorn.run(app, host=settings.itsm_host, port=settings.itsm_port, log_config=None)


if __name__ == "__main__":
    main()
