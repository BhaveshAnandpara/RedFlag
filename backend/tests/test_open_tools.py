"""Quick scan and the MCP check without the owner password.

Only the calls those two pages need are open: the hello check, the rule list, starting a scan,
and reading back the scan you started with the secret view key that start returned. Everything
else stays behind the owner password. A scan nobody started through these pages cannot be read
without the owner password, and the key to the target is saved nowhere.
"""

import json
import time
from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import OWNER, wait_for_scan
from tests.test_mcp_scan import URL as MCP_URL
from tests.test_mcp_scan import traversal_server
from tests.test_quick_scan import ENDPOINT, all_rules
from tests.test_setup_api import KEY
from tests.test_setup_runs import ready, run, run_client

QUICK_BODY: dict[str, Any] = {
    "endpoint": ENDPOINT,
    "key": KEY,
    "bot_type": "chatbot",
    "purpose": "A support bot for a bank.",
    "must_never": all_rules("chatbot"),
}


def read_open(client: TestClient, scan_id: int, view_key: str, timeout: float = 30.0) -> Any:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/open-scans/{scan_id}", params={"key": view_key})
        if response.status_code != 200 or time.monotonic() > deadline:
            return response
        if response.json()["scan"]["status"] != "running":
            return response
        time.sleep(0.05)


def test_the_quick_scan_works_without_the_password() -> None:
    with run_client() as (client, _, _):
        assert client.get("/quick-scans/rules").status_code == 200
        hello = client.post("/quick-scans/check", json={"endpoint": ENDPOINT, "key": KEY})
        assert hello.status_code == 200 and hello.json()["status"] == "ok"
        started = client.post("/quick-scans", json=QUICK_BODY)
        assert started.status_code == 202, started.text
        body = started.json()
        assert body["view_key"] and len(body["view_key"]) >= 20
        read = read_open(client, body["scan_id"], body["view_key"])
    assert read.status_code == 200
    scan = read.json()
    assert scan["scan"]["status"] == "completed" and len(scan["results"]) == body["test_count"]
    assert "summary" in scan


def test_a_scan_can_only_be_read_with_its_own_view_key() -> None:
    with run_client() as (client, _, _):
        first = client.post("/quick-scans", json=QUICK_BODY).json()
        read_open(client, first["scan_id"], first["view_key"])
        assert client.get(f"/open-scans/{first['scan_id']}").status_code == 422
        assert (
            client.get(f"/open-scans/{first['scan_id']}", params={"key": "wrong"}).status_code
            == 404
        )
        assert client.get("/open-scans/99999", params={"key": first["view_key"]}).status_code == 404


def test_the_view_key_and_the_target_key_never_appear_in_what_is_read_back() -> None:
    with run_client() as (client, _, _):
        started = client.post("/quick-scans", json=QUICK_BODY).json()
        text = read_open(client, started["scan_id"], started["view_key"]).text
    assert started["view_key"] not in text
    assert KEY not in text
    assert "label" not in json.loads(text)["results"][0]


def test_a_scan_started_any_other_way_is_never_readable_this_way() -> None:
    # A run the owner started from the setup page has no view key in its settings.
    with run_client() as (client, _, _):
        setup_id = ready(client)
        started = run(client, setup_id, ["g-1"])
        assert started.status_code == 202, started.text
        scan_id = int(started.json()["scan_id"])
        wait_for_scan(client, scan_id)
        for key in ("", "anything"):
            assert client.get(f"/open-scans/{scan_id}", params={"key": key}).status_code == 404


def test_everything_else_stays_behind_the_owner_password() -> None:
    with run_client() as (client, _, _):
        for method, path in [
            ("get", "/bots"),
            ("get", "/scans"),
            ("get", "/scans/1"),
            ("post", "/scans/1/rerun"),
            ("get", "/judge-accuracy"),
            ("put", "/scans/1/results/g-1/label"),
            ("post", "/setups"),
            ("get", "/setups"),
            ("post", "/setups/1/ci-tokens"),
        ]:
            response = getattr(client, method)(path)
            assert response.status_code == 401, (method, path)
        assert client.get("/scans", headers=OWNER).status_code == 200


def test_the_mcp_check_works_without_the_password_and_its_scan_is_read_with_a_view_key() -> None:
    fake = traversal_server(leak=False)
    with run_client(stand_in=fake) as (client, _, _):
        listed = client.post("/mcp-scans/check", json={"url": MCP_URL, "key": KEY})
        assert listed.status_code == 200
        started = client.post("/mcp-scans", json={"url": MCP_URL, "key": KEY})
        assert started.status_code == 202, started.text
        body = started.json()
        assert body["view_key"]
        read = read_open(client, body["scan_id"], body["view_key"])
    scan = read.json()
    assert scan["scan"]["settings"]["mcp"]["target_host"] == "mcp.example"
    assert "view_key" not in json.dumps(scan)
    assert KEY not in read.text
