from shmample.app import ShmampleApp


async def test_starts_on_ansi_dark_theme():
    app = ShmampleApp(samples_directories=[])
    async with app.run_test():
        assert app.theme == "ansi-dark"
        # native_ansi_color is what actually disables Textual's
        # ANSIToTruecolor filter - this is the bit that makes colours
        # come from the terminal's own palette rather than fixed hex.
        assert app.native_ansi_color is True
