from pathlib import Path

from shmample.auto_tag import tag_file, tag_folder, tags_for_filename, tags_for_path
from shmample.tag_store import tags_for_sample


def test_matches_a_drum_machine_abbreviation_and_ignores_trailing_tokens():
    # Real filename from the "Samples From Mars" 808 pack survey -
    # trailing velocity index/model/note tokens shouldn't match anything.
    path = Path("808 From Mars/BD 808 5 MP1 G#.wav")
    assert tags_for_filename(path) == {"kick"}


def test_matches_a_full_word_first_token():
    assert tags_for_filename(Path("Conga 2.wav")) == {"conga"}


def test_matches_from_the_parent_folder_when_the_filename_alone_has_no_hit():
    path = Path("07. Cabasa & Shaker/SomeRandomName.wav")
    assert tags_for_filename(path) == {"cabasa", "shaker"}


def test_does_not_false_match_a_vocabulary_word_as_a_substring():
    # "Chick" contains "ch" (closed-hihat) but is a whole other word - only
    # whole tokens should ever match.
    path = Path("S612 From Mars/Chick N Swell/Chick N Swell S612 C3.wav")
    assert tags_for_filename(path) == set()


def test_no_match_returns_an_empty_set():
    assert tags_for_filename(Path("Misc-16-note.wav")) == set()


def test_tag_file_persists_the_derived_tags(tmp_path):
    db_path = tmp_path / "shmample.db"
    path = Path("BD 808.wav")

    tags = tag_file(path, db_path)

    assert tags == {"kick"}
    assert tags_for_sample(path, db_path) == {"kick"}


def test_tag_folder_recurses_and_only_tags_wav_files(tmp_path):
    db_path = tmp_path / "shmample.db"
    (tmp_path / "BD 808.wav").touch()
    (tmp_path / "notes.txt").touch()
    sub = tmp_path / "Sub"
    sub.mkdir()
    (sub / "SD 808.wav").touch()
    (sub / "cover.png").touch()

    count = tag_folder(tmp_path, db_path)

    assert count == 2
    assert tags_for_sample(tmp_path / "BD 808.wav", db_path) == {"kick"}
    assert tags_for_sample(sub / "SD 808.wav", db_path) == {"snare"}
    assert tags_for_sample(tmp_path / "notes.txt", db_path) == set()


def test_tag_folder_is_case_insensitive_about_extension(tmp_path):
    db_path = tmp_path / "shmample.db"
    (tmp_path / "BD 808.WAV").touch()

    count = tag_folder(tmp_path, db_path)

    assert count == 1
    assert tags_for_sample(tmp_path / "BD 808.WAV", db_path) == {"kick"}


def test_tag_folder_calls_the_progress_callback_per_file_with_index_and_total(tmp_path):
    db_path = tmp_path / "shmample.db"
    (tmp_path / "BD 808.wav").touch()
    (tmp_path / "SD 808.wav").touch()
    calls = []

    tag_folder(
        tmp_path,
        db_path,
        on_file_tagged=lambda path, tags, index, total: calls.append((path, tags, index, total)),
    )

    assert len(calls) == 2
    assert (tmp_path / "BD 808.wav", {"kick"}, 1, 2) in calls
    assert (tmp_path / "SD 808.wav", {"snare"}, 2, 2) in calls


def test_tag_folder_never_tags_the_folder_itself(tmp_path):
    db_path = tmp_path / "shmample.db"
    # Folder name itself has vocabulary words in it - only files beneath
    # it should end up tagged, never the folder path.
    bd_folder = tmp_path / "BD Kit"
    bd_folder.mkdir()
    (bd_folder / "sample.wav").touch()

    tag_folder(tmp_path, db_path)

    assert tags_for_sample(bd_folder, db_path) == set()


def test_tags_for_path_without_root_matches_tags_for_filename():
    path = Path("Loopmasters - Deep House/BD 808.wav")
    assert tags_for_path(path) == tags_for_filename(path)


def test_tags_for_path_adds_the_pack_folder_as_a_tag(tmp_path):
    path = tmp_path / "Loopmasters Deep House" / "BD 808.wav"
    assert tags_for_path(path, root=tmp_path) == {"kick", "loopmasters-deep-house"}


def test_tags_for_path_skips_generic_folder_words(tmp_path):
    # "Drums" and "WAV" are both real folder names a pack might use, but
    # neither says anything specific enough about *this* pack to be worth
    # a tag - every pack has drums, most ship as WAV.
    path = tmp_path / "Drums" / "WAV" / "BD 808.wav"
    assert tags_for_path(path, root=tmp_path) == {"kick"}


def test_tags_for_path_favours_folders_closest_to_root(tmp_path):
    # Vendor/Pack are the pack's own identity; Kontakt/Samples/Kicks are
    # file-type/DAW-export noise further down - only the first
    # MAX_FOLDER_TAGS non-generic folders (closest to root) should survive.
    path = tmp_path / "SomeVendor" / "Some Pack" / "Kontakt" / "Samples" / "Kicks" / "BD.wav"
    assert tags_for_path(path, root=tmp_path) == {"kick", "somevendor", "some-pack"}


def test_tags_for_path_ignores_a_path_not_under_root(tmp_path):
    other = tmp_path / "elsewhere" / "BD 808.wav"
    assert tags_for_path(other, root=tmp_path / "configured-root") == {"kick"}


def test_tag_file_persists_the_pack_folder_tag_when_root_given(tmp_path):
    db_path = tmp_path / "shmample.db"
    path = tmp_path / "Loopmasters Deep House" / "BD 808.wav"

    tags = tag_file(path, db_path, root=tmp_path)

    assert tags == {"kick", "loopmasters-deep-house"}
    assert tags_for_sample(path, db_path) == {"kick", "loopmasters-deep-house"}


def test_tag_folder_persists_pack_folder_tags_when_root_given(tmp_path):
    db_path = tmp_path / "shmample.db"
    pack = tmp_path / "Loopmasters Deep House"
    pack.mkdir()
    (pack / "BD 808.wav").touch()

    tag_folder(tmp_path, db_path, root=tmp_path)

    assert tags_for_sample(pack / "BD 808.wav", db_path) == {"kick", "loopmasters-deep-house"}
