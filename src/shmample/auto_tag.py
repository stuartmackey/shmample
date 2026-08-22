import contextlib
import re
from collections.abc import Callable
from pathlib import Path

from shmample import tag_store
from shmample.sample_store import DEFAULT_DB_PATH

_TOKEN_RE = re.compile(r"[A-Za-z]+")

# How many files' worth of tags to batch into one commit during a folder
# scan (see tag_folder) - trades a small amount of "how much could be lost
# to a crash mid-run" (auto-tagging is idempotent, so re-running just picks
# up where it left off) for a large cut in fsync overhead versus committing
# per file, let alone per (sample, tag) pair.
COMMIT_BATCH_SIZE = 200

# Naming-convention vocabulary catalogued against the real "Samples From
# Mars" library in 01-auto-tagging.md - abbreviation and full-word
# variants of the same instrument both map to one canonical tag. A few
# tokens found in the survey are deliberately left out rather than
# guessed at: bare "Bass" is too ambiguous (bass drum vs. a bass/synth
# sample), and "MC" had no confirmed meaning. "HC" is mapped to clap on
# the strength of its standard meaning (hand clap) on the machines these
# packs emulate.
_VOCABULARY = {
    "bd": "kick",
    "kick": "kick",
    "sd": "snare",
    "snare": "snare",
    "ch": "closed-hihat",
    "oh": "open-hihat",
    "hh": "hihat",
    "hihat": "hihat",
    "cy": "cymbal",
    "cym": "cymbal",
    "cymbal": "cymbal",
    "crash": "crash",
    "ride": "ride",
    "cp": "clap",
    "clap": "clap",
    "hc": "clap",
    "cb": "cowbell",
    "cowb": "cowbell",
    "cowbell": "cowbell",
    "rs": "rim",
    "rim": "rim",
    "rimshot": "rim",
    "sidestick": "rim",
    "cl": "claves",
    "clave": "claves",
    "claves": "claves",
    "ma": "maracas",
    "maracas": "maracas",
    "lt": "tom",
    "mt": "tom",
    "ht": "tom",
    "tom": "tom",
    "conga": "conga",
    "bongo": "bongo",
    "timbale": "timbale",
    "tamb": "tambourine",
    "tambourine": "tambourine",
    "cabasa": "cabasa",
    "shaker": "shaker",
    "agogo": "agogo",
    "triangle": "triangle",
    "whistle": "whistle",
    "block": "block",
    "synth": "synth",
    "organ": "organ",
    "bell": "bell",
    "guitar": "guitar",
    "noise": "noise",
    "snap": "snap",
    "perc": "percussion",
}


def tags_for_filename(path: Path) -> set[str]:
    """Canonical instrument-convention tags implied by a sample's filename
    and immediate parent folder name, per the naming-convention catalogue
    in 01-auto-tagging.md. Deliberately just the immediate parent, not
    every ancestor folder - a pack-name folder further up doesn't carry
    instrument signal, only the folder right around the file tends to
    (e.g. "07. Cabasa & Shaker/"). Pack/vendor-style tags from folders
    further up are tags_for_path's job, below.

    Only whole alphabetic tokens are matched against the vocabulary, so
    velocity/round-robin numbers and note names (e.g. "G#", "D#0") never
    get mistaken for a tag, and "Chick" in a folder name like "Chick N
    Swell" doesn't false-match "CH" as a substring.
    """
    tokens = _TOKEN_RE.findall(path.stem) + _TOKEN_RE.findall(path.parent.name)
    return {_VOCABULARY[token.lower()] for token in tokens if token.lower() in _VOCABULARY}


# Folder-name tokens that almost never carry pack/vendor identity - file
# formats, bit depths, and common DAW/plugin export folders. Short and
# non-exhaustive on purpose (13-folder-name-tagging.md): the point isn't to
# catch every uninteresting folder, it's to catch the obvious ones cheaply -
# anything this misses just becomes a slightly odd tag, which the
# tag-vocabulary review (12-ai-tag-review.md) is the actual backstop for,
# not this list.
_GENERIC_FOLDER_WORDS = {
    "samples", "sample", "sounds", "sound", "audio", "library",
    "wav", "wavs", "aiff", "aif", "mp3", "flac", "ogg", "rex", "rx2",
    "loops", "loop", "shots", "shot", "presets", "preset",
    "patches", "patch", "misc", "documentation", "docs", "readme",
    "artwork", "license", "licence",
    # Umbrella instrument-category words, too generic to single out any
    # one pack even though they're not ambiguous the way bare "bass" is -
    # every pack has drums/percussion in it somewhere.
    "drum", "drums", "percussion", "percussions", "instrument", "instruments",
    "kontakt", "battery", "ableton", "logic", "maschine", "reason",
    "cubase", "reaktor", "halion", "serum", "massive", "omnisphere",
    "exs24", "nnxt", "soundfont", "sfz",
}

# How many folder levels above a sample (counted from the configured root
# downwards, not from the file upwards) are worth turning into pack/vendor
# tags. Kept small on purpose - deeper folders tend to be file-type or
# DAW-export folders rather than pack identity, and a low cap means one
# oddly-named pack pollutes the tag list a little rather than a lot.
MAX_FOLDER_TAGS = 2


def _folder_tag_slug(name: str) -> str | None:
    """`name` as a tag, or None if every token in it looks generic (see
    _GENERIC_FOLDER_WORDS) or is already covered by the instrument
    vocabulary (including a naive plural, "kicks" for "kick") - either way
    it's not telling us anything a pack/vendor tag should."""
    tokens = [token.lower() for token in _TOKEN_RE.findall(name)]
    if not tokens:
        return None  # nothing alphabetic - e.g. "24bit", "[2020]"
    if all(
        token in _GENERIC_FOLDER_WORDS
        or token in _VOCABULARY
        or token.rstrip("s") in _VOCABULARY
        for token in tokens
    ):
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or None


def _folder_tags(path: Path, root: Path) -> set[str]:
    try:
        relative_parts = path.parent.relative_to(root).parts
    except ValueError:
        return set()  # path isn't actually under root - nothing to walk

    candidates = []
    for part in relative_parts:
        slug = _folder_tag_slug(part)
        if slug is not None:
            candidates.append(slug)
        if len(candidates) >= MAX_FOLDER_TAGS:
            break
    return set(candidates)


def tags_for_path(path: Path, root: Path | None = None) -> set[str]:
    """tags_for_filename's instrument-convention tags, plus - when `root`
    is given - pack/vendor-style tags from the folder names between the
    sample and `root`, favouring whichever are closest to `root` (see
    MAX_FOLDER_TAGS). `root` should be whichever configured samples
    directory (or "."-focused subfolder) the sample is actually being
    browsed under - see FileBrowser._root_for - not an arbitrary ancestor,
    since "how deep is this" only means something relative to a boundary
    the user recognises as the top of a pack's own folder tree.
    """
    tags = tags_for_filename(path)
    if root is not None:
        tags |= _folder_tags(path, root)
    return tags


def tag_file(path: Path, db_path: Path = DEFAULT_DB_PATH, root: Path | None = None) -> set[str]:
    """Auto-tags a single sample from its filename/folder name (and, with
    `root` given, its pack/vendor folder tags too), returning whatever
    tags were derived for it - whether or not each one actually changed
    anything in the store (see tag_store.auto_assign_tag)."""
    tags = tags_for_path(path, root)
    for tag in tags:
        tag_store.auto_assign_tag(path, tag, db_path)
    return tags


def tag_folder(
    path: Path,
    db_path: Path = DEFAULT_DB_PATH,
    on_file_tagged: Callable[[Path, set[str], int, int], None] | None = None,
    root: Path | None = None,
) -> int:
    """Recursively auto-tags every .wav under `path` - folders themselves
    are never tagged (01-auto-tagging.md). Returns the count of files
    processed; `on_file_tagged(file_path, tags, index, total)` fires after
    each one (1-based index, out of total), for a progress indicator.
    `root` is forwarded to tags_for_path for each file - see its
    docstring for what it anchors.

    Shares one connection across the whole run, committing every
    COMMIT_BATCH_SIZE files rather than once per (sample, tag) pair (see
    tag_store.auto_assign_tag_batch) - the difference between tagging a
    large library taking seconds versus minutes. A crash mid-run loses at
    most the current uncommitted batch, which is fine: auto-tagging is
    idempotent, so running it again just picks up where it left off.
    """
    wav_paths = sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".wav")
    total = len(wav_paths)

    with contextlib.closing(tag_store.connect(db_path)) as connection:
        for index, file_path in enumerate(wav_paths, start=1):
            tags = tags_for_path(file_path, root)
            for tag in tags:
                tag_store.auto_assign_tag_batch(connection, file_path, tag)
            if index % COMMIT_BATCH_SIZE == 0:
                connection.commit()
            if on_file_tagged is not None:
                on_file_tagged(file_path, tags, index, total)
        connection.commit()

    return total
