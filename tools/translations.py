# GPL License

# Thanks to https://www.thegrove3d.com/learn/how-to-translate-a-blender-addon/ for the idea

import os
import re
import bpy
import json
import requests

from .register import register_wrap
from . import settings
from . import paths as Paths

settings_file = str(Paths.SETTINGS_FILE)
translations_dir = str(Paths.BUNDLED_TRANSLATIONS_DIR)

dictionary: dict[str, str] = dict()
languages = []
verbose = True
last_loaded_language = None
dictionary_download_link = (
    "https://raw.githubusercontent.com/teamneoneko/"
    "Cats-Blender-Plugin-Unofficial-translations/5x-translations/dictionary.json"
)
_addon_startup_time = None


def _available_translation_files():
    """Return bundled translations overlaid by validated user downloads."""
    translation_files = {}
    for directory in (Paths.BUNDLED_TRANSLATIONS_DIR, Paths.USER_TRANSLATIONS_DIR):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.json"):
            translation_files[path.stem] = path
    return translation_files


def _load_translation_messages(language):
    """Load bundled messages and overlay a validated user download."""
    candidates = (
        Paths.BUNDLED_TRANSLATIONS_DIR / f"{language}.json",
        Paths.USER_TRANSLATIONS_DIR / f"{language}.json",
    )
    combined_messages = {}
    loaded_file = None
    for translation_file in candidates:
        if not translation_file.is_file():
            continue
        try:
            with translation_file.open('r', encoding='utf8') as file:
                payload = json.load(file)
            messages = payload.get("messages")
            if not isinstance(messages, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in messages.items()
            ):
                raise ValueError("messages must contain string key/value pairs")
            combined_messages.update(messages)
            loaded_file = translation_file
        except (OSError, json.JSONDecodeError, ValueError) as error:
            print(f"Invalid translation file {translation_file}: {error}")
    if loaded_file is None:
        return None, None
    return combined_messages, loaded_file

def load_translations(override_language=None):
    global dictionary, languages, last_loaded_language, _addon_startup_time
    import time

    # Set startup time on first load
    if _addon_startup_time is None:
        _addon_startup_time = time.time()

    dictionary = dict()
    languages = ["auto"]

    print("Loading translations")

    if override_language:
        language = override_language
        print(f"Using override language: {language}")
    else:
        language = get_language_from_settings()
        print(f"Selected language: {language}")

    # Get all current languages. User downloads override, but never replace, the
    # immutable translations bundled with the extension.
    languages.extend(sorted(_available_translation_files()))
    print(f"Available languages: {languages}")

    # Determine the language to load
    language_to_load = language if language and language in languages else None

    # If language is not available, fallback to en_US
    if language_to_load is None:
        print(f"Language '{language}' not available, defaulting to en_US")
        language_to_load = "en_US"

    # Load the translation file
    messages, translation_file = _load_translation_messages(language_to_load)
    if messages is not None:
        print(f"Loading translation file: {translation_file}")
        dictionary = messages
        last_loaded_language = language_to_load
        print(f"Loaded {len(dictionary)} translations from {language_to_load}")
    else:
        print(f"Translation file not found for language: {language_to_load}")
        # Load the default "en_US" translation file as last resort
        messages, default_file = _load_translation_messages("en_US")
        if messages is not None:
            print(f"Loading fallback translation file: {default_file}")
            dictionary = messages
            last_loaded_language = "en_US"
            print(f"Loaded {len(dictionary)} translations from en_US (fallback)")
        else:
            print("DEFAULT TRANSLATION FILE 'en_US.json' NOT FOUND.")

    check_missing_translations()


def t(phrase: str, *args, **kwargs):
    # Translate the given phrase into Blender's current language.
    output = dictionary.get(phrase)
    if output is None:
        if verbose:
            print('Warning: Unknown phrase: ' + phrase)
        return phrase

    return output.format(*args, **kwargs)


def check_missing_translations():
    for key, value in dictionary.items():
        if not value and verbose:
            print('Translations en_US: Value missing for key: ' + key)


def get_languages_list(self, context):
    choices = []

    for language in languages:
        # 1. Will be returned by context.scene
        # 2. Will be shown in lists
        # 3. will be shown in the hover description (below description)
        choices.append((language, language, language))

    return choices


def update_ui(self, context):
    global _addon_startup_time
    import time

    print("update_ui function called")

    # Don't trigger reload during the first 2 seconds after addon load (initialization period or crashes may occur)
    if _addon_startup_time and (time.time() - _addon_startup_time) < 2.0:
        print("Skipping reload during initialization period")
        return

    # Get the NEW language value directly from the scene property (not from file)
    # because the update callback is triggered BEFORE the settings file is saved
    current_language = context.scene.ui_lang if context and hasattr(context, 'scene') else None

    # Handle "auto" mode - detect from Blender locale
    if current_language and "auto" in current_language.lower():
        from bpy.app.translations import locale
        current_language = convert_locale_to_language_code(locale)
        if not current_language:
            current_language = "en_US"

    print(f"Current language from scene: {current_language}, Last loaded: {last_loaded_language}")

    if current_language != last_loaded_language:
        print(f"Language changed from {last_loaded_language} to {current_language}, reloading translations")

        # Save the settings first so get_language_from_settings() will return the new value
        settings.update_settings_core(None, None)

        load_translations()

        # Automatically reload scripts after a delay to apply new translations (old method was unreliable)
        def delayed_reload():
            try:
                print("Auto-reloading scripts to apply new language...")
                bpy.ops.script.reload()
                print("Language changed successfully!")
            except Exception as e:
                print(f"Script reload failed: {e}")
            return None

        # Delay by 2 seconds to ensure all dialogs are closed and operations complete (Or we get crashes due to gotchaes situation)
        bpy.app.timers.register(delayed_reload, first_interval=2.0)
    else:
        print("Language unchanged, no reload needed")


def get_language_from_settings():
    Paths.migrate_legacy_file(
        Paths.BUNDLED_RESOURCES_DIR / "settings.json",
        Paths.SETTINGS_FILE,
    )

    # Load settings file
    try:
        with open(settings_file, encoding="utf8") as file:
            settings_data = json.load(file)
    except FileNotFoundError:
        print("SETTINGS FILE NOT FOUND!")
        return
    except json.decoder.JSONDecodeError:
        print("ERROR FOUND IN SETTINGS FILE")
        return

    if not settings_data:
        print("NO DATA IN SETTINGS FILE")
        return

    lang = settings_data.get("ui_lang")
    if not lang or "auto" in lang.lower():
        # Auto-detect language from Blender's locale
        from bpy.app.translations import locale as current_locale
        detected_lang = convert_locale_to_language_code(current_locale)
        print(f"Auto-detecting language from Blender locale: {current_locale} -> {detected_lang}")
        return detected_lang

    return lang


def convert_locale_to_language_code(blender_locale):
    """
    Convert Blender's locale format to supported language code format.
    Blender uses formats like 'en_US', 'ja_JP', 'ko_KR', etc.
    """
    if not blender_locale:
        return None

    # Blender locale is already in the format we need (e.g., 'en_US')
    locale_str = str(blender_locale)

    # Check if exact match exists in available languages
    for lang_code in _available_translation_files():
        if locale_str == lang_code:
            print(f"Found exact locale match: {lang_code}")
            return lang_code

    # Try to match by language code (first part before underscore)
    language_only = locale_str.split("_")[0].lower() if "_" in locale_str else locale_str.lower()
    for lang_code in _available_translation_files():
        if lang_code.lower().startswith(language_only):
            print(f"Found language match: {lang_code}")
            return lang_code

    # Fallback to English if no match
    print(f"No language match found for locale: {locale_str}, defaulting to en_US")
    return None

@register_wrap
class DownloadTranslations(bpy.types.Operator):
    bl_idname = 'cats_translations.download_latest'
    bl_label = 'Download Latest Translations'
    bl_description = 'Download the latest translations for cats UI and internal dictionary'   
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if not getattr(bpy.app, "online_access", True):
            self.report({'ERROR'}, "Online access is disabled in Blender preferences")
            return {'CANCELLED'}

        # GitHub repository and folder information
        repo_owner = "teamneoneko"
        repo_name = "Cats-Blender-Plugin-Unofficial-translations"
        branch = "5x-translations"
        folder_path = "UI%20Tanslations"

        # Construct the API URL to get the list of files in the folder
        api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{folder_path}?ref={branch}"

        request_options = {
            "headers": {"User-Agent": "Cats-Blender-Plugin-Translations"},
            "timeout": 20,
        }
        try:
            # Send a GET request to the API URL
            response = requests.get(api_url, **request_options)
            response.raise_for_status()  # Raise an exception if the request was unsuccessful

            # Parse the JSON response
            files = response.json()
            if not isinstance(files, list):
                raise ValueError("GitHub returned an unexpected folder response")

            # Download each translation file
            translation_payloads = []
            for file_info in files:
                file_name = file_info.get("name", "")
                safe_name = os.path.basename(file_name)
                if (
                    file_info.get("type") == "file"
                    and file_name == safe_name
                    and re.fullmatch(r"[A-Za-z0-9_.-]+\.json", safe_name)
                ):
                    file_url = file_info.get("download_url")
                    if not file_url:
                        raise ValueError(f"Missing download URL for {safe_name}")

                    # Download the translation file
                    file_response = requests.get(file_url, **request_options)
                    file_response.raise_for_status()
                    payload = file_response.json()
                    messages = payload.get("messages") if isinstance(payload, dict) else None
                    if not isinstance(messages, dict) or not all(
                        isinstance(key, str) and isinstance(value, str)
                        for key, value in messages.items()
                    ):
                        raise ValueError(f"Invalid translation JSON in {safe_name}")
                    translation_payloads.append((safe_name, payload))

            if not translation_payloads:
                raise ValueError("No translation JSON files were found")

            for file_name, payload in translation_payloads:
                file_path = Paths.USER_TRANSLATIONS_DIR / file_name
                Paths.atomic_write_json(file_path, payload)
                print(f"Downloaded: {file_name}")

        except (requests.exceptions.RequestException, OSError, ValueError, TypeError) as e:
            print("TRANSLATIONS FILES COULD NOT BE DOWNLOADED")
            self.report({'ERROR'}, "TRANSLATIONS FILES COULD NOT BE DOWNLOADED: " + str(e))
            return {'CANCELLED'}

        print('TRANSLATIONS DOWNLOAD FINISHED')

        # Download dictionary.json from GitHub
        print('DOWNLOAD DICTIONARY FILE')
        try:
            response = requests.get(dictionary_download_link, **request_options)
            response.raise_for_status()  # Raise an exception if the request was unsuccessful
            dictionary_payload = response.json()
            if not isinstance(dictionary_payload, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in dictionary_payload.items()
            ):
                raise ValueError("Invalid dictionary JSON")
            Paths.atomic_write_json(Paths.DOWNLOADED_DICTIONARY_FILE, dictionary_payload)
        except (requests.exceptions.RequestException, OSError, ValueError, TypeError) as e:
            print("DICTIONARY FILE COULD NOT BE DOWNLOADED")
            self.report({'ERROR'}, "DICTIONARY FILE COULD NOT BE DOWNLOADED: " + str(e))
            return {'CANCELLED'}
        print('DICTIONARY DOWNLOAD FINISHED')

        bpy.ops.script.reload()

        self.report({'INFO'}, "Successfully downloaded the translations and dictionary")
        return {'FINISHED'}




load_translations()
