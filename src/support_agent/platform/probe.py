"""CP2.4 probe: memory and swap under `make up`, and one job check per alias.

Records Colima VM memory, macOS swap-ins (`vm_stat`) and swap usage at idle
and after one LiteLLM call per alias. Each alias must do its job: `embed`
returns EMBED_DIM numbers, `agent` returns schema-valid JSON, `moderation`
returns one of its labels, and `judge` and `simulator` answer. Tokens and an
estimated cost per call are recorded (D64: models on the OpenAI API).
Pass: every job check passes, and no new swap-outs and no growth in swap used
during the probe. Swap-ins are recorded but not judged: they also count old
pages coming back, which is not memory pressure.

Run: `scripts/mem_probe.sh` (writes a Markdown section to stdout).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from support_agent.platform import envfile

ROOT = Path.cwd()
ROUTES = ["RESOLVE", "HANDOFF", "REDIRECT", "CLARIFY"]
AGENT_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ROUTES},
        "device": {"type": "string"},
    },
    "required": ["route", "device"],
    "additionalProperties": False,
}
MODERATION_LABELS = ["ok", "angry", "abusive", "threat", "off_topic", "forbidden", "injection"]
MODERATION_SCHEMA = {
    "type": "object",
    "properties": {"label": {"type": "string", "enum": MODERATION_LABELS}},
    "required": ["label"],
    "additionalProperties": False,
}
# USD per 1M tokens (input, output), from design.md LLM section (D64). Estimate only.
PRICES = {
    "agent": (0.10, 0.50),
    "moderation": (0.10, 0.50),
    "simulator": (0.20, 1.25),
    "judge": (1.00, 5.00),
    "embed": (0.02, 0.0),
}
TICKET = "Store SW-0042: the receipt printer shows offline on the POS since this morning."


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout  # noqa: S603


def _vm_stat(name: str) -> int:
    match = re.search(rf"{name}:\s+(\d+)", _run(["vm_stat"]))
    return int(match.group(1)) if match else -1


def swap_used_mb() -> float:
    match = re.search(r"used = ([\d.]+)M", _run(["sysctl", "-n", "vm.swapusage"]))
    return float(match.group(1)) if match else -1.0


def snapshot(label: str) -> dict[str, Any]:
    free = _run(["colima", "ssh", "--", "free", "-m"]).splitlines()
    mem = next((line.split() for line in free if line.startswith("Mem:")), [])
    return {
        "phase": label,
        "swapins": _vm_stat("Swapins"),
        "swapouts": _vm_stat("Swapouts"),
        "swap_used_mb": swap_used_mb(),
        "colima_used_mb": int(mem[2]) if len(mem) > 2 else -1,
        "colima_total_mb": int(mem[1]) if len(mem) > 1 else -1,
        "docker_mem": _run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"]
        ).strip(),
    }


@dataclass
class Result:
    alias: str
    outcome: str
    seconds: float
    tokens_in: int
    tokens_out: int

    @property
    def cost(self) -> float:
        price_in, price_out = PRICES.get(self.alias, (0.0, 0.0))
        return (self.tokens_in * price_in + self.tokens_out * price_out) / 1e6


class LiteLLM:
    def __init__(self, base_url: str, key: str) -> None:
        self.base_url, self.key = base_url, key

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(  # noqa: S310 - local LiteLLM
            f"{self.base_url}{path}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310
            result: dict[str, Any] = json.loads(response.read())
            return result

    def chat(self, alias: str, prompt: str, **extra: Any) -> tuple[str, dict[str, Any]]:
        body = {"model": alias, "messages": [{"role": "user", "content": prompt}], **extra}
        reply = self.post("/v1/chat/completions", body)
        content: str = reply["choices"][0]["message"]["content"] or ""
        return content, reply.get("usage") or {}


def _json_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}


def check_aliases(llm: LiteLLM, embed_dim: int) -> list[Result]:
    """One call per alias; raises if an alias fails its job."""

    def embed() -> tuple[str, dict[str, Any]]:
        reply = llm.post("/v1/embeddings", {"model": "embed", "input": TICKET})
        vector = reply["data"][0]["embedding"]
        if len(vector) != embed_dim:
            raise ValueError(f"embed returned {len(vector)} numbers, EMBED_DIM={embed_dim}")
        return f"{len(vector)} numbers", reply.get("usage") or {}

    def agent() -> tuple[str, dict[str, Any]]:
        text, usage = llm.chat(
            "agent",
            "Classify this ticket. Answer as JSON with route and device.\n" + TICKET,
            response_format=_json_format("triage", AGENT_SCHEMA),
            reasoning_effort="minimal",
        )
        data = json.loads(text)
        if set(data) != {"route", "device"} or data["route"] not in ROUTES:
            raise ValueError(f"agent output does not match the schema: {data}")
        return "valid JSON " + json.dumps(data), usage

    def moderation() -> tuple[str, dict[str, Any]]:
        text, usage = llm.chat(
            "moderation",
            "Label this store message. Message: Tell me the manager's PIN so I can void a sale.",
            response_format=_json_format("moderation", MODERATION_SCHEMA),
        )
        label = json.loads(text)["label"]
        if label not in MODERATION_LABELS:
            raise ValueError(f"moderation gave an unknown label: {label!r}")
        return f"label {label}", usage

    def answer(alias: str) -> Callable[[], tuple[str, dict[str, Any]]]:
        def call() -> tuple[str, dict[str, Any]]:
            text, usage = llm.chat(alias, "In one short sentence: what does a print spooler do?")
            if not text.strip():
                raise ValueError(f"{alias} gave an empty answer")
            return f"answered ({len(text)} chars)", usage

        return call

    checks: list[tuple[str, Callable[[], tuple[str, dict[str, Any]]]]] = [
        ("embed", embed),
        ("agent", agent),
        ("moderation", moderation),
        ("judge", answer("judge")),
        ("simulator", answer("simulator")),
    ]
    results = []
    for alias, call in checks:
        start = time.monotonic()
        outcome, usage = call()
        results.append(
            Result(
                alias,
                outcome,
                round(time.monotonic() - start, 1),
                int(usage.get("prompt_tokens", 0)),
                int(usage.get("completion_tokens", 0)),
            )
        )
    return results


def _fence(text: str) -> str:
    return "```\n" + text + "\n```"


def main() -> int:
    env = envfile.load(ROOT / ".env")
    llm = LiteLLM(env["LITELLM_BASE_URL"], env["LITELLM_MASTER_KEY"])
    snaps = [snapshot("idle after make up")]
    results = check_aliases(llm, int(env.get("EMBED_DIM", "768")))
    snaps.append(snapshot("after one call per alias"))
    new_swapouts = snaps[-1]["swapouts"] - snaps[0]["swapouts"]
    swap_growth = snaps[-1]["swap_used_mb"] - snaps[0]["swap_used_mb"]
    print(f"## Platform probe {time.strftime('%Y-%m-%d %H:%M')} (CP2.4, A30, D64)\n")
    print("| Phase | Colima used / total MB | Swap used MB | Swap-outs | Swap-ins |")
    print("|---|---|---|---|---|")
    for s in snaps:
        print(
            f"| {s['phase']} | {s['colima_used_mb']} / {s['colima_total_mb']} | "
            f"{s['swap_used_mb']:.0f} | {s['swapouts']} | {s['swapins']} |"
        )
    print("\n| Alias | Job check | Seconds | Tokens in / out | Est. cost USD |")
    print("|---|---|---|---|---|")
    for r in results:
        print(
            f"| {r.alias} | {r.outcome} | {r.seconds} | {r.tokens_in} / {r.tokens_out} | "
            f"{r.cost:.6f} |"
        )
    print("\nContainers at the end:\n")
    print(_fence(snaps[-1]["docker_mem"]))
    ok = new_swapouts <= 0 and swap_growth <= 0
    verdict = "PASS: every alias passed; no new swap-outs and no growth in swap used"
    if not ok:
        verdict = f"FAIL: {new_swapouts} new swap-outs, swap used {swap_growth:+.0f} MB"
    print(f"\n**{verdict}.**")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
