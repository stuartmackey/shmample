import argparse
from pathlib import Path

from shmample import migrations
from shmample.app import ShmampleApp
from shmample.settings import load_settings, save_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="shmample")
    parser.add_argument(
        "--samples-dir",
        type=Path,
        help="A directory to add to the file browser's sample paths. Persisted for future "
        "runs, on top of whatever's already configured (see Shift+A in the samples pane).",
    )
    args = parser.parse_args()

    migrations.run_migrations()

    settings = load_settings()
    if args.samples_dir is not None:
        directory = args.samples_dir.expanduser().resolve()
        if directory not in settings.samples_directories:
            settings.samples_directories.append(directory)
            save_settings(settings)

    ShmampleApp(
        samples_directories=settings.samples_directories,
        directory_aliases=settings.directory_aliases,
    ).run()


if __name__ == "__main__":
    main()
