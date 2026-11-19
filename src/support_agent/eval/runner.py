"""S14 build step 4: the eval runner (D45, D47, D52, D53, D56).

`make eval SPLIT=tune|heldout|all [IDS="INC-… …"] [LIMIT=n]` (the agent phase):

1. a held-out id in the selection needs a valid freeze manifest (eval/freeze.py);
2. one `run_id` for the whole dataset run; the expected item list is written to
   `eval/runs/<run>/expected.json` before any ticket starts;
3. each item is created through the API as `eval-runner` with its
   `source_ticket_id` and the run id (the API takes date_opened and the contact from
   the source row, D52), then every pause is answered by its `pending_id`:
   - store reply or clarify answer: the simulator (outcome decided by code from the
     fault card) as `eval-runner`;
   - approval: `mock-l2` or `mock-vendor` (by the card's approver role) approves;
   - L2 task: `mock-l2` returns `done` with a fixed result;
4. the final view is read as `eval-runner`, plus the IT view (notes, approvals, L2
   tasks, audit) as the queue's role when the ticket ends in a queue;
5. one JSON line per item in `results.jsonl`; a ticket that errors or never
   finishes is written with `status: missing`, never dropped.

The platform must run with EVAL_MODE=true, CLOCK_MODE=replay and fault cards
(`make eval-mode`); every action row must say `eval_mode: true`, or the item is
marked `not_eval_mode` and the run fails its checks. Judge scoring is a separate
phase (eval/score.py) that starts only after this one, so scores never feed back.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from support_agent.agent.llm import ChatClient
from support_agent.cli.ticket import CliSettings
from support_agent.common.config import EvalSettings, get_settings
from support_agent.eval import freeze
from support_agent.eval.dataset import DATASET, ITEM_PREFIX
from support_agent.eval.simulator import Simulator, decide, load_card
from support_agent.platform.mock_secrets import mock_client_secret

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "eval" / "runs"
CARDS_DIR = ROOT / "eval" / "fault_cards"
POLL_S = 2.0
TICKET_TIMEOUT_S = 900.0
MAX_PAUSES = 20
CONCURRENCY = 4
DONE = ("done", "failed")
BODY_FIELDS = (
    "subject", "description", "asset_id", "system_version", "category", "subcategory",
    "priority", "tags", "store_name", "escalation_flag", "related_tickets", "ticket_history",
)  # fmt: skip
L2_RESULT = "Done as the runbook step describes."
QUEUE_READER = {"l2": "mock-l2", "l1": "mock-l1"}


@dataclass
class Token:
    http: httpx.AsyncClient
    url: str
    client_id: str
    secret: str
    _token: str | None = None
    _expires: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def get(self) -> str:
        async with self._lock:
            if not self._token or time.time() >= self._expires:
                r = await self.http.post(self.url, data={
                    "grant_type": "client_credentials", "client_id": self.client_id,
                    "client_secret": self.secret,
                })  # fmt: skip
                r.raise_for_status()
                body = r.json()
                self._token = str(body["access_token"])
                self._expires = time.time() + max(float(body.get("expires_in", 60)) - 30, 5)
            return self._token


@dataclass
class Api:
    http: httpx.AsyncClient
    base: str
    tokens: dict[str, Token]

    async def call(
        self, who: str, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        token = await self.tokens[who].get()
        for attempt in range(4):
            r = await self.http.request(method, self.base + path, json=body,
                                        headers={"Authorization": f"Bearer {token}"})  # fmt: skip
            if r.status_code != 429:
                return r
            await asyncio.sleep(5 * (attempt + 1))
        return r


def ticket_body(item_input: dict[str, Any], run_id: uuid.UUID) -> dict[str, Any]:
    body = {k: item_input[k] for k in BODY_FIELDS if item_input.get(k) not in (None, "")}
    body["source_ticket_id"] = item_input["source_ticket_id"]
    body["run_id"] = str(run_id)
    return body


@dataclass
class ItemResult:
    source_ticket_id: str
    split: str
    cohort: str
    status: str  # done | missing | not_eval_mode
    ticket_id: str | None = None
    view: dict[str, Any] | None = None
    it_view: dict[str, Any] | None = None
    store_replies: list[dict[str, str]] = field(default_factory=list)
    approvals: int = 0
    l2_tasks: int = 0
    seconds: float = 0.0
    error: str | None = None


async def run_item(api: Api, sim: Simulator, item: dict[str, Any], run_id: uuid.UUID) -> ItemResult:
    inp, meta = item["input"], item["metadata"]
    res = ItemResult(inp["source_ticket_id"], meta["split"], meta["cohort"], "missing")
    started = time.monotonic()
    card = load_card(CARDS_DIR, inp["source_ticket_id"])
    l2_done: list[str] = []
    try:
        r = await api.call("eval-runner", "POST", "/tickets", ticket_body(inp, run_id))
        if r.status_code != 202:
            raise RuntimeError(f"POST /tickets {r.status_code} {r.text[:200]}")
        tid = res.ticket_id = r.json()["ticket_id"]
        answered: set[str] = set()
        deadline = time.monotonic() + TICKET_TIMEOUT_S
        while True:
            view = (await api.call("eval-runner", "GET", f"/tickets/{tid}")).raise_for_status()
            v = view.json()
            pending = v.get("pending")
            if pending and pending["pending_id"] not in answered:
                if len(answered) >= MAX_PAUSES:
                    raise RuntimeError(f"more than {MAX_PAUSES} pauses")
                kind, pid = pending["kind"], pending["pending_id"]
                if kind in ("store_reply", "answer"):
                    outcome = decide(card, v, l2_done)
                    last = v["messages"][-1]["text"] if v.get("messages") else ""
                    text = await sim.reply(inp, card, last, outcome)
                    res.store_replies.append({"outcome": outcome, "text": text})
                    resp = await api.call("eval-runner", "POST", f"/tickets/{tid}/reply",
                                          {"pending_id": pid, "text": text})  # fmt: skip
                elif kind == "approval":
                    who = "mock-vendor" if pending.get("approver_role") == "vendor_approver" \
                        else "mock-l2"  # fmt: skip
                    res.approvals += 1
                    resp = await api.call(who, "POST", f"/tickets/{tid}/approve",
                                          {"pending_id": pid, "decision": "approve"})  # fmt: skip
                else:  # l2_task
                    res.l2_tasks += 1
                    l2_done.append(str(pending.get("step_id")))
                    resp = await api.call("mock-l2", "POST", f"/tickets/{tid}/approve",
                                          {"pending_id": pid, "decision": "done",
                                           "result": L2_RESULT})  # fmt: skip
                if resp.status_code != 202:
                    raise RuntimeError(f"{kind}: {resp.status_code} {resp.text[:200]}")
                answered.add(pid)
            elif not pending and v["api_status"] in DONE:
                res.view = v
                break
            if time.monotonic() > deadline:
                raise RuntimeError(f"no outcome after {TICKET_TIMEOUT_S:.0f} s")
            await asyncio.sleep(POLL_S)
        reader = QUEUE_READER.get(str(res.view.get("assignee_queue")))
        if reader:
            it = await api.call(reader, "GET", f"/tickets/{tid}")
            if it.status_code == 200:
                res.it_view = it.json()
        if any(a.get("eval_mode") is not True for a in res.view.get("actions") or []):
            res.status = "not_eval_mode"
        else:
            res.status = "done"
    except Exception as exc:  # noqa: BLE001 - every failure is recorded, never dropped
        res.error = f"{type(exc).__name__}: {exc}"[:500]
    res.seconds = round(time.monotonic() - started, 1)
    return res


def select(
    items: list[dict[str, Any]], split: str, ids: set[str], limit: int | None
) -> list[dict[str, Any]]:
    chosen = [
        i for i in items
        if (split == "all" or i["metadata"]["split"] == split)
        and (not ids or i["input"]["source_ticket_id"] in ids)
    ]  # fmt: skip
    chosen.sort(key=lambda i: i["input"]["source_ticket_id"])
    return chosen[:limit] if limit else chosen


def load_dataset_items(settings: EvalSettings) -> list[dict[str, Any]]:
    from support_agent.eval.dataset import LangfuseDataset

    lf = LangfuseDataset(settings).lf
    return [
        {"id": i.id, "input": i.input, "metadata": i.metadata}
        for i in lf.get_dataset(DATASET, fetch_items_page_size=100).items
        if i.id.startswith(ITEM_PREFIX)
    ]


async def run(split: str, ids: set[str], limit: int | None, run_name: str | None) -> Path:
    settings = get_settings(EvalSettings)
    # D56: any entry point that may touch a held-out id checks the freeze first.
    manifest = freeze.check(settings) if split in ("heldout", "all") else None
    cli = CliSettings()
    items = select(load_dataset_items(settings), split, ids, limit)
    if not items:
        raise SystemExit("no items selected")
    if manifest is None and any(i["metadata"]["split"] == "heldout" for i in items):
        raise SystemExit("held-out item in a tune selection")
    run_id = uuid.uuid4()
    name = run_name or f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{split}"
    folder = RUNS / name
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "expected.json").write_text(json.dumps({
        "run_id": str(run_id), "run_name": name, "split": split, "dataset": DATASET,
        "started_at": datetime.now(UTC).isoformat(), "freeze_hash": manifest,
        "items": [i["input"]["source_ticket_id"] for i in items],
    }, indent=1))  # fmt: skip
    print(f"run {name} ({run_id}): {len(items)} items -> {folder}")
    async with httpx.AsyncClient(timeout=60.0) as http:
        secret_key = cli.mock_client_secret_key.get_secret_value()
        tokens = {
            "eval-runner": Token(http, cli.token_url, "eval-runner",
                                 settings.keycloak_secret_eval_runner.get_secret_value()),
            **{c: Token(http, cli.token_url, c, mock_client_secret(secret_key, c))
               for c in ("mock-l2", "mock-vendor", "mock-l1")},
        }  # fmt: skip
        api = Api(http, cli.api_url, tokens)
        llm = ChatClient(settings.litellm_base_url,
                         settings.litellm_master_key.get_secret_value(),
                         model=settings.model_simulator)  # fmt: skip
        sim = Simulator(llm)
        sem = asyncio.Semaphore(CONCURRENCY)
        out = (folder / "results.jsonl").open("a")
        done = 0

        async def one(item: dict[str, Any]) -> None:
            nonlocal done
            async with sem:
                res = await run_item(api, sim, item, run_id)
            out.write(json.dumps(res.__dict__, default=str) + "\n")
            out.flush()
            done += 1
            print(f"[{done}/{len(items)}] {res.source_ticket_id} {res.status} "
                  f"{(res.view or {}).get('route') or '-'} {res.seconds}s"
                  + (f" {res.error}" if res.error else ""))  # fmt: skip

        try:
            await asyncio.gather(*(one(i) for i in items))
        finally:
            out.close()
            await llm.aclose()
    return folder


def main(argv: list[str]) -> int:
    split = argv[0] if argv else "tune"
    if split not in ("tune", "heldout", "all"):
        raise SystemExit("usage: runner tune|heldout|all [--ids A,B] [--limit n] [--name x]")
    opts = dict(zip(argv[1::2], argv[2::2], strict=False))
    ids = {i for i in opts.get("--ids", "").replace(",", " ").split() if i}
    limit = int(opts["--limit"]) if opts.get("--limit") else None
    asyncio.run(run(split, ids, limit, opts.get("--name")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
