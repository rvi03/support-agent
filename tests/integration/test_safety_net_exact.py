"""CP4.6: with the pattern detector switched off, the vault exact match alone
still blocks a prompt, a log line and an L2 note that carry the ticket's name
or its phone (any separators), and writes one `pii_blocked` audit row for each
(D43). A store message with the name passes. Mock contact values only.

Needs `make up`. Audit rows go in as `intake_rw`; audit.events is append-only,
so each run uses its own ticket id and run id.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest

from support_agent.common.audit import AuditEvent, write_event
from support_agent.common.pii_filter import clear_exact_values
from support_agent.intake.reference import build_reference
from support_agent.intake.safety_net import (
    Channel,
    Hit,
    PatternDetector,
    PIIBlocked,
    SafetyNet,
    register_contact,
)
from support_agent.intake.vault import Contact
from tests.integration.platform_env import load_env, superuser_url

pytestmark = pytest.mark.integration

CONTACT = Contact(full_name="Testa Mockwell", phone="+91-90000-00031")
# The name, a name part in another case, and the phone with other separators.
LEAKS = {
    Channel.PROMPT: "Store contact is Testa Mockwell, ask about the KOT printer.",
    Channel.LOG: "resolver step done for mockwell at counter 2",
    Channel.L2_NOTE: "Store reachable on 90000 00031 or (900) 000-0031 after 6 pm.",
}


class _Off(PatternDetector):
    def detect(self, text: str) -> list[Hit]:
        return []


@pytest.fixture
def setup() -> Iterator[tuple[SafetyNet, str, uuid.UUID, psycopg.Connection[Any]]]:
    env = load_env()
    ticket_id = f"CP46-{uuid.uuid4().hex[:8]}"
    run_id = uuid.uuid4()
    reference = build_reference((), ("KOT",))
    with psycopg.connect(env["DATABASE_URL_INTAKE"], autocommit=True) as conn:

        def audit(event: AuditEvent) -> object:
            return write_event(
                conn,
                AuditEvent(**{**event.__dict__, "run_id": run_id}),
            )

        net = SafetyNet(reference, audit, actor="intake", pattern=_Off(reference))
        register_contact(ticket_id, CONTACT)
        yield net, ticket_id, run_id, conn
        clear_exact_values(ticket_id)


def _rows(ticket_id: str) -> list[tuple[Any, ...]]:
    with psycopg.connect(superuser_url(load_env())) as su:
        rows: list[tuple[Any, ...]] = su.execute(
            "SELECT action, result, payload->>'channel', payload->>'detector', reason,"
            " payload::text FROM audit.events WHERE ticket_id = %s ORDER BY id",
            (ticket_id,),
        ).fetchall()
    return rows


def test_vault_exact_match_alone_blocks_and_audits(
    setup: tuple[SafetyNet, str, uuid.UUID, psycopg.Connection[Any]],
) -> None:
    net, ticket_id, _, _ = setup
    for channel, text in LEAKS.items():
        with pytest.raises(PIIBlocked) as info:
            net.scan(text, ticket_id, channel)
        assert {h.detector for h in info.value.hits} == {"vault_exact"}
        assert "Testa" not in str(info.value) and "00031" not in str(info.value)

    rows = _rows(ticket_id)
    assert {(r[2], r[3]) for r in rows} == {(str(c), "vault_exact") for c in LEAKS}
    assert all(r[0] == "pii_blocked" and r[1] == "blocked" for r in rows)
    for row in rows:  # the audit row never holds the value
        joined = " ".join(str(v) for v in row).casefold()
        assert "testa" not in joined and "mockwell" not in joined and "00031" not in joined


def test_store_message_with_the_name_passes(
    setup: tuple[SafetyNet, str, uuid.UUID, psycopg.Connection[Any]],
) -> None:
    net, ticket_id, _, _ = setup
    assert net.scan("Hi Testa Mockwell, the printer is fixed.", ticket_id, "store_message") == []
    assert _rows(ticket_id) == []


def test_never_mask_name_part_is_not_a_hit(
    setup: tuple[SafetyNet, str, uuid.UUID, psycopg.Connection[Any]],
) -> None:
    net, ticket_id, _, _ = setup
    # A clean text with other words and other numbers passes.
    assert net.scan("KOT printer at SW-9999 reset; call 90000 00099.", ticket_id, "prompt") == []
