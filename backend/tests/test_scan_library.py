"""The catalog and the test library: their shape, their mapping to each other and their coverage."""

from collections import Counter

from redflag_backend.sandbox.loader import load_bots
from redflag_backend.scan.catalog import load_catalog
from redflag_backend.scan.checks import CHECKS, missing_needs
from redflag_backend.scan.suite import load_suite

EXPECTED_RISKS = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "LLM05": "Improper Output Handling",
    "LLM06": "Excessive Agency",
    "LLM07": "System Prompt Leakage",
    "LLM08": "Vector and Embedding Weaknesses",
    "LLM09": "Misinformation",
    "LLM10": "Unbounded Consumption",
}


def test_the_catalog_holds_all_ten_risks_and_says_where_it_came_from() -> None:
    catalog = load_catalog()
    assert {r.id: r.name for r in catalog.risks} == EXPECTED_RISKS
    assert catalog.version == "owasp-llm-2025"
    assert catalog.source.startswith("https://genai.owasp.org/")
    assert catalog.retrieved  # when the list was checked against OWASP's own page
    assert all(r.description for r in catalog.risks)


def test_every_negative_test_maps_to_a_real_risk_and_positive_tests_to_none() -> None:
    catalog, suite = load_catalog(), load_suite()
    known = {r.id for r in catalog.risks}
    for test in suite.tests:
        if test.kind == "negative":
            assert test.risk in known, test.id
        else:
            assert test.risk is None, test.id


def test_the_suite_has_the_agreed_size_and_covers_every_group() -> None:
    suite = load_suite()
    assert suite.suite_version >= 1
    assert len(suite.tests) == 16
    assert len({t.id for t in suite.tests}) == 16  # ids are unique
    by_risk = Counter(t.risk for t in suite.tests if t.kind == "negative")
    assert by_risk["LLM01"] >= 4  # prompt injection, including poisoned documents
    assert by_risk["LLM02"] >= 3
    assert by_risk["LLM05"] >= 1
    assert by_risk["LLM06"] >= 3
    assert by_risk["LLM07"] >= 1
    assert sum(1 for t in suite.tests if t.kind == "positive") >= 3


def test_there_are_poisoned_document_tests() -> None:
    suite = load_suite()
    poisoned = [t for t in suite.tests if "lookup_article" in t.needs.tools]
    assert len(poisoned) >= 2


def test_every_test_names_a_check_that_exists_and_has_a_message() -> None:
    for test in load_suite().tests:
        assert test.check.type in CHECKS, test.id
        assert test.message.strip(), test.id
        assert test.title.strip(), test.id


def test_every_test_applies_to_both_acme_bots() -> None:
    bots = load_bots().bots
    for definition in bots.values():
        for test in load_suite().tests:
            assert missing_needs(test, set(definition.tools), definition.data) == [], (
                definition.config.id,
                test.id,
            )


def test_every_rule_a_test_cites_is_in_the_bots_policy() -> None:
    policy = load_bots().bots["acme-weak"].policy
    for test in load_suite().tests:
        if test.kind == "negative":
            assert test.rule in policy.rules, test.id
