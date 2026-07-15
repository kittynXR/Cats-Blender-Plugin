# SPDX-License-Identifier: GPL-3.0-or-later

"""Filesystem locations for bundled assets and mutable CATS state.

Blender extensions may be installed into a read-only directory.  Everything in
``resources`` is therefore treated as immutable; settings, downloaded
translations, updater state, and temporary downloads live in Blender's per-user
directories instead.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import bpy


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_RESOURCES_DIR = PACKAGE_ROOT / "resources"
BUNDLED_TRANSLATIONS_DIR = BUNDLED_RESOURCES_DIR / "translations"
BUNDLED_DICTIONARY_FILE = BUNDLED_RESOURCES_DIR / "dictionary.json"

USER_CONFIG_DIR = Path(
    bpy.utils.user_resource("CONFIG", path="cats_blender_plugin", create=True)
)
USER_DATA_DIR = Path(
    bpy.utils.user_resource("DATAFILES", path="cats_blender_plugin", create=True)
)

SETTINGS_FILE = USER_CONFIG_DIR / "settings.json"
GOOGLE_DICTIONARY_CACHE_FILE = USER_CONFIG_DIR / "dictionary_google.json"

USER_TRANSLATIONS_DIR = USER_DATA_DIR / "translations"
DOWNLOADED_DICTIONARY_FILE = USER_DATA_DIR / "dictionary.json"
TRANSLATION_EXPORT_DIR = USER_DATA_DIR / "translation_exports"

UPDATER_STATE_DIR = USER_CONFIG_DIR / "updater"
UPDATER_DOWNLOADS_DIR = UPDATER_STATE_DIR / "downloads"
UPDATER_IGNORE_VERSION_FILE = UPDATER_STATE_DIR / "ignore_version.txt"
UPDATER_DISABLE_AUTO_CHECK_FILE = UPDATER_STATE_DIR / "no_auto_ver_check.txt"


for _directory in (
    USER_CONFIG_DIR,
    USER_DATA_DIR,
    USER_TRANSLATIONS_DIR,
    TRANSLATION_EXPORT_DIR,
    UPDATER_STATE_DIR,
):
    _directory.mkdir(parents=True, exist_ok=True)


def migrate_legacy_file(source, destination):
    """Copy valid legacy state out of the package without modifying the package."""
    source = Path(source)
    destination = Path(destination)
    if destination.exists() or not source.is_file():
        return False

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, destination)
    except OSError as error:
        print(f"Could not migrate legacy CATS state {source}: {error}")
        return False
    return True


def atomic_write_json(path, value):
    """Write JSON atomically so an interrupted save cannot corrupt user state."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(value, temporary_file, ensure_ascii=False, indent=4)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
