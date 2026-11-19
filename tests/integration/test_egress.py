"""D103: no container reaches the internet except LiteLLM; the gateway keeps the ports.

Network membership is read from Docker (deterministic); one live probe per
service shows the route out is really gone.
"""

from __future__ import annotations

import json
import socket
import subprocess

import pytest

pytestmark = pytest.mark.integration

PROJECT = "servewell"
EDGE = {"litellm", "gateway"}  # the only containers with a route out
PORTS = (5432, 8333, 8080, 8181, 3000, 4000, 8101, 8102, 8103)
PROBE = (
    "import urllib.request\n"
    "try:\n"
    "    urllib.request.urlopen('https://api.openai.com', timeout=5); print('reached')\n"
    "except Exception:\n"
    "    print('blocked')\n"
)


def _containers() -> dict[str, dict[str, object]]:
    ids = subprocess.run(
        ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECT}"],
        capture_output=True, text=True, check=True,
    ).stdout.split()  # fmt: skip
    info = json.loads(
        subprocess.run(
            ["docker", "inspect", *ids], capture_output=True, text=True, check=True
        ).stdout
    )
    return {
        c["Config"]["Labels"]["com.docker.compose.service"]: c["NetworkSettings"]["Networks"]
        for c in info
    }


def test_only_litellm_and_the_gateway_are_on_edge() -> None:
    nets = _containers()
    assert EDGE <= set(nets)
    for service, networks in nets.items():
        names = {n.removeprefix(f"{PROJECT}_") for n in networks}
        assert names == ({"core", "edge"} if service in EDGE else {"core"}), service


def test_core_network_is_internal() -> None:
    out = subprocess.run(
        ["docker", "network", "inspect", f"{PROJECT}_core", "--format", "{{.Internal}}"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert out == "true"


@pytest.mark.parametrize("service", ["it-data", "knowledge", "itsm-actions"])
def test_services_have_no_route_out(service: str) -> None:
    out = subprocess.run(
        ["docker", "exec", f"{PROJECT}-{service}-1", "python", "-c", PROBE],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()  # fmt: skip
    assert out == "blocked"


def test_published_ports_only_on_the_gateway_and_all_reachable() -> None:
    for service in _containers():
        ports = subprocess.run(
            ["docker", "port", f"{PROJECT}-{service}-1"], capture_output=True, text=True
        ).stdout.strip()
        assert (ports != "") == (service == "gateway"), service
    for port in PORTS:
        with socket.create_connection(("127.0.0.1", port), timeout=3):
            pass
