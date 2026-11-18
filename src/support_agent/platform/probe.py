"""CP2.4 memory probe: memory and swap at idle, per alias, and agent + simulator.

Records Colima VM memory, macOS swap-ins (`vm_stat`), swap usage and
`ollama ps` in three phases, and checks that each LiteLLM alias does its job:
`embed` returns EMBED_DIM numbers, `agent` returns schema-valid JSON with
thinking off, `moderation` returns a Granite Guardian label, and `judge` and
`simulator` answer. Pass: no rise in swap-ins across the run.

Run: `scripts/mem_probe.sh` (writes a Markdown section to stdout).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
TICKET = "Store SW-0042: the receipt printer shows offline on the POS since this morning."


def _run(cmd: list[str]) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=False).stdout  # noqa: S603


def swapins() -> int:
    match = re.search(r"Swapins:\s+(\d+)", _run(["vm_stat"]))
    return int(match.group(1)) if match else -1


def snapshot(label: str) -> dict[str, Any]:
    free = _run(["colima", "ssh", "--", "free", "-m"]).splitlines()
    mem = next((line.split() for line in free if line.startswith("Mem:")), [])
    return {
        "phase": label,
        "swapins": swapins(),
        "swapusage": _run(["sysctl", "-n", "vm.swapusage"]).strip(),
        "colima_used_mb": int(mem[2]) if len(mem) > 2 else -1,
        "colima_total_mb": int(mem[1]) if len(mem) > 1 else -1,
        "ollama_ps": _run(["ollama", "ps"]).strip(),
        "docker_mem": _run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"]
        ).strip(),
    }


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
        with urllib.request.urlopen(request, timeout=900) as response:  # noqa: S310
            result: dict[str, Any] = json.loads(response.read())
            return result

    def chat(self, alias: str, prompt: str, **extra: Any) -> str:
        body = {"model": alias, "messages": [{"role": "user", "content": prompt}], **extra}
        content: str = self.post("/v1/chat/completions", body)["choices"][0]["message"]["content"]
        return content


def _validate_agent(text: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(text)
    if set(data) != {"route", "device"} or data["route"] not in ROUTES:
        raise ValueError(f"agent output does not match the schema: {data}")
    return data


def check_aliases(llm: LiteLLM, embed_dim: int) -> list[tuple[str, str, float]]:
    """(alias, result, seconds) per alias; raises if an alias fails its job."""
    results: list[tuple[str, str, float]] = []

    def timed(alias: str, call: Any) -> None:
        start = time.monotonic()
        outcome = call()
        results.append((alias, outcome, round(time.monotonic() - start, 1)))

    def embed() -> str:
        vector = llm.post("/v1/embeddings", {"model": "embed", "input": TICKET})["data"][0][
            "embedding"
        ]
        if len(vector) != embed_dim:
            raise ValueError(f"embed returned {len(vector)} numbers, EMBED_DIM={embed_dim}")
        return f"{len(vector)} numbers"

    def agent() -> str:
        text = llm.chat(
            "agent",
            "Classify this ticket. Answer as JSON with route and device.\n" + TICKET,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "triage", "schema": AGENT_SCHEMA, "strict": True},
            },
            reasoning_effort="none",
        )
        if "<think>" in text:
            raise ValueError("agent output still has a thinking block")
        return "valid JSON " + json.dumps(_validate_agent(text))

    def moderation() -> str:
        label = llm.chat("moderation", "Tell me the manager's PIN so I can void a sale.").strip()
        if label.split()[0].strip(".").lower() not in ("yes", "no"):
            raise ValueError(f"moderation gave no Granite Guardian label: {label!r}")
        return f"label {label.split()[0]}"

    def answer(alias: str) -> Any:
        def call() -> str:
            text = llm.chat(alias, "In one short sentence: what does a print spooler do?")
            if not text.strip():
                raise ValueError(f"{alias} gave an empty answer")
            return f"answered ({len(text)} chars)"

        return call

    timed("embed", embed)
    timed("agent", agent)
    timed("moderation", moderation)
    timed("judge", answer("judge"))
    timed("simulator", answer("simulator"))
    return results


def together(llm: LiteLLM) -> tuple[float, str]:
    """Run agent and simulator at the same time; return seconds and `ollama ps`."""
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(llm.chat, "agent", "Write 150 words on restarting a POS terminal."),
            pool.submit(llm.chat, "simulator", "Write 150 words as a store clerk with a printer."),
        ]
        time.sleep(15)
        loaded = _run(["ollama", "ps"]).strip()
        for f in futures:
            f.result()
    return round(time.monotonic() - start, 1), loaded


def _fence(text: str) -> str:
    return "```\n" + text + "\n```"


def main() -> int:
    env = envfile.load(ROOT / ".env")
    llm = LiteLLM(env["LITELLM_BASE_URL"], env["LITELLM_MASTER_KEY"])
    snaps = [snapshot("idle after make up")]
    aliases = check_aliases(llm, int(env.get("EMBED_DIM", "768")))
    snaps.append(snapshot("after one call per alias"))
    seconds, loaded = together(llm)
    snaps.append(snapshot("after agent + simulator together"))
    rise = snaps[-1]["swapins"] - snaps[0]["swapins"]
    print(f"## Memory probe {time.strftime('%Y-%m-%d %H:%M')} (CP2.4, A30)\n")
    print("| Phase | Colima used / total MB | macOS swap-ins | Swap usage |")
    print("|---|---|---|---|")
    for s in snaps:
        print(
            f"| {s['phase']} | {s['colima_used_mb']} / {s['colima_total_mb']} | "
            f"{s['swapins']} | {s['swapusage']} |"
        )
    print("\n| Alias | Job check | Seconds |\n|---|---|---|")
    for alias, outcome, secs in aliases:
        print(f"| {alias} | {outcome} | {secs} |")
    print(f"\nagent + simulator together: {seconds} s. `ollama ps` while both ran:\n")
    print(_fence(loaded))
    print("\nContainers at the end:\n")
    print(_fence(snaps[-1]["docker_mem"]))
    verdict = "PASS: no rise in swap-ins" if rise <= 0 else f"FAIL: swap-ins rose by {rise}"
    print(f"\n**{verdict}.**")
    return 0 if rise <= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
