import contextlib

from shmample.tag_store import (
    auto_assign_tag,
    auto_assign_tag_batch,
    connect,
    delete_tag,
    remove_tag_from_sample,
    tag_counts,
    tags_for_sample,
)


def test_auto_assign_creates_the_tag_and_assigns_it(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"

    changed = auto_assign_tag(kick, "kick", db_path)

    assert changed is True
    assert tags_for_sample(kick, db_path) == {"kick"}


def test_auto_assign_is_idempotent(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"

    auto_assign_tag(kick, "kick", db_path)
    changed_again = auto_assign_tag(kick, "kick", db_path)

    assert changed_again is False
    assert tags_for_sample(kick, db_path) == {"kick"}


def test_auto_assign_does_not_revive_a_manually_removed_pairing(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    auto_assign_tag(kick, "kick", db_path)
    remove_tag_from_sample(kick, "kick", db_path)

    changed = auto_assign_tag(kick, "kick", db_path)

    assert changed is False
    assert tags_for_sample(kick, db_path) == set()


def test_auto_assign_does_not_revive_a_deleted_tag(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    other = tmp_path / "other.wav"
    auto_assign_tag(kick, "kick", db_path)
    delete_tag("kick", db_path)

    changed = auto_assign_tag(other, "kick", db_path)

    assert changed is False
    assert tags_for_sample(other, db_path) == set()


def test_delete_tag_cascades_to_every_sample(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    other_kick = tmp_path / "other_kick.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(other_kick, "kick", db_path)

    delete_tag("kick", db_path)

    assert tags_for_sample(kick, db_path) == set()
    assert tags_for_sample(other_kick, db_path) == set()


def test_remove_tag_from_sample_only_affects_that_sample(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    other_kick = tmp_path / "other_kick.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(other_kick, "kick", db_path)

    remove_tag_from_sample(kick, "kick", db_path)

    assert tags_for_sample(kick, db_path) == set()
    assert tags_for_sample(other_kick, db_path) == {"kick"}


def test_removing_or_deleting_a_never_assigned_tag_does_not_raise(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"

    remove_tag_from_sample(kick, "nonexistent", db_path)
    delete_tag("nonexistent", db_path)

    assert tags_for_sample(kick, db_path) == set()


def test_auto_assign_tag_batch_shares_a_connection_and_needs_an_explicit_commit(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"

    with contextlib.closing(connect(db_path)) as connection:
        changed = auto_assign_tag_batch(connection, kick, "kick")
        # Not committed yet - a separate connection shouldn't see it.
        assert changed is True
        assert tags_for_sample(kick, db_path) == set()

        connection.commit()

    assert tags_for_sample(kick, db_path) == {"kick"}


def test_auto_assign_tag_batch_follows_the_same_rescan_rule_as_auto_assign_tag(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    auto_assign_tag(kick, "kick", db_path)
    remove_tag_from_sample(kick, "kick", db_path)

    with contextlib.closing(connect(db_path)) as connection:
        changed = auto_assign_tag_batch(connection, kick, "kick")
        connection.commit()

    assert changed is False
    assert tags_for_sample(kick, db_path) == set()


def test_tag_counts_is_empty_with_no_tags(tmp_path):
    db_path = tmp_path / "shmample.db"
    assert tag_counts(db_path) == []


def test_tag_counts_reflects_active_assignments_sorted_by_name(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(tmp_path / "kick1.wav", "kick", db_path)
    auto_assign_tag(tmp_path / "kick2.wav", "kick", db_path)
    auto_assign_tag(tmp_path / "snare1.wav", "snare", db_path)

    assert tag_counts(db_path) == [("kick", 2), ("snare", 1)]


def test_tag_counts_excludes_a_removed_pairing_but_keeps_the_tag(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    auto_assign_tag(kick, "kick", db_path)

    remove_tag_from_sample(kick, "kick", db_path)

    assert tag_counts(db_path) == [("kick", 0)]


def test_tag_counts_excludes_a_deleted_tag_entirely(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(tmp_path / "kick.wav", "kick", db_path)

    delete_tag("kick", db_path)

    assert tag_counts(db_path) == []


def test_tags_for_sample_keeps_different_samples_independent(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    snare = tmp_path / "snare.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(snare, "snare", db_path)

    assert tags_for_sample(kick, db_path) == {"kick"}
    assert tags_for_sample(snare, db_path) == {"snare"}
