"""Entry point used by bin/boring-meter (sh) and bin/boring-meter.cmd (Windows).

Finds src/ from this file's own location, so no PYTHONPATH handling is needed on
any platform. `--run-hook instructions-loaded` runs the InstructionsLoaded hook.
"""

import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    if sys.argv[1:2] == ["--run-hook"]:
        if sys.argv[2:3] == ["instructions-loaded"]:
            sys.argv = [sys.argv[0]]
            runpy.run_path(os.path.join(ROOT, "scripts", "hook_instructions_loaded.py"), run_name="__main__")
        return 0  # unknown hooks are ignored so a hook can never block Claude Code
    sys.path.insert(0, os.path.join(ROOT, "src"))
    runpy.run_module("boring_meter", run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
