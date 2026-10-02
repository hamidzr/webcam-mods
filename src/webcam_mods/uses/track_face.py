"""Compatibility entrypoint for the supported track-face command."""

import sys
from collections.abc import Sequence


def main(args: Sequence[str] | None = None) -> None:
    from webcam_mods.entry import app

    app(
        args=["track-face", *(sys.argv[1:] if args is None else args)],
        prog_name="python -m webcam_mods.uses.track_face",
    )


if __name__ == "__main__":
    main()
