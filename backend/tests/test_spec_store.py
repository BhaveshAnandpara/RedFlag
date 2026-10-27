"""Saving specs over a real Postgres: an ID and hash, locking at approval, new versions."""

import pytest
from sqlalchemy import create_engine, text

from redflag_backend.specs.oracle import (
    Conversation,
    Oracle,
    ReplyContains,
    ToolCalled,
    Turn,
    evaluate,
)
from redflag_backend.specs.spec import TestSpec, spec_hash
from redflag_backend.specs.store import NoSuchSpec, SpecStore
from tests.helpers import TEST_DB_URL
from tests.test_spec_model import make


@pytest.fixture
def store() -> SpecStore:
    return SpecStore(create_engine(TEST_DB_URL), clock=lambda: 1000.0)


def test_a_new_spec_is_saved_with_an_id_a_hash_and_version_one_unlocked(store: SpecStore) -> None:
    spec = make()
    saved = store.create(spec)
    assert saved.spec_id.startswith("spec-") and saved.version == 1
    assert saved.hash == spec_hash(spec) and saved.locked is False and saved.locked_at is None
    assert store.get(saved.spec_id) == saved
    assert store.create(spec).spec_id != saved.spec_id  # each test is its own spec


def test_what_is_read_back_is_exactly_what_was_saved_including_the_oracle(store: SpecStore) -> None:
    spec = make(
        oracle=Oracle(broke_if=ToolCalled(tool="delete_sheet"), held_if=ReplyContains(text="no"))
    )
    back = store.get(store.create(spec).spec_id).spec
    assert back == spec and spec_hash(back) == spec_hash(spec)
    assert back.broke_if == spec.broke_if and back.held_if == spec.held_if
    convo = Conversation(turns=[Turn(role="assistant", content="no")], logs=[])
    assert evaluate(back.oracle, convo) == evaluate(spec.oracle, convo)


def test_a_draft_is_edited_in_place_and_keeps_one_version(store: SpecStore) -> None:
    saved = store.create(make())
    edited = store.edit(saved.spec_id, make(opening_message="Please delete Sheet3."))
    assert edited.version == 1 and edited.locked is False
    assert edited.hash == spec_hash(make(opening_message="Please delete Sheet3."))
    assert len(store.history(saved.spec_id)) == 1
    assert store.get(saved.spec_id).spec.opening_message == "Please delete Sheet3."


def test_approving_locks_the_spec_and_locking_twice_changes_nothing(store: SpecStore) -> None:
    saved = store.create(make())
    locked = store.lock(saved.spec_id)
    assert locked.locked is True and locked.locked_at == 1000.0
    assert locked.hash == saved.hash and locked.spec == saved.spec
    assert store.lock(saved.spec_id) == locked


def test_changing_a_locked_spec_makes_a_new_version_and_leaves_the_old_one_untouched(
    store: SpecStore,
) -> None:
    saved = store.create(make())
    store.lock(saved.spec_id)
    changed = make(repeats=3)
    second = store.edit(saved.spec_id, changed)
    assert second.version == 2 and second.locked is False and second.hash == spec_hash(changed)
    assert second.hash != saved.hash
    first = store.get(saved.spec_id, version=1)
    assert first.locked is True and first.hash == saved.hash and first.spec == make()
    assert store.get(saved.spec_id).version == 2
    assert [s.version for s in store.history(saved.spec_id)] == [1, 2]
    # a second edit to the unlocked version 2 stays version 2
    assert store.edit(saved.spec_id, make(repeats=4)).version == 2
    assert len(store.history(saved.spec_id)) == 2


def test_saving_the_same_content_again_makes_no_new_version(store: SpecStore) -> None:
    saved = store.create(make())
    store.lock(saved.spec_id)
    again = store.edit(saved.spec_id, make())
    assert again.version == 1 and again.locked is True
    assert len(store.history(saved.spec_id)) == 1


def test_locking_many_specs_at_approval_locks_each_one(store: SpecStore) -> None:
    ids = [store.create(make(opening_message=f"message {i}")).spec_id for i in range(3)]
    assert all(s.locked for s in store.lock_many(ids))
    assert all(store.get(i).locked for i in ids)


def test_an_unknown_spec_is_a_clear_error(store: SpecStore) -> None:
    for call in (
        lambda: store.get("spec-nope"),
        lambda: store.get("spec-nope", version=1),
        lambda: store.history("spec-nope"),
        lambda: store.edit("spec-nope", make()),
        lambda: store.lock("spec-nope"),
    ):
        with pytest.raises(NoSuchSpec):
            call()


def test_the_table_cannot_hold_two_rows_for_one_version(store: SpecStore) -> None:
    saved = store.create(make())
    engine = create_engine(TEST_DB_URL)
    with pytest.raises(Exception, match="uq_test_specs_id_version"), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO test_specs (spec_id, version, spec_hash, spec, created_at) "
                "VALUES (:id, 1, 'x', '{}'::jsonb, 0)"
            ),
            {"id": saved.spec_id},
        )
    assert isinstance(store.get(saved.spec_id).spec, TestSpec)
