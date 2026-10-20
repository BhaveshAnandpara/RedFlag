"""Judge accuracy (W7), over HTTP with real Postgres.

The owner marks what the right verdict was for a result. The accuracy view compares those marks
with what the judge said, per risk, and states how many results each number rests on.
"""

from typing import Any

from fastapi.testclient import TestClient

from tests.helpers import OWNER, GullibleProvider, TitleJudge, run_scan, scan_client

LEAK = "si-other-customer-order"  # the plain rules FAIL this with the gullible bot
SHIPPING = "pos-shipping-times"  # the plain rules PASS this
SHIPPING_TITLE = "Normal request: how long does shipping take?"


def label(client: TestClient, scan_id: int, test_id: str, correct: str) -> Any:
    return client.put(
        f"/scans/{scan_id}/results/{test_id}/label", json={"correct": correct}, headers=OWNER
    )


def accuracy(client: TestClient) -> dict[str, Any]:
    response = client.get("/judge-accuracy", headers=OWNER)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def result(scan: dict[str, Any], test_id: str) -> dict[str, Any]:
    return next(r for r in scan["results"] if r["test_id"] == test_id)


def test_with_no_labels_there_is_nothing_to_report_and_it_says_so() -> None:
    with scan_client([GullibleProvider()]) as client:
        body = accuracy(client)
    assert body["labeled"] == 0
    assert body["agreement"] is None
    assert body["risks"] == []
    assert "not been checked" in body["note"]


def test_a_label_is_saved_shown_on_the_result_and_can_be_changed_or_removed() -> None:
    with scan_client([GullibleProvider()]) as client:
        scan = run_scan(client, "acme-weak")
        scan_id = scan["scan"]["id"]
        assert label(client, scan_id, SHIPPING, "pass").status_code == 200
        assert (
            result(client.get(f"/scans/{scan_id}", headers=OWNER).json(), SHIPPING)["label"]
            == "pass"
        )
        label(client, scan_id, SHIPPING, "fail")
        assert (
            result(client.get(f"/scans/{scan_id}", headers=OWNER).json(), SHIPPING)["label"]
            == "fail"
        )
        assert (
            client.delete(f"/scans/{scan_id}/results/{SHIPPING}/label", headers=OWNER).status_code
            == 200
        )
        assert (
            result(client.get(f"/scans/{scan_id}", headers=OWNER).json(), SHIPPING)["label"] is None
        )


def test_a_label_must_be_pass_or_fail_and_must_belong_to_a_real_result() -> None:
    with scan_client([GullibleProvider()]) as client:
        scan_id = run_scan(client, "acme-weak")["scan"]["id"]
        assert label(client, scan_id, SHIPPING, "maybe").status_code == 422
        assert label(client, scan_id, "no-such-test", "pass").status_code == 404
        assert label(client, 9999, SHIPPING, "pass").status_code == 404


def test_labels_are_owner_only() -> None:
    with scan_client([GullibleProvider()]) as client:
        scan_id = run_scan(client, "acme-weak")["scan"]["id"]
        assert (
            client.put(
                f"/scans/{scan_id}/results/{SHIPPING}/label", json={"correct": "pass"}
            ).status_code
            == 401
        )
        assert client.get("/judge-accuracy").status_code == 401


def test_agreement_false_alarms_and_misses_are_counted_per_risk_with_the_sample_size() -> None:
    # The judge fails the shipping answer (a false alarm if the owner says it was fine) and passes
    # everything else. The leak: the judge passes it, the owner says it should fail (a miss).
    judge = TitleJudge(fail={SHIPPING_TITLE: "The delivery time is wrong."})
    with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
        scan_id = scan["scan"]["id"]
        leak = result(scan, LEAK)
        shipping = result(scan, SHIPPING)
        assert shipping["judge_status"] == "fail" and leak["judge_status"] == "pass"
        label(client, scan_id, SHIPPING, "pass")  # judge said fail: a false alarm
        label(client, scan_id, LEAK, "fail")  # judge said pass: a miss
        body = accuracy(client)
    assert body["labeled"] == 2
    assert body["agree"] == 0
    assert body["false_alarms"] == 1
    assert body["misses"] == 1
    assert body["agreement"] == 0.0
    assert body["small_sample"] is True
    by_risk = {r["risk"]: r for r in body["risks"]}
    assert by_risk[leak["risk"]]["misses"] == 1
    assert by_risk[leak["risk"]]["labeled"] >= 1


def test_a_result_the_judge_could_not_judge_is_left_out_of_the_numbers() -> None:
    judge = TitleJudge(down={SHIPPING_TITLE})
    with scan_client([GullibleProvider()], redflag_providers=[judge]) as client:
        scan = run_scan(client, "acme-weak")
        assert result(scan, SHIPPING)["judge_status"] == "unavailable"
        label(client, scan["scan"]["id"], SHIPPING, "pass")
        body = accuracy(client)
    assert body["labeled"] == 1
    assert body["counted"] == 0
    assert body["agreement"] is None
    assert body["unjudged"] == 1


def test_a_large_enough_sample_is_not_called_small() -> None:
    with scan_client([GullibleProvider()], judge_accuracy_min_sample=5) as client:
        scan = run_scan(client, "acme-weak")
        scan_id = scan["scan"]["id"]
        judged = [r for r in scan["results"] if r["judge_status"] in ("pass", "fail")]
        assert len(judged) >= 5
        for r in judged[:5]:
            label(client, scan_id, r["test_id"], r["judge_status"])
        body = accuracy(client)
    assert body["counted"] == 5
    assert body["agreement"] == 1.0
    assert body["small_sample"] is False
