from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Label

from shmample.settings import Settings, save_settings
from shmample.tag_store import auto_assign_tag, delete_tag, tag_counts, tags_for_sample
from shmample.widgets.tag_browser import TagBrowser


class TagBrowserApp(App):
    def __init__(self, db_path: Path, settings_path: Path | None = None) -> None:
        super().__init__()
        self.db_path = db_path
        self.settings_path = settings_path

    def compose(self) -> ComposeResult:
        yield TagBrowser(self.db_path, self.settings_path, id="tags")


def _labels(tags: TagBrowser) -> list[str]:
    return [str(label.render()) for label in tags.query(Label)]


async def test_shows_placeholder_when_no_tags_exist(tmp_path):
    app = TagBrowserApp(tmp_path / "shmample.db")
    async with app.run_test():
        tags = app.query_one(TagBrowser)
        assert _labels(tags) == ["No tags yet"]


async def test_lists_tags_sorted_by_name_with_sample_counts(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(Path("kick1.wav"), "kick", db_path)
    auto_assign_tag(Path("kick2.wav"), "kick", db_path)
    auto_assign_tag(Path("snare1.wav"), "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test():
        tags = app.query_one(TagBrowser)
        assert _labels(tags) == ["kick (2)", "snare (1)"]


async def test_refresh_list_picks_up_newly_assigned_tags(tmp_path):
    db_path = tmp_path / "shmample.db"
    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        assert _labels(tags) == ["No tags yet"]

        auto_assign_tag(Path("kick.wav"), "kick", db_path)
        tags.refresh_list()
        await pilot.pause()

        assert _labels(tags) == ["kick (1)"]


async def test_deleted_tag_drops_out_of_the_list(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(Path("kick.wav"), "kick", db_path)
    auto_assign_tag(Path("snare.wav"), "snare", db_path)
    delete_tag("kick", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test():
        tags = app.query_one(TagBrowser)
        assert _labels(tags) == ["snare (1)"]


async def test_set_scope_narrows_the_listing_to_that_folder(tmp_path):
    db_path = tmp_path / "shmample.db"
    pack_a = tmp_path / "PackA"
    pack_b = tmp_path / "PackB"
    auto_assign_tag(pack_a / "kick.wav", "kick", db_path)
    auto_assign_tag(pack_b / "snare.wav", "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        assert _labels(tags) == ["kick (1)", "snare (1)"]

        tags.set_scope(pack_a)
        await pilot.pause()
        assert _labels(tags) == ["kick (1)"]

        tags.set_scope(None)
        await pilot.pause()
        assert _labels(tags) == ["kick (1)", "snare (1)"]


def _rendered_styles(tags: TagBrowser) -> list[str | None]:
    """The style of each row's rendered content, or None for a plain
    (unselected) row - lets a test tell a styled-green selected row apart
    from a normal one. Label.render() returns Textual's own Content type
    (text plus a list of (start, end, style) spans), not a plain rich.Text,
    so styling shows up as a span rather than a `.style` attribute."""
    styles = []
    for label in tags.query(Label):
        spans = label.render().spans
        styles.append(spans[0].style if spans else None)
    return styles


async def test_space_selects_a_tag_and_posts_selection_changed(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(Path("kick.wav"), "kick", db_path)
    auto_assign_tag(Path("snare.wav"), "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")
        await pilot.pause()

        assert tags.selected_tags == {"kick"}
        assert _rendered_styles(tags) == [TagBrowser.SELECTED_STYLE, None]


async def test_space_again_deselects_the_tag(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(Path("kick.wav"), "kick", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")
        await pilot.press("space")
        await pilot.pause()

        assert tags.selected_tags == set()
        assert _rendered_styles(tags) == [None]


async def test_multiple_tags_can_be_selected_at_once(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(Path("kick.wav"), "kick", db_path)
    auto_assign_tag(Path("snare.wav"), "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")
        await pilot.press("j")
        await pilot.press("space")
        await pilot.pause()

        assert tags.selected_tags == {"kick", "snare"}
        assert _rendered_styles(tags) == [TagBrowser.SELECTED_STYLE, TagBrowser.SELECTED_STYLE]


async def test_shift_c_asks_for_confirmation_before_cleaning_anything(tmp_path):
    db_path = tmp_path / "shmample.db"
    settings_path = tmp_path / "settings.json"  # never written - no tracked directories
    gone = tmp_path / "gone.wav"  # never written - simulates a since-deleted file
    auto_assign_tag(gone, "drums", db_path)

    app = TagBrowserApp(db_path, settings_path)
    async with app.run_test() as pilot:
        screens_before = len(app.screen_stack)
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("C")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before + 1
        assert tags_for_sample(gone, db_path) == {"drums"}  # untouched while unconfirmed

        await pilot.press("escape")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before
        assert tags_for_sample(gone, db_path) == {"drums"}


async def test_shift_c_confirm_cleans_up_a_file_thats_actually_gone(tmp_path):
    # One of the two ways this exists for: "drums" looks perfectly healthy
    # at count 2 even though one of its two samples no longer exists on
    # disk at all - counting alone can't find this, only checking the
    # filesystem can.
    db_path = tmp_path / "shmample.db"
    settings_path = tmp_path / "settings.json"
    kept = tmp_path / "kept.wav"
    kept.write_bytes(b"")
    gone = tmp_path / "gone.wav"
    save_settings(Settings(samples_directories=[tmp_path]), settings_path)
    auto_assign_tag(kept, "drums", db_path)
    auto_assign_tag(gone, "drums", db_path)
    auto_assign_tag(gone, "only-gone", db_path)

    app = TagBrowserApp(db_path, settings_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()
        assert _labels(tags) == ["drums (2)", "only-gone (1)"]

        await pilot.press("C")
        await pilot.pause()
        await pilot.press("enter")  # "Clean up unused tags" is the first, highlighted option
        await pilot.pause()

        assert _labels(tags) == ["drums (1)"]
        assert tags_for_sample(kept, db_path) == {"drums"}
        assert tags_for_sample(gone, db_path) == set()


async def test_shift_c_confirm_cleans_up_a_file_thats_on_disk_but_no_longer_tracked(tmp_path):
    # The actual bug report this exists for: a samples directory removed
    # before remove_tags_under existed left "drums" looking perfectly
    # healthy - the file was never touched (removing a path doesn't touch
    # disk), so it's still sitting right there, just not under any
    # currently configured samples directory any more.
    db_path = tmp_path / "shmample.db"
    settings_path = tmp_path / "settings.json"  # never written - nothing is tracked
    kick = tmp_path / "old-drive" / "kick.wav"
    kick.parent.mkdir()
    kick.write_bytes(b"")
    auto_assign_tag(kick, "drums", db_path)

    app = TagBrowserApp(db_path, settings_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()
        assert _labels(tags) == ["drums (1)"]  # looks perfectly healthy

        await pilot.press("C")
        await pilot.pause()
        await pilot.press("enter")  # "Clean up unused tags" is the first, highlighted option
        await pilot.pause()

        assert _labels(tags) == ["No tags yet"]
        assert kick.is_file()  # cleaning up tags never touches files on disk
        assert tags_for_sample(kick, db_path) == set()


async def test_shift_c_with_nothing_unused_notifies_and_asks_nothing(tmp_path):
    db_path = tmp_path / "shmample.db"
    settings_path = tmp_path / "settings.json"
    kick = tmp_path / "kick.wav"
    kick.write_bytes(b"")
    save_settings(Settings(samples_directories=[tmp_path]), settings_path)
    auto_assign_tag(kick, "drums", db_path)

    app = TagBrowserApp(db_path, settings_path)
    async with app.run_test() as pilot:
        screens_before = len(app.screen_stack)
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("C")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before  # no confirmation needed
        assert _labels(tags) == ["drums (1)"]


async def test_d_asks_for_confirmation_before_deleting_a_tag(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    auto_assign_tag(kick, "kick", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        screens_before = len(app.screen_stack)
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("d")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before + 1
        assert tags_for_sample(kick, db_path) == {"kick"}  # untouched while unconfirmed

        await pilot.press("escape")
        await pilot.pause()

        assert len(app.screen_stack) == screens_before
        assert _labels(tags) == ["kick (1)"]


async def test_d_confirm_soft_deletes_the_tag_and_it_survives_a_rescan(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    snare = tmp_path / "snare.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(snare, "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()
        assert _labels(tags) == ["kick (1)", "snare (1)"]

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")  # "Delete 'kick'" is the first, highlighted option
        await pilot.pause()

        assert _labels(tags) == ["snare (1)"]
        assert tags_for_sample(kick, db_path) == set()

        # A rescan must not silently bring a deleted tag back.
        auto_assign_tag(kick, "kick", db_path)
        assert tags_for_sample(kick, db_path) == set()
        assert tag_counts(db_path) == [("snare", 1)]


async def test_deleting_a_selected_tag_also_drops_it_from_the_active_filter(tmp_path):
    db_path = tmp_path / "shmample.db"
    kick = tmp_path / "kick.wav"
    snare = tmp_path / "snare.wav"
    auto_assign_tag(kick, "kick", db_path)
    auto_assign_tag(snare, "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()

        await pilot.press("space")  # select "kick"
        await pilot.pause()
        assert tags.selected_tags == {"kick"}

        await pilot.press("d")
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

        assert tags.selected_tags == set()


async def test_vim_keys_navigate(tmp_path):
    db_path = tmp_path / "shmample.db"
    auto_assign_tag(Path("kick.wav"), "kick", db_path)
    auto_assign_tag(Path("snare.wav"), "snare", db_path)

    app = TagBrowserApp(db_path)
    async with app.run_test() as pilot:
        tags = app.query_one(TagBrowser)
        tags.focus()
        await pilot.pause()
        assert tags.index == 0

        await pilot.press("j")
        assert tags.index == 1

        await pilot.press("k")
        assert tags.index == 0
