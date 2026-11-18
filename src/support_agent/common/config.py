"""Per-service settings (D46).

Each service loads only its own settings class, so no process holds another
role's credentials. Variables come from the environment (compose passes each
container only its own) or a local `.env` for development.

Run `python -m support_agent.common.config <service>` to check one service's
settings; a missing or invalid setting exits with code 2.
"""

from __future__ import annotations

import sys
from enum import StrEnum
from pathlib import Path
from typing import NoReturn

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

EXIT_BAD_SETTINGS = 2


class ClockMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"


class BaseServiceSettings(BaseSettings):
    """Fields every service shares. Holds no credentials.

    Model fields hold LiteLLM aliases (`agent`, `embed`, ...), never a model
    name: compose/litellm/config.yaml maps each alias to a model (D21).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    keycloak_issuer: str
    # Where a container fetches the signing keys; the issuer stays the public URL (S5).
    keycloak_jwks_url: str | None = None
    opa_url: str
    litellm_base_url: str
    log_dir: str = "logs"
    clock_mode: ClockMode = ClockMode.LIVE
    eval_mode: bool = False
    # Inside a container the DSN's `localhost` is replaced by this host (S5).
    db_host: str | None = None

    @property
    def jwks_url(self) -> str:
        return self.keycloak_jwks_url or self.keycloak_issuer + "/protocol/openid-connect/certs"


class IngestSettings(BaseServiceSettings):
    database_url_ingest: SecretStr
    s3_endpoint_url: str
    s3_access_key_ingest: SecretStr
    s3_secret_key_ingest: SecretStr
    # The given dataset folder, read-only; the default fits the tsk task layout.
    dataset_dir: Path = Path("../../references/assignment/dataset")


class IntakeSettings(BaseServiceSettings):
    database_url_intake: SecretStr
    # LiteLLM has no database for per-service virtual keys yet, so intake uses the master key.
    litellm_master_key: SecretStr
    model_moderation: str = "moderation"
    # Moderation has its own cap, outside LLM_MAX_CALLS (review m1).
    moderation_max_calls: int = Field(default=10, ge=1)


class ItDataSettings(BaseServiceSettings):
    database_url_it_data: SecretStr
    it_data_host: str = "127.0.0.1"
    it_data_port: int = Field(default=8101, ge=1, le=65535)


class KnowledgeSettings(BaseServiceSettings):
    database_url_knowledge: SecretStr
    # Query embeddings go through the router like every model call (D66).
    litellm_master_key: SecretStr
    model_embed: str = "embed"
    embed_dim: int = Field(default=768, ge=1)
    knowledge_host: str = "127.0.0.1"
    knowledge_port: int = Field(default=8102, ge=1, le=65535)
    # Per-run KB-text budget and eval exclusions live in Valkey; compose builds the URL.
    valkey_url_knowledge: SecretStr | None = None
    kb_budget_tokens: int = Field(default=12_000, ge=1)


class KbIndexSettings(BaseServiceSettings):
    database_url_kb_index: SecretStr
    s3_endpoint_url: str
    s3_access_key_kb_index: SecretStr
    s3_secret_key_kb_index: SecretStr
    litellm_master_key: SecretStr
    model_embed: str = "embed"
    embed_dim: int = Field(default=768, ge=1)


class ItsmSettings(BaseServiceSettings):
    database_url_itsm: SecretStr
    # Safety setting: required, no default (D46, A35).
    action_autonomy_runs: int = Field(ge=1)
    approval_ttl_min: int = Field(default=15, ge=1)
    itsm_host: str = "127.0.0.1"
    itsm_port: int = Field(default=8103, ge=1, le=65535)


class AgentSettings(BaseServiceSettings):
    database_url_agent: SecretStr
    model_agent: str = "agent"
    model_embed: str = "embed"
    embed_dim: int = Field(default=768, ge=1)
    llm_max_calls: int = Field(default=15, ge=1)
    triage_max_tool_calls: int = Field(default=6, ge=1)
    token_budget_per_ticket: int = Field(default=50_000, ge=1)
    approval_ttl_min: int = Field(default=15, ge=1)
    # Safety setting: required, no default (D46, A35).
    action_autonomy_runs: int = Field(ge=1)
    # Keycloak client-credentials secrets of the two agent identities (D25).
    keycloak_secret_agent_reader: SecretStr
    keycloak_secret_agent_actor: SecretStr
    it_data_url: str = "http://localhost:8101/mcp"


class ApiSettings(BaseServiceSettings):
    database_url_api: SecretStr
    s3_endpoint_url: str
    s3_access_key_api: SecretStr
    s3_secret_key_api: SecretStr


class EvalSettings(BaseServiceSettings):
    database_url_eval: SecretStr
    s3_endpoint_url: str
    s3_access_key_eval: SecretStr
    s3_secret_key_eval: SecretStr
    model_judge: str = "judge"
    model_simulator: str = "simulator"
    keycloak_secret_eval_runner: SecretStr
    # Shared router key (D66): query embeddings in the K4 replay (S6), judge calls later.
    litellm_master_key: SecretStr
    model_embed: str = "embed"
    embed_dim: int = Field(default=768, ge=1)


class CheckerSettings(BaseServiceSettings):
    database_url_checker: SecretStr


SERVICES: dict[str, type[BaseServiceSettings]] = {
    "ingest": IngestSettings,
    "intake": IntakeSettings,
    "it_data": ItDataSettings,
    "knowledge": KnowledgeSettings,
    "kb_index": KbIndexSettings,
    "itsm": ItsmSettings,
    "agent": AgentSettings,
    "api": ApiSettings,
    "eval": EvalSettings,
    "checker": CheckerSettings,
}


def _fail(lines: list[str]) -> NoReturn:
    for line in lines:
        print(line, file=sys.stderr)
    raise SystemExit(EXIT_BAD_SETTINGS)


def get_settings[S: BaseServiceSettings](cls: type[S]) -> S:
    """Load one service's settings or exit with code 2 naming each bad setting."""
    try:
        return cls()
    except ValidationError as exc:
        lines: list[str] = []
        for error in exc.errors(include_input=False, include_url=False):
            name = ".".join(str(part) for part in error["loc"]).upper()
            if error["type"] == "missing":
                lines.append(f"Missing setting: {name}")
            else:
                lines.append(f"Invalid setting: {name}: {error['msg']}")
        _fail(lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1 or args[0] not in SERVICES:
        _fail([f"Usage: python -m support_agent.common.config <{'|'.join(SERVICES)}>"])
    get_settings(SERVICES[args[0]])
    print(f"Settings OK: {args[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
