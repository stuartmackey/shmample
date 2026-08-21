from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Label

from shmample.tag_store import auto_assign_tag, delete_tag
from shmample.widgets.tag_browser import TagBrowser


class TagBrowserApp(App):
    def __init__(self, db_path: Path) -> None:
        super().__init__()
        self.db_path = db_path

    def compose(self) -> ComposeResult:
        yield TagBrowser(self.db_path, id="tags")


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
