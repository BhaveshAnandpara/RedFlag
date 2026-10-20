"""MITRE ATLAS tags on the OWASP risks (W5).

The mapping is Redflag's own best match between the two lists, with its source and the date it was
checked. Where there is no good ATLAS technique the list is empty, and it says so; nothing is
invented to fill a gap.
"""

import re

from redflag_backend.scan.atlas import ATLAS
from redflag_backend.scan.catalog import load_catalog
from tests.helpers import OWNER, GullibleProvider, run_scan, scan_client

TECHNIQUE_ID = re.compile(r"^AML\.T\d{4}(\.\d{3})?$")


def test_every_owasp_risk_has_an_entry_and_every_technique_has_a_real_looking_id_and_a_name() -> (
    None
):
    catalog = load_catalog()
    assert set(ATLAS.by_risk) == {risk.id for risk in catalog.risks}
    for techniques in ATLAS.by_risk.values():
        for technique in techniques:
            assert TECHNIQUE_ID.match(technique.id), technique.id
            assert technique.name.strip()


def test_the_mapping_says_where_it_came_from_when_it_was_checked_and_that_it_is_a_best_match() -> (
    None
):
    assert ATLAS.source.startswith("https://atlas.mitre.org")
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", ATLAS.checked)
    assert "best match" in ATLAS.note.lower()
    assert ATLAS.version


def test_the_main_risks_map_to_the_techniques_they_are_known_for() -> None:
    ids = {risk: [t.id for t in techniques] for risk, techniques in ATLAS.by_risk.items()}
    assert (
        "AML.T0051" in ids["LLM01"] and "AML.T0054" in ids["LLM01"]
    )  # prompt injection, jailbreak
    assert ids["LLM02"] == ["AML.T0057"]  # data leakage
    assert ids["LLM06"] == ["AML.T0053"]  # agent tool invocation
    assert ids["LLM07"] == ["AML.T0056"]  # system prompt extraction


def test_a_risk_with_no_good_match_has_an_empty_list_not_a_guess() -> None:
    assert ATLAS.by_risk["LLM09"] == []  # misinformation


def test_the_catalog_endpoint_carries_the_tags_and_their_source() -> None:
    with scan_client([GullibleProvider()]) as client:
        body = client.get("/catalog", headers=OWNER).json()
    by_id = {r["id"]: r for r in body["risks"]}
    assert [t["id"] for t in by_id["LLM07"]["atlas"]] == ["AML.T0056"]
    assert by_id["LLM09"]["atlas"] == []
    assert body["atlas"]["source"].startswith("https://atlas.mitre.org")
    assert body["atlas"]["checked"] == ATLAS.checked


def test_every_scan_summary_carries_the_tags_for_its_risks_including_older_scans() -> None:
    with scan_client([GullibleProvider()]) as client:
        scan = run_scan(client, "acme-weak")
    risks = {r["id"]: r for r in scan["summary"]["risks"]}
    assert [t["id"] for t in risks["LLM02"]["atlas"]] == ["AML.T0057"]
    assert all("atlas" in r for r in scan["summary"]["risks"])
    assert scan["summary"]["atlas"]["version"] == ATLAS.version
