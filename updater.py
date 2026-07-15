# MIT License

import os
import bpy
import json
import stat
import urllib.error
import urllib.request
import shutil
import zipfile
from threading import Thread
from queue import Empty, Queue
from collections import OrderedDict
from bpy.app.handlers import persistent
from .tools.translations import t
from .tools.common import wrap_dynamic_enum_items
from .tools import paths as Paths
from . import CATS_VERSION, dev_branch

no_ver_check = False
fake_update = False

is_checking_for_update = False
checked_on_startup = False
version_list = None
current_version = []
current_version_str = ''
update_needed = False
latest_version = None
latest_version_str = ''
used_updater_panel = False
update_finished = False
remind_me_later = False
is_ignored_version = False

confirm_update_to = ''

show_error = ''

main_dir = os.path.dirname(__file__)
downloads_dir = str(Paths.UPDATER_DOWNLOADS_DIR)
resources_dir = os.path.join(main_dir, "resources")
ignore_ver_file = str(Paths.UPDATER_IGNORE_VERSION_FILE)
no_auto_ver_check_file = str(Paths.UPDATER_DISABLE_AUTO_CHECK_FILE)
Paths.migrate_legacy_file(
    os.path.join(resources_dir, "ignore_version.txt"),
    Paths.UPDATER_IGNORE_VERSION_FILE,
)
Paths.migrate_legacy_file(
    os.path.join(resources_dir, "no_auto_ver_check.txt"),
    Paths.UPDATER_DISABLE_AUTO_CHECK_FILE,
)

# Get package name, important for panel in user preferences
package_name = __package__

_update_result_queue = Queue()


def online_access_allowed():
    """Honor Blender's per-user online access preference."""
    return bool(getattr(bpy.app, "online_access", True))


# Icons for UI
ICON_URL = 'URL'

class CheckForUpdateButton(bpy.types.Operator):
    bl_idname = 'cats_updater.check_for_update'
    bl_label = t('CheckForUpdateButton.label')
    bl_description = t('CheckForUpdateButton.desc')
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return not is_checking_for_update and online_access_allowed()

    def execute(self, context):
        global used_updater_panel
        used_updater_panel = True
        check_for_update_background()
        return {'FINISHED'}


class UpdateToLatestButton(bpy.types.Operator):
    bl_idname = 'cats_updater.update_latest'
    bl_label = t('UpdateToLatestButton.label')
    bl_description = t('UpdateToLatestButton.desc')
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return update_needed and online_access_allowed()

    def execute(self, context):
        global confirm_update_to, used_updater_panel
        confirm_update_to = 'latest'
        used_updater_panel = True

        bpy.ops.cats_updater.confirm_update_panel('INVOKE_DEFAULT')
        return {'FINISHED'}


class UpdateToSelectedButton(bpy.types.Operator):
    bl_idname = 'cats_updater.update_selected'
    bl_label = t('UpdateToSelectedButton.label')
    bl_description = t('UpdateToSelectedButton.desc')
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if is_checking_for_update or not version_list or not online_access_allowed():
            return False
        return True

    def execute(self, context):
        global confirm_update_to, used_updater_panel
        confirm_update_to = context.scene.cats_updater_version_list
        used_updater_panel = True

        bpy.ops.cats_updater.confirm_update_panel('INVOKE_DEFAULT')
        return {'FINISHED'}


class UpdateToDevButton(bpy.types.Operator):
    bl_idname = 'cats_updater.update_dev'
    bl_label = t('UpdateToDevButton.label')
    bl_description = t('UpdateToDevButton.desc')
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return online_access_allowed()

    def execute(self, context):
        global confirm_update_to, used_updater_panel
        confirm_update_to = 'dev'
        used_updater_panel = True

        bpy.ops.cats_updater.confirm_update_panel('INVOKE_DEFAULT')
        return {'FINISHED'}


class RemindMeLaterButton(bpy.types.Operator):
    bl_idname = 'cats_updater.remind_me_later'
    bl_label = t('RemindMeLaterButton.label')
    bl_description = t('RemindMeLaterButton.desc')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        global remind_me_later
        remind_me_later = True
        self.report({'INFO'}, t('RemindMeLaterButton.success'))
        return {'FINISHED'}


class IgnoreThisVersionButton(bpy.types.Operator):
    bl_idname = 'cats_updater.ignore_this_version'
    bl_label = t('IgnoreThisVersionButton.label')
    bl_description = t('IgnoreThisVersionButton.desc')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        set_ignored_version()
        self.report({'INFO'}, t('IgnoreThisVersionButton.success', name=latest_version_str))
        return {'FINISHED'}


class ShowPatchnotesPanel(bpy.types.Operator):
    bl_idname = 'cats_updater.show_patchnotes'
    bl_label = t('ShowPatchnotesPanel.label')
    bl_description = t('ShowPatchnotesPanel.desc')
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if is_checking_for_update or not version_list:
            return False
        return True

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        global used_updater_panel
        used_updater_panel = True
        dpi_value = context.preferences.system.dpi
        return context.window_manager.invoke_props_dialog(self, width=int(dpi_value * 8.2))

    def check(self, context):
        # Important for changing options
        return True

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        row = col.row(align=True)
        row.prop(context.scene, 'cats_updater_version_list')

        if context.scene.cats_updater_version_list:
            version = version_list.get(context.scene.cats_updater_version_list)

            col.separator()
            row = col.row(align=True)
            row.label(text=t('ShowPatchnotesPanel.releaseDate', date=version[2]))

            col.separator()
            for line in version[1].replace('**', '').split('\r\n'):
                row = col.row(align=True)
                row.scale_y = 0.75
                row.label(text=line)

        col.separator()


class ConfirmUpdatePanel(bpy.types.Operator):
    bl_idname = 'cats_updater.confirm_update_panel'
    bl_label = t('ConfirmUpdatePanel.label')
    bl_description = t('ConfirmUpdatePanel.desc')
    bl_options = {'INTERNAL'}

    show_patchnotes = False

    def execute(self, context):
        print('UPDATE TO ' + confirm_update_to)
        if confirm_update_to == 'dev':
            update_now(dev=True)
        elif confirm_update_to == 'latest':
            update_now(latest=True)
        else:
            update_now(version=confirm_update_to)
        return {'FINISHED'}

    def invoke(self, context, event):
        dpi_value = context.preferences.system.dpi
        return context.window_manager.invoke_props_dialog(self, width=int(dpi_value * 4.1))

    def check(self, context):
        # Important for changing options
        return True

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        version_str = confirm_update_to
        if confirm_update_to == 'latest':
            version_str = latest_version_str
        elif confirm_update_to == 'dev':
            version_str = 'Dev'

        col.separator()
        row = col.row(align=True)
        row.label(text='Version: ' + version_str)

        if confirm_update_to == 'dev':
            col.separator()
            col.separator()
            row = col.row(align=True)
            row.scale_y = 0.75
            row.label(text=t('ConfirmUpdatePanel.warn.dev1'))
            row = col.row(align=True)
            row.scale_y = 0.75
            row.label(text=t('ConfirmUpdatePanel.warn.dev2'))
            row = col.row(align=True)
            row.scale_y = 0.75
            row.label(text=t('ConfirmUpdatePanel.warn.dev3'))
            row = col.row(align=True)
            row.scale_y = 0.75
            row.label(text=t('ConfirmUpdatePanel.warn.dev4'))
            row = col.row(align=True)
            row.scale_y = 0.75
            row.label(text=t('ConfirmUpdatePanel.warn.dev5'))

        else:
            row.operator(ShowPatchnotesPanel.bl_idname, text=t('ConfirmUpdatePanel.ShowPatchnotesPanel.label'))

        col.separator()
        col.separator()
        # col.separator()
        row = col.row(align=True)
        row.scale_y = 0.65
        # row.label(text='Update now to ' + version_str + ':', icon=ICON_URL)
        row.label(text=t('ConfirmUpdatePanel.updateNow'), icon=ICON_URL)


class UpdateCompletePanel(bpy.types.Operator):
    bl_idname = 'cats_updater.update_complete_panel'
    bl_label = t('UpdateCompletePanel.label')
    bl_description = t('UpdateCompletePanel.desc')
    bl_options = {'INTERNAL'}

    show_patchnotes = False

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        dpi_value = context.preferences.system.dpi
        return context.window_manager.invoke_props_dialog(self, width=int(dpi_value * 4.1))

    def check(self, context):
        # Important for changing options
        return True

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        if update_finished:
            row = col.row(align=True)
            row.scale_y = 0.9
            row.label(text=t('UpdateCompletePanel.success1'), icon='FILE_TICK')

            row = col.row(align=True)
            row.scale_y = 0.9
            row.label(text=t('UpdateCompletePanel.success2'), icon='BLANK1')
        else:
            row = col.row(align=True)
            row.scale_y = 0.9
            row.label(text=t('UpdateCompletePanel.failure1'), icon='CANCEL')

            row = col.row(align=True)
            row.scale_y = 0.9
            row.label(text=t('UpdateCompletePanel.failure2'), icon='BLANK1')


class UpdateNotificationPopup(bpy.types.Operator):
    bl_idname = 'cats_updater.update_notification_popup'
    bl_label = t('UpdateNotificationPopup.label')
    bl_description = t('UpdateNotificationPopup.desc')
    bl_options = {'INTERNAL'}

    def execute(self, context):
        action = context.scene.cats_update_action
        if action == 'UPDATE':
            update_now(latest=True)
        elif action == 'IGNORE':
            set_ignored_version()
        else:
            # Remind later aka defer
            global remind_me_later
            remind_me_later = True
        ui_refresh()
        return {'FINISHED'}

    def invoke(self, context, event):
        dpi_value = context.preferences.system.dpi
        return context.window_manager.invoke_props_dialog(self, width=int(dpi_value * 4.6))

    # def invoke(self, context, event):
    #     return context.window_manager.invoke_props_dialog(self)

    def check(self, context):
        # Important for changing options
        return True

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        row = layout_split(col, factor=0.55, align=True)
        row.scale_y = 1.05
        row.label(text=t('UpdateNotificationPopup.newUpdate', name=latest_version_str), icon='SOLO_ON')
        row.operator(ShowPatchnotesPanel.bl_idname, text=t('UpdateNotificationPopup.ShowPatchnotesPanel.label'))

        col.separator()
        col.separator()
        col.separator()
        row = col.row(align=True)
        row.prop(context.scene, 'cats_update_action', expand=True)


def check_for_update_background(check_on_startup=False):
    global is_checking_for_update, checked_on_startup
    if check_on_startup and checked_on_startup:
        # print('ALREADY CHECKED ON STARTUP')
        return
    if is_checking_for_update:
        # print('ALREADY CHECKING')
        return

    checked_on_startup = True

    if check_on_startup and os.path.isfile(no_auto_ver_check_file):
        print('AUTO CHECK DISABLED VIA FILE')
        return

    if not online_access_allowed():
        checked_on_startup = True
        finish_update_checking(error="Online access is disabled in Blender preferences")
        return

    is_checking_for_update = True
    while True:
        try:
            _update_result_queue.get_nowait()
        except Empty:
            break

    if not bpy.app.timers.is_registered(_poll_update_result):
        bpy.app.timers.register(_poll_update_result, first_interval=0.1)

    thread = Thread(
        target=_fetch_update_worker,
        args=(_release_series(),),
        daemon=True,
    )
    thread.start()


def check_for_update():
    """Synchronous update check retained for callers and test harnesses."""
    print('Checking for Cats update...')

    if not online_access_allowed():
        finish_update_checking(error="Online access is disabled in Blender preferences")
        return

    if not get_github_releases('kittynXR'):
        finish_update_checking(error=t('check_for_update.cantCheck'))
        return

    _complete_update_check()


def _complete_update_check():
    """Apply fetched results and touch Blender state only on the main thread."""
    global update_needed, is_ignored_version

    # Check if an update is needed
    update_needed = check_for_update_available()
    is_ignored_version = check_ignored_version()

    # Update needed, show the notification popup if it wasn't checked through the UI
    if update_needed:
        print('Update found!')
        if not used_updater_panel and not is_ignored_version:
            prepare_to_show_update_notification()
    else:
        print('No update found.')

    # Finish update checking, update the UI
    finish_update_checking()


def _release_series(blender_version=None):
    blender_version = blender_version or bpy.app.version
    return f"{blender_version[0]}.{blender_version[1]}."


def _normalize_release_tag(tag):
    """Return a stable dotted numeric tag, accepting v/hyphen variants."""
    if not isinstance(tag, str):
        return None
    normalized = tag.strip().replace('-', '.')
    if normalized.lower().startswith('v.'):
        normalized = normalized[2:]
    elif normalized.lower().startswith('v'):
        normalized = normalized[1:]
    parts = normalized.split('.')
    if len(parts) < 3 or any(not part.isdigit() for part in parts):
        return None
    return '.'.join(str(int(part)) for part in parts)


def _version_tuple(version):
    normalized = _normalize_release_tag(version)
    if normalized is None:
        return tuple()
    return tuple(int(part) for part in normalized.split('.'))


def _download_github_releases():
    req = urllib.request.Request(
        'https://api.github.com/repos/kittynXR/Cats-Blender-Plugin/releases',
        headers={'User-Agent': 'Cats-Blender-Plugin-Updater'},
    )
    with urllib.request.urlopen(req, timeout=20) as url:
        data = json.loads(url.read().decode('utf8'))
    if not isinstance(data, list):
        raise ValueError("GitHub returned an unexpected release response")
    return data


def _build_version_list(data, series):
    releases = []
    for release in data:
        if (not isinstance(release, dict)
                or release.get('draft')
                or release.get('prerelease')):
            continue
        normalized_tag = _normalize_release_tag(release.get('tag_name'))
        if not normalized_tag or not normalized_tag.startswith(series):
            continue
        zipball_url = release.get('zipball_url')
        if not isinstance(zipball_url, str) or not zipball_url:
            continue
        published_at = release.get('published_at') or ''
        if not isinstance(published_at, str):
            published_at = ''
        body = release.get('body') or ''
        if not isinstance(body, str):
            body = ''
        releases.append((
            _version_tuple(normalized_tag),
            normalized_tag,
            [
                zipball_url,
                body,
                published_at.split('T')[0],
            ],
        ))

    releases.sort(key=lambda item: item[0], reverse=True)
    return OrderedDict((tag, metadata) for _, tag, metadata in releases)


def _fetch_update_worker(series):
    """Network-only worker. Blender API changes are deferred to the timer."""
    try:
        data = _download_github_releases()
        result = _build_version_list(data, series)
        _update_result_queue.put((result, None))
    except Exception as error:
        _update_result_queue.put((None, str(error)))


def _poll_update_result():
    global version_list
    try:
        result, error = _update_result_queue.get_nowait()
    except Empty:
        return 0.1 if is_checking_for_update else None

    if error is not None:
        version_list = OrderedDict()
        print(f'Could not check for Cats update: {error}')
        finish_update_checking(error=t('check_for_update.cantCheck'))
        return None

    version_list = result
    _complete_update_check()
    return None


def get_github_releases(repo):
    """Fetch releases synchronously and keep only the active Blender series."""
    global version_list
    if fake_update:
        print('FAKE INSTALL!')
        series = _release_series()
        version_list = OrderedDict((
            (series + '99.99', ['', 'Put exciting new stuff here', 'Today']),
            (series + '98.0', ['', 'Nothing new to see', 'A week ago probably']),
        ))
        return True

    try:
        data = _download_github_releases()
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as error:
        print(f'URL ERROR: {error}')
        version_list = OrderedDict()
        return False
    version_list = _build_version_list(data, _release_series())
    return True


def check_for_update_available():
    global latest_version, latest_version_str
    latest_version = []
    latest_version_str = ''

    if not version_list:
        return False

    latest_version_str = next(iter(version_list))
    latest_version = list(_version_tuple(latest_version_str))

    # print(latest_version, '>', current_version)
    return tuple(latest_version) > tuple(current_version)


def finish_update_checking(error=''):
    global is_checking_for_update, show_error
    is_checking_for_update = False

    # Only show error if the update panel was used before
    if used_updater_panel:
        show_error = error

    ui_refresh()


def ui_refresh():
    # A way to refresh the ui
    if not hasattr(bpy.data, 'window_managers'):
        return
    for windowManager in bpy.data.window_managers:
        for window in windowManager.windows:
            for area in window.screen.areas:
                area.tag_redraw()


def get_update_post():
    if hasattr(bpy.app.handlers, 'scene_update_post'):
        return bpy.app.handlers.scene_update_post
    else:
        return bpy.app.handlers.depsgraph_update_post


def prepare_to_show_update_notification():
    # This is necessary to show a popup directly after startup
    # You will get a nasty error otherwise
    # This will add the function to the scene_update_post and it will be executed every frame. that's why it needs to be removed again asap
    # print('PREPARE TO SHOW UI')
    if show_update_notification not in get_update_post():
        get_update_post().append(show_update_notification)


@persistent
def show_update_notification(*_args):
    # print('SHOWING UI NOW!!!!')

    # # Immediately remove this from handlers again
    if show_update_notification in get_update_post():
        get_update_post().remove(show_update_notification)

    # Show notification popup
    atr = UpdateNotificationPopup.bl_idname.split(".")
    getattr(getattr(bpy.ops, atr[0]), atr[1])('INVOKE_DEFAULT')


def update_now(version=None, latest=False, dev=False):
    if not online_access_allowed():
        finish_update(error="Online access is disabled in Blender preferences")
        return
    if fake_update:
        finish_update()
        return
    if dev:
        print('UPDATE TO DEVELOPMENT')
        major, minor = bpy.app.version[:2]
        branch = f'blender-{major}{minor}-dev'
        update_link = (
            'https://github.com/kittynXR/Cats-Blender-Plugin/'
            f'archive/refs/heads/{branch}.zip'
        )
    elif latest or not version:
        print('UPDATE TO ' + latest_version_str)
        update_link = version_list.get(latest_version_str)[0]
        bpy.context.scene.cats_updater_version_list = latest_version_str
    else:
        print('UPDATE TO ' + version)
        update_link = version_list[version][0]

    download_file(update_link)


def _safe_extract(zip_ref, destination):
    """Extract an update archive only when every member stays in destination."""
    destination = os.path.realpath(destination)
    for member in zip_ref.infolist():
        file_type = (member.external_attr >> 16) & 0o170000
        if file_type == stat.S_IFLNK:
            raise ValueError(f"Symbolic link in update archive: {member.filename}")
        target = os.path.realpath(os.path.join(destination, member.filename))
        try:
            inside_destination = os.path.commonpath((destination, target)) == destination
        except ValueError:
            inside_destination = False
        if not inside_destination:
            raise ValueError(f"Unsafe path in update archive: {member.filename}")
    zip_ref.extractall(destination)


def download_file(update_url):
    # Load all the directories and files
    update_zip_file = os.path.join(downloads_dir, "cats-update.zip")

    # Remove existing download folder
    if os.path.isdir(downloads_dir):
        print("DOWNLOAD FOLDER EXISTED")
        shutil.rmtree(downloads_dir, ignore_errors=True)

    # Create download folder
    os.makedirs(downloads_dir, exist_ok=True)

    # Download zip
    print('DOWNLOAD FILE')
    try:
        request = urllib.request.Request(
            update_url,
            headers={'User-Agent': 'Cats-Blender-Plugin-Updater'},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            with open(update_zip_file, 'wb') as output_file:
                shutil.copyfileobj(response, output_file)
    except (OSError, urllib.error.URLError):
        print("FILE COULD NOT BE DOWNLOADED")
        shutil.rmtree(downloads_dir, ignore_errors=True)
        finish_update(error=t('download_file.cantConnect'))
        return
    print('DOWNLOAD FINISHED')

    # If zip is not downloaded, abort
    if not os.path.isfile(update_zip_file):
        print("ZIP NOT FOUND!")
        shutil.rmtree(downloads_dir, ignore_errors=True)
        finish_update(error=t('download_file.cantFindZip'))
        return

    # Extract the downloaded zip
    print('EXTRACTING ZIP')
    try:
        with zipfile.ZipFile(update_zip_file, "r") as zip_ref:
            _safe_extract(zip_ref, downloads_dir)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"UPDATE ARCHIVE COULD NOT BE EXTRACTED: {error}")
        shutil.rmtree(downloads_dir, ignore_errors=True)
        finish_update(error=t('download_file.cantFindZip'))
        return
    print('EXTRACTED')

    # Delete the extracted zip file
    print('REMOVING ZIP FILE')
    os.remove(update_zip_file)

    # Detect the extracted folders and files
    print('SEARCHING FOR INIT 1')

    def searchInit(path):
        print('SEARCHING IN ' + path)
        files = os.listdir(path)
        if "__init__.py" in files:
            print('FOUND')
            return path
        folders = [f for f in os.listdir(path) if os.path.isdir(os.path.join(path, f))]
        if len(folders) != 1:
            print(len(folders), 'FOLDERS DETECTED')
            return None
        print('GOING DEEPER')
        return searchInit(os.path.join(path, folders[0]))

    print('SEARCHING FOR INIT 2')
    extracted_zip_dir = searchInit(downloads_dir)
    if not extracted_zip_dir:
        print("INIT NOT FOUND!")
        shutil.rmtree(downloads_dir, ignore_errors=True)
        # finish_reloading()
        finish_update(error=t('download_file.cantFindCATS'))
        return

    # Remove old addon files
    clean_addon_dir()

    # Move the extracted files to their correct places
    def move_files(from_dir, to_dir):
        print('MOVE FILES TO DIR:', to_dir)
        files = os.listdir(from_dir)
        for file in files:
            file_dir = os.path.join(from_dir, file)
            target_dir = os.path.join(to_dir, file)
            print('MOVE', file_dir)

            # If file exists
            if os.path.isfile(file_dir) and os.path.isfile(target_dir):
                os.remove(target_dir)
                shutil.move(file_dir, to_dir)
                print('REMOVED AND MOVED', file)

            elif os.path.isdir(file_dir) and os.path.isdir(target_dir):
                move_files(file_dir, target_dir)

            else:
                shutil.move(file_dir, to_dir)
                print('MOVED', file)

    move_files(extracted_zip_dir, main_dir)

    # Delete download folder
    print('DELETE DOWNLOADS DIR')
    shutil.rmtree(downloads_dir, ignore_errors=True)

    # Finish the update
    finish_update()


def finish_update(error=''):
    global update_finished, show_error
    show_error = error

    if not error:
        update_finished = True

    bpy.ops.cats_updater.update_complete_panel('INVOKE_DEFAULT')
    ui_refresh()
    print("UPDATE DONE!")


def clean_addon_dir():
    print("CLEAN ADDON FOLDER")

    # first remove root files and folders (except update folder, important folders and resource folder)
    files = [f for f in os.listdir(main_dir) if os.path.isfile(os.path.join(main_dir, f))]
    folders = [f for f in os.listdir(main_dir) if os.path.isdir(os.path.join(main_dir, f))]

    for f in files:
        file = os.path.join(main_dir, f)
        try:
            os.remove(file)
            print("Clean removing file {}".format(file))
        except OSError:
            print("Failed to pre-remove file " + file)

    for f in folders:
        folder = os.path.join(main_dir, f)
        if f.startswith('.') or f == 'resources' or f == 'downloads':
            continue

        try:
            shutil.rmtree(folder)
            print("Clean removing folder and contents {}".format(folder))
        except OSError:
            print("Failed to pre-remove folder " + folder)

    # then remove resource files and folders (except settings and google dict)
    resources_folder = os.path.join(main_dir, 'resources')
    files = [f for f in os.listdir(resources_folder) if os.path.isfile(os.path.join(resources_folder, f))]
    folders = [f for f in os.listdir(resources_folder) if os.path.isdir(os.path.join(resources_folder, f))]

    for f in files:
        if f == 'settings.json' or f == 'dictionary_google.json':
            continue
        file = os.path.join(resources_folder, f)
        try:
            os.remove(file)
            print("Clean removing file {}".format(file))
        except OSError:
            print("Failed to pre-remove " + file)

    for f in folders:
        folder = os.path.join(resources_folder, f)
        try:
            shutil.rmtree(folder)
            print("Clean removing folder and contents {}".format(folder))
        except OSError:
            print("Failed to pre-remove folder " + folder)


def set_ignored_version():
    # Keep updater state in Blender's user configuration, not the extension.
    Paths.UPDATER_STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Create ignore file
    with open(ignore_ver_file, 'w', encoding="utf8") as outfile:
        outfile.write(latest_version_str)

    # Set ignored status
    global is_ignored_version
    is_ignored_version = True
    print('IGNORE VERSION ' + latest_version_str)


def check_ignored_version():
    if not latest_version_str:
        return False

    if not os.path.isfile(ignore_ver_file):
        # print('IGNORE FILE NOT FOUND')
        return False

    # Read ignore file
    with open(ignore_ver_file, 'r', encoding="utf8") as outfile:
        version = outfile.read()

    # Check if the latest version matches the one in the ignore file
    if latest_version_str == version:
        print('Update ignored.')
        return True

    # Delete ignore version file if the latest version is not the version in the file
    try:
        os.remove(ignore_ver_file)
    except OSError:
        print("FAILED TO REMOVE IGNORE VERSION FILE")

    return False


def get_version_list(self, context):
    choices = []
    if version_list:
        for version in version_list.keys():
            choices.append((version, version, version))

    return choices


def get_user_preferences():
    return bpy.context.preferences


def layout_split(layout, factor=0.0, align=False):
    return layout.split(factor=factor, align=align)


def draw_update_notification_panel(layout):
    if not update_needed or remind_me_later or is_ignored_version:
        # pass
        return

    col = layout.column(align=True)

    if update_finished:
        col.separator()
        row = col.row(align=True)
        row.label(text=t('draw_update_notification_panel.success'), icon='ERROR')
        col.separator()
        return

    row = col.row(align=True)
    row.scale_y = 0.75
    row.label(text=t('draw_update_notification_panel.newUpdate', name=latest_version_str), icon='SOLO_ON')

    col.separator()
    row = col.row(align=True)
    row.scale_y = 1.3
    row.operator(UpdateToLatestButton.bl_idname, text=t('draw_update_notification_panel.UpdateToLatestButton.label'))

    row = col.row(align=True)
    row.scale_y = 1
    row.operator(RemindMeLaterButton.bl_idname, text=t('draw_update_notification_panel.RemindMeLaterButton.label'))
    row.operator(IgnoreThisVersionButton.bl_idname, text=t('draw_update_notification_panel.IgnoreThisVersionButton.label'))


def draw_updater_panel(context, layout, user_preferences=False):
    col = layout.column(align=True)

    scale_big = 2
    scale_small = 1.2

    row = col.row(align=True)
    row.scale_y = 0.8
    row.label(text=t('draw_updater_panel.updateLabel') if not user_preferences else t('draw_updater_panel.updateLabel_alt'), icon=ICON_URL)
    col.separator()

    if update_finished:
        col.separator()
        row = col.row(align=True)
        row.label(text=t('draw_updater_panel.success'), icon='ERROR')
        col.separator()
        return

    if show_error:
        row = col.row(align=True)
        row.label(text=show_error, icon='ERROR')
        col.separator()

    if is_checking_for_update:
        if not used_updater_panel:
            row = col.row(align=True)
            row.scale_y = scale_big
            row.operator(CheckForUpdateButton.bl_idname, text=t('draw_updater_panel.CheckForUpdateButton.label'))
        else:
            split = col.row(align=True)
            row = split.row(align=True)
            row.scale_y = scale_big
            row.operator(CheckForUpdateButton.bl_idname, text=t('draw_updater_panel.CheckForUpdateButton.label'))
            row = split.row(align=True)
            row.alignment = 'RIGHT'
            row.scale_y = scale_big
            row.operator(CheckForUpdateButton.bl_idname, text="", icon='FILE_REFRESH')

    elif update_needed:
        split = col.row(align=True)
        row = split.row(align=True)
        row.scale_y = scale_big
        row.operator(UpdateToLatestButton.bl_idname, text=t('draw_updater_panel.UpdateToLatestButton.label', name=latest_version_str))
        row = split.row(align=True)
        row.alignment = 'RIGHT'
        row.scale_y = scale_big
        row.operator(CheckForUpdateButton.bl_idname, text="", icon='FILE_REFRESH')

    elif not used_updater_panel or not version_list:
        row = col.row(align=True)
        row.scale_y = scale_big
        row.operator(CheckForUpdateButton.bl_idname, text=t('draw_updater_panel.CheckForUpdateButton.label_alt'))

    else:
        split = col.row(align=True)
        row = split.row(align=True)
        row.scale_y = scale_big
        row.operator(UpdateToLatestButton.bl_idname, text=t('draw_updater_panel.UpdateToLatestButton.label_alt'))
        row = split.row(align=True)
        row.alignment = 'RIGHT'
        row.scale_y = scale_big
        row.operator(CheckForUpdateButton.bl_idname, text="", icon='FILE_REFRESH')

    # col.separator()
    # col.separator()
    # col.separator()
    # row = layout_split(col, factor=0.6, align=True)
    # row.scale_y = 0.9
    # row.active = True if not is_checking_for_update and version_list else False
    # row.label(text="Select Version:")
    # row.prop(context.scene, 'cats_updater_version_list', text='')
    #
    # row = layout_split(col, factor=0.6, align=True)
    # row.scale_y = scale_small
    # row.operator(UpdateToSelectedButton.bl_idname, text='Install Selected Version')
    # row.operator(ShowPatchnotesPanel.bl_idname, text='Show Patchnotes')

    col.separator()
    col.separator()
    split = col.row(align=True)
    row = layout_split(split, factor=0.55, align=True)
    row.scale_y = scale_small
    row.active = True if not is_checking_for_update and version_list else False
    row.operator(UpdateToSelectedButton.bl_idname, text=t('draw_updater_panel.UpdateToSelectedButton.label'))
    row.prop(context.scene, 'cats_updater_version_list', text='')
    row = split.row(align=True)
    row.scale_y = scale_small
    row.operator(ShowPatchnotesPanel.bl_idname, text="", icon='WORDWRAP_ON')

    # topsplit = layout_split(col, factor=0.55, align=True)
    #
    # split = topsplit.row(align=True)
    # row = split.row(align=True)
    # row.scale_y = scale_small
    # row.active = True if not is_checking_for_update and version_list else False
    # row.operator(UpdateToSelectedButton.bl_idname, text='Install Version:')
    #
    # row = split.row(align=True)
    # row.alignment = 'RIGHT'
    # row.scale_y = scale_small
    # row.operator(ShowPatchnotesPanel.bl_idname, text="", icon='WORDWRAP_ON')
    #
    # row = topsplit.row(align=True)
    # row.scale_y = scale_small
    # row.prop(context.scene, 'cats_updater_version_list', text='')

    row = col.row(align=True)
    row.scale_y = scale_small
    row.operator(UpdateToDevButton.bl_idname, text=t('draw_updater_panel.UpdateToDevButton.label'))

    col.separator()
    row = col.row(align=True)
    row.scale_y = 0.65
    row.label(text=t('draw_updater_panel.currentVersion', name=current_version_str))


# demo bare-bones preferences
class DemoPreferences(bpy.types.AddonPreferences):
    bl_idname = package_name

    def draw(self, context):
        layout = self.layout
        draw_updater_panel(context, layout, user_preferences=True)


to_register = [
    CheckForUpdateButton,
    UpdateToLatestButton,
    UpdateToSelectedButton,
    UpdateToDevButton,
    RemindMeLaterButton,
    IgnoreThisVersionButton,
    ShowPatchnotesPanel,
    ConfirmUpdatePanel,
    UpdateCompletePanel,
    UpdateNotificationPopup,
    DemoPreferences,
]


def register(dev_branch, version_str):
    # print('REGISTER CATS UPDATER')
    global current_version, fake_update, current_version_str

    # If not dev branch, always disable fake update!
    if not dev_branch:
        fake_update = False
    current_version_str = version_str

    # Get current version
    current_version = []
    version_parts = CATS_VERSION.split(".")

    for part in version_parts:
        current_version.append(int(part))

    bpy.types.Scene.cats_updater_version_list = bpy.props.EnumProperty(
        name=t('bpy.types.Scene.cats_updater_version_list.label'),
        description=t('bpy.types.Scene.cats_updater_version_list.desc'),
        items=wrap_dynamic_enum_items(get_version_list, 'cats_updater_version_list', sort=False)
    )
    bpy.types.Scene.cats_update_action = bpy.props.EnumProperty(
        name=t('bpy.types.Scene.cats_update_action.label'),
        description=t('bpy.types.Scene.cats_update_action.desc'),
        items=[
            ("UPDATE", t('bpy.types.Scene.cats_update_action.update.label'), t('bpy.types.Scene.cats_update_action.update.desc')),
            ("IGNORE", t('bpy.types.Scene.cats_update_action.ignore.label'), t( 'bpy.types.Scene.cats_update_action.ignore.desc')),
            ("DEFER", t('bpy.types.Scene.cats_update_action.defer.label'), t( 'bpy.types.Scene.cats_update_action.defer.desc'))
        ]
    )

    # Register all Updater classes
    count = 0
    for cls in to_register:
        try:
            bpy.utils.register_class(cls)
            count += 1
        except ValueError:
            pass
    # print('Registered', count, 'CATS updater classes.')
    if count < len(to_register):
        print('Skipped', len(to_register) - count, 'CATS updater classes.')


def unregister():
    global is_checking_for_update
    is_checking_for_update = False
    if bpy.app.timers.is_registered(_poll_update_result):
        bpy.app.timers.unregister(_poll_update_result)
    update_post = get_update_post()
    if show_update_notification in update_post:
        update_post.remove(show_update_notification)

    # Unregister all Updater classes
    for cls in reversed(to_register):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass

    if hasattr(bpy.types.Scene, 'cats_updater_version_list'):
        del bpy.types.Scene.cats_updater_version_list

    if hasattr(bpy.types.Scene, 'cats_update_action'):
        del bpy.types.Scene.cats_update_action
