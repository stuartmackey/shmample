import contextlib

from shmample.tag_store import (
    any_sample_under_matches_all_tags,
    auto_assign_tag,
    auto_assign_tag_batch,
    connect,
    delete_tag,
    remove_tag_from_sample,
    tag_counts,
    tags_for_sample,
    tags_for_samples,
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


def test_tag_counts_scoped_to_a_root_only_counts_samples_under_it(tmp_path):
    db_path = tmp_path / "shmample.db"
    pack_a = tmp_path / "PackA"
    pack_b = tmp_path / "PackB"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)
    auto_assign_tag(pack_a / "snare.wav", "snare", db_path)
    auto_assign_tag(pack_b / "kick.wav", "kick", db_path)

    assert tag_counts(db_path, root=pack_a) == [("kick", 1), ("snare", 1)]
    assert tag_counts(db_path, root=pack_b) == [("kick", 1)]


def test_tag_counts_scoped_to_a_root_drops_tags_with_no_samples_in_scope(tmp_path):
    # Unlike the unscoped listing, a tag entirely outside the scope isn't
    # shown at all - not even as "(0)".
    db_path = tmp_path / "shmample.db"
    pack_a = tmp_path / "PackA"
    pack_b = tmp_path / "PackB"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)
    auto_assign_tag(pack_b / "snare.wav", "snare", db_path)

    assert tag_counts(db_path, root=pack_a) == [("kick", 1)]


def test_tag_counts_scoped_to_a_root_matches_the_root_itself(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    auto_assign_tag(kick, "kick", db_path)

    assert tag_counts(db_path, root=kick) == [("kick", 1)]


def test_tag_counts_scoped_to_a_root_does_not_match_a_sibling_with_a_similar_prefix(tmp_path):
    # "/tmp/.../PackA" shouldn't match "/tmp/.../PackAB/..." - a naive
    # string-prefix check would get this wrong.
    db_path = tmp_path / "shmample.db"
    pack_a = tmp_path / "PackA"
    pack_ab = tmp_path / "PackAB"
    auto_assign_tag(pack_ab / "kick.wav", "kick", db_path)

    assert tag_counts(db_path, root=pack_a) == []


def test_tags_for_samples_batches_the_lookup(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    snare = tmp_path / "snare.wav"
    untagged = tmp_path / "untagged.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(kick, "808", db_path)
    auto_assign_tag(snare, "snare", db_path)

    result = tags_for_samples([kick, snare, untagged], db_path)

    assert result == {str(kick): {"kick", "808"}, str(snare): {"snare"}}


def test_tags_for_samples_with_no_paths_makes_no_query_and_returns_empty(tmp_path):
    db_path = tmp_path / "shmample.db"
    assert tags_for_samples([], db_path) == {}


def test_any_sample_under_matches_all_tags_requires_every_tag_on_one_sample(tmp_path):
    db_path = tmp_path / "shmample.db"
    pack = tmp_path / "Pack"
    # kick.wav has both tags together; snare.wav has only one of them -
    # the AND has to hold on a single sample, not just somewhere in scope.
    auto_assign_tag(pack / "kick.wav", "kick", db_path)
    auto_assign_tag(pack / "kick.wav", "808", db_path)
    auto_assign_tag(pack / "snare.wav", "808", db_path)

    assert any_sample_under_matches_all_tags(pack, {"kick", "808"}, db_path) is True
    assert any_sample_under_matches_all_tags(pack, {"snare", "808"}, db_path) is False


def test_any_sample_under_matches_all_tags_respects_the_root_boundary(tmp_path):
    db_path = tmp_path / "shmample.db"
    pack_a = tmp_path / "PackA"
    pack_ab = tmp_path / "PackAB"
    auto_assign_tag(pack_ab / "kick.wav", "kick", db_path)

    assert any_sample_under_matches_all_tags(pack_a, {"kick"}, db_path) is False
    assert any_sample_under_matches_all_tags(pack_ab, {"kick"}, db_path) is True


def test_any_sample_under_matches_all_tags_with_no_tags_is_always_true(tmp_path):
    db_path = tmp_path / "shmample.db"
    assert any_sample_under_matches_all_tags(tmp_path, set(), db_path) is True


def test_tags_for_sample_keeps_different_samples_independent(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    snare = tmp_path / "snare.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(snare, "snare", db_path)

    assert tags_for_sample(kick, db_path) == {"kick"}
    assert tags_for_sample(snare, db_path) == {"snare"}
