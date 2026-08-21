from textual.binding import Binding


class VimGoToTopAndBottom:
    """Adds vim's "gg" (top) / "G" (bottom) motions to any list-like pane,
    on top of whatever j/k/h/l bindings it already has (see
    vim_option_list.py for that half of the same idea - kept separate
    since not every list-like pane here is an OptionList, so a single
    shared base class won't fit all of them).

    "gg" genuinely needs the double keypress to match vim - tracked here
    as a short-lived pending flag cleared by a timer, rather than binding
    a bare "g" straight to the top, since a lone "g" is meaningless in
    vim (it's a prefix for gg, ge, gt, ...) and shouldn't silently move
    the cursor on its own.

    Mixed in alongside the widget's real base class (e.g.
    `class ConfigList(ListView, VimGoToTopAndBottom)`) - but unlike CSS,
    Textual's BINDINGS merging (DOMNode._merge_bindings) only looks at
    MRO entries that are themselves DOMNode subclasses, and this mixin
    deliberately isn't one (mixing DOMNode in twice via a second base
    plays badly with Widget's own init). So BINDINGS here still needs
    concatenating into each subclass's own BINDINGS list by hand -
    `BINDINGS = [...] + VimGoToTopAndBottom.BINDINGS` - same as any other
    multi-source Binding list already in this codebase (see
    BankPickerModal). Each subclass implements go_to_top()/go_to_bottom()
    in terms of whatever its real base class already offers (e.g.
    DataTable's action_scroll_top()).
    """

    GG_TIMEOUT = 0.6

    BINDINGS = [
        Binding("g", "vim_g_pressed", "Top (vim gg)", show=False),
        Binding("G", "go_to_bottom", "Bottom (vim)", show=False),
    ]

    _vim_gg_pending_timer = None

    def action_vim_g_pressed(self) -> None:
        if self._vim_gg_pending_timer is not None:
            self._vim_gg_pending_timer.stop()
            self._vim_gg_pending_timer = None
            self.go_to_top()
        else:
            self._vim_gg_pending_timer = self.set_timer(self.GG_TIMEOUT, self._clear_vim_gg_pending)

    def _clear_vim_gg_pending(self) -> None:
        self._vim_gg_pending_timer = None

    def action_go_to_bottom(self) -> None:
        self.go_to_bottom()

    def go_to_top(self) -> None:
        raise NotImplementedError

    def go_to_bottom(self) -> None:
        raise NotImplementedError
