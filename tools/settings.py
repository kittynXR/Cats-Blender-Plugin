# GPL License

import bpy
import json
import copy
import time
import collections
from datetime import datetime, timezone
from collections import OrderedDict
from contextlib import contextmanager

from .. import globs
from ..tools.register import register_wrap
from ..extern_tools.google_trans_new.google_trans_new import google_translator
from . import translate as Translate
from . import paths as Paths
from .translations import t

settings_file = str(Paths.SETTINGS_FILE)

settings_data = None
settings_data_unchanged = None
_settings_timer_started_at = None
_SETTINGS_TIMER_TIMEOUT = 5.0

# Settings name = [Default Value, Require Blender Restart]
settings_default = OrderedDict()
settings_default['embed_textures'] = [False, False]
settings_default['ui_lang'] = ["auto", False]

lock_settings = False

@contextmanager
def settings_lock_context():
    global lock_settings
    lock_settings = True
    try:
        yield
    finally:
        lock_settings = False

@register_wrap
class RevertChangesButton(bpy.types.Operator):
    bl_idname = 'cats_settings.revert'
    bl_label = t('RevertChangesButton.label')
    bl_description = t('RevertChangesButton.desc')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        for setting in settings_default.keys():
            setattr(bpy.context.scene, setting, settings_data_unchanged.get(setting))
        save_settings()
        self.report({'INFO'}, t('RevertChangesButton.success'))
        return {'FINISHED'}

@register_wrap
class ResetGoogleDictButton(bpy.types.Operator):
    bl_idname = 'cats_settings.reset_google_dict'
    bl_label = t('ResetGoogleDictButton.label')
    bl_description = t('ResetGoogleDictButton.desc')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        Translate.reset_google_dict()
        Translate.load_translations()
        self.report({'INFO'}, t('ResetGoogleDictButton.resetInfo'))
        return {'FINISHED'}

@register_wrap
class DebugTranslations(bpy.types.Operator):
    bl_idname = 'cats_settings.debug_translations'
    bl_label = t('DebugTranslations.label')
    bl_description = t('DebugTranslations.desc')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if not getattr(bpy.app, "online_access", True):
            self.report({'ERROR'}, "Online access is disabled in Blender preferences")
            return {'CANCELLED'}

        bpy.context.scene.debug_translations = True
        translator = google_translator()
        try:
            translator.translate('猫')
        except:
            self.report({'INFO'}, t('DebugTranslations.error'))

        bpy.context.scene.debug_translations = False
        self.report({'INFO'}, t('DebugTranslations.success'))
        return {'FINISHED'}

def load_settings():
    global settings_data, settings_data_unchanged

    Paths.migrate_legacy_file(
        Paths.BUNDLED_RESOURCES_DIR / "settings.json",
        Paths.SETTINGS_FILE,
    )

    try:
        with open(settings_file, encoding="utf8") as file:
            settings_data = json.load(file, object_pairs_hook=collections.OrderedDict)
    except FileNotFoundError:
        print("SETTINGS FILE NOT FOUND!")
        reset_settings(full_reset=True)
        return
    except json.decoder.JSONDecodeError:
        print("ERROR FOUND IN SETTINGS FILE")
        reset_settings(full_reset=True)
        return

    if not settings_data:
        print("NO DATA IN SETTINGS FILE")
        reset_settings(full_reset=True)
        return

    to_reset_settings = []

    for setting in ['last_supporter_update']:
        if setting not in settings_data and setting not in to_reset_settings:
            to_reset_settings.append(setting)
            print('RESET SETTING', setting)

    for setting in settings_default.keys():
        if setting not in settings_data and setting not in to_reset_settings:
            to_reset_settings.append(setting)
            print('RESET SETTING', setting)

    utc_now = datetime.strptime(datetime.now(timezone.utc).strftime(globs.time_format), globs.time_format)
    for setting in ['last_supporter_update']:
        if setting not in to_reset_settings and settings_data.get(setting):
            try:
                timestamp = datetime.strptime(settings_data.get(setting), globs.time_format)
            except ValueError:
                to_reset_settings.append(setting)
                print('RESET TIME', setting)
                continue

            time_delta = (utc_now - timestamp).total_seconds()
            if time_delta < 0:
                to_reset_settings.append(setting)
                print('TIME', setting, 'IN FUTURE!', time_delta)

    if to_reset_settings:
        reset_settings(to_reset_settings=to_reset_settings)
        return

    settings_data_unchanged = copy.deepcopy(settings_data)

def save_settings():
    Paths.atomic_write_json(settings_file, settings_data)

def reset_settings(full_reset=False, to_reset_settings=None):
    if not to_reset_settings:
        full_reset = True

    global settings_data, settings_data_unchanged

    if full_reset:
        settings_data = OrderedDict()
        settings_data['last_supporter_update'] = None

        for setting, value in settings_default.items():
            settings_data[setting] = value[0]

    else:
        for setting in to_reset_settings:
            if setting in settings_default.keys():
                settings_data[setting] = settings_default[setting][0]
            else:
                settings_data[setting] = None

    save_settings()

    settings_data_unchanged = copy.deepcopy(settings_data)
    print('SETTINGS RESET')

def start_apply_settings_timer():
    """Apply saved settings on Blender's main thread once registration settles."""
    global _settings_timer_started_at
    _settings_timer_started_at = time.monotonic()

    if bpy.app.timers.is_registered(apply_settings_with_timeout):
        bpy.app.timers.unregister(apply_settings_with_timeout)
    bpy.app.timers.register(apply_settings_with_timeout, first_interval=0.0)

def apply_settings_with_timeout():
    """Blender timer callback; return a delay to retry until a scene exists."""
    global _settings_timer_started_at

    if _settings_timer_started_at is None:
        return None
    if time.monotonic() - _settings_timer_started_at >= _SETTINGS_TIMER_TIMEOUT:
        release_lock()
        _settings_timer_started_at = None
        return None

    try:
        with settings_lock_context():
            if apply_settings():
                _settings_timer_started_at = None
                return None
    except (AttributeError, RuntimeError) as error:
        print(f"Waiting to apply CATS settings: {error}")

    return 0.3

def release_lock():
    global lock_settings
    print("Settings lock timed out, releasing lock")
    lock_settings = False

def apply_settings():
    """Try once to apply settings. Must be called from Blender's main thread."""
    scene = getattr(bpy.context, 'scene', None)
    if scene is None or settings_data is None:
        return False

    settings_to_reset = []
    for setting in settings_default.keys():
        try:
            setattr(scene, setting, settings_data.get(setting))
        except TypeError:
            settings_to_reset.append(setting)

    if settings_to_reset:
        reset_settings(to_reset_settings=settings_to_reset)
        print("RESET SETTINGS ON TIMER:", ", ".join(settings_to_reset))

    print('Settings applied successfully')
    return True

def stop_apply_settings_threads():
    """Cancel the settings timer (kept under its legacy public function name)."""
    global _settings_timer_started_at
    _settings_timer_started_at = None
    if bpy.app.timers.is_registered(apply_settings_with_timeout):
        bpy.app.timers.unregister(apply_settings_with_timeout)

def settings_changed():
    for setting, value in settings_default.items():
        if value[1] and settings_data.get(setting) != settings_data_unchanged.get(setting):
            return True
    return False

def update_settings(self, context):
    update_settings_core(self, context)

def update_settings_core(self, context):
    print("update_settings_core function called")
    settings_changed_tmp = False
    if lock_settings:
        print("Settings are locked, returning")
        return settings_changed_tmp

    with settings_lock_context():
        for setting in settings_default.keys():
            old = settings_data[setting]
            new = getattr(bpy.context.scene, setting)
            print(f"Checking setting: {setting}")
            print(f"Old value: {old}")
            print(f"New value: {new}")
            if old != new:
                print(f"Setting {setting} changed")
                settings_data[setting] = new
                settings_changed_tmp = True

        if settings_changed_tmp:
            print("Settings changed, saving settings")
            save_settings()
        else:
            print("No settings changed")

    return settings_changed_tmp

def get_embed_textures():
    return settings_data.get('embed_textures')

def get_ui_lang():
    return settings_data.get('ui_lang')

