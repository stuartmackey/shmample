from textual.binding import Binding
from textual.widgets import OptionList


class VimOptionList(OptionList):
    """OptionList plus vim j/k, consistent with the rest of the app.

    Shared by ConfigList's modals and the assignment grid's bank/pad
    pickers - split out rather than duplicated in each module.

    Deliberately doesn't get VimGoToTopAndBottom's gg/G on top of this -
    BankPickerModal binds every single letter (including lowercase "g",
    for Bank G) directly to its own pick, and a focused widget's own
    bindings win over its screen's, so a "g" binding here would silently
    swallow that pick before BankPickerModal ever saw it. None of this
    class's users have enough items for "jump to top/bottom" to earn its
    keep over that anyway - the bank/pad pickers are built entirely
    around every key being a direct pick, and the confirm dialogs only
    ever have two options.
    """

    BINDINGS = [
        Binding("j", "cursor_down", "Down (vim)", show=False),
        Binding("k", "cursor_up", "Up (vim)", show=False),
    ]
