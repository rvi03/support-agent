"""CP4.4 live smoke: one real message per label through LiteLLM (`moderation`
alias, gpt-6-luna), with the real safety net in front of the call, plus one
clean IT message that must come back ok. Mock texts, no PII.

Needs `make up` and OPENAI_API_KEY in LiteLLM; about 7 short calls.
"""

from __future__ import annotations

import pytest

from support_agent.common.audit import AuditEvent
from support_agent.intake.moderation import (
    BEHAVIOUR,
    Label,
    ModerationBudget,
    ModerationClient,
    Moderator,
    decide,
)
from support_agent.intake.reference import build_reference
from support_agent.intake.safety_net import SafetyNet
from tests.integration.platform_env import load_env
from tests.unit.test_moderation import CASES

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def moderator() -> Moderator:
    env = load_env()
    reference = build_reference((), ("KOT", "OrbitPOS", "POS"))
    events: list[AuditEvent] = []
    client = ModerationClient(env["LITELLM_BASE_URL"], env["LITELLM_MASTER_KEY"], timeout=60)
    return Moderator(client, SafetyNet(reference, events.append, actor="intake"), events.append)


@pytest.mark.parametrize("label", list(CASES), ids=str)
def test_live_label(moderator: Moderator, label: Label) -> None:
    text, _ = CASES[label]
    result = moderator.moderate(text, "INC-90040", ModerationBudget(max_calls=3))
    assert not result.failed, result.failure
    assert label in result.labels, f"got {result.labels}"
    assert decide(result) == BEHAVIOUR[result.label]


def test_live_clean_it_message_is_ok(moderator: Moderator) -> None:
    result = moderator.moderate(
        "The KOT printer at counter 2 shows offline since 9 am; we restarted it once.",
        "INC-90041",
        ModerationBudget(max_calls=3),
    )
    assert not result.failed and result.label is Label.OK, f"got {result.labels}"
