import json
from pathlib import Path

_SRC_DIR = Path(__file__).parent

with open(
    _SRC_DIR / "config.json",
    "r",
    encoding="utf-8"
) as _file:

    _SETTINGS = json.load(_file)

_GLOBAL = _SETTINGS["global"]

# Anchored to src/ rather than the process cwd, so scripts behave the same
# no matter which directory they're launched from.
CONFIG_DIR = _SRC_DIR / _GLOBAL["config_dir"]

DATABASE_FILE = CONFIG_DIR / _GLOBAL["database_file"]

USER_AGENT = _GLOBAL["user_agent"]


def section(name):
    """Settings for one script/step of config.json, e.g. section("sources")["tfl"]."""
    return _SETTINGS[name]

