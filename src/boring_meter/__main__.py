import sys

if sys.version_info < (3, 9):
    sys.stderr.write(
        "Boring Meter error [UNSUPPORTED_PYTHON]: Python 3.9 or newer is required "
        "(found %d.%d).\nHint: install a newer Python 3 and make it the first python3 on PATH.\n"
        % sys.version_info[:2]
    )
    sys.exit(3)

from boring_meter.cli import main  # noqa: E402

sys.exit(main())
