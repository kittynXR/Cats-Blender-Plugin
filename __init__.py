# MIT License

CATS_VERSION = "5.1.1.0"
dev_branch = False

# Each release line declares the Blender versions it has actually been tested
# against.  The upper bound is exclusive so the 5.1 bridge cannot silently be
# enabled on a future Blender API.
BLENDER_VERSION_MIN = (5, 1, 0)
BLENDER_VERSION_MAX = (5, 2, 0)

import os
import sys

# Append bundled tools to sys.path before importing mmd_tools_local.  Blender
# can call register/unregister more than once without re-importing this module,
# so register() restores the path after unregister() removes it.
file_dir = os.path.join(os.path.dirname(__file__), 'extern_tools')


def _ensure_external_tools_path():
    if file_dir not in sys.path:
        sys.path.append(file_dir)


_ensure_external_tools_path()

import pathlib

from importlib.util import find_spec

from . import globs

# Check if cats is reloading or started fresh
if "bpy" not in locals():
    import bpy
    is_reloading = False
else:
    is_reloading = True

# Load or reload all cats modules
if not is_reloading:
    # This order is important
    import mmd_tools_local
    if find_spec("imscale") and find_spec("imscale.immersive_scaler"):
        import imscale.immersive_scaler as imscale
    from . import updater
    from . import tools
    from . import ui
    from . import extentions
else:
    import importlib
    importlib.reload(updater)
    importlib.reload(mmd_tools_local)
    if 'imscale' in vars():
        importlib.reload(imscale)
    importlib.reload(tools)
    importlib.reload(ui)
    importlib.reload(extentions)

from .tools import translations
from .tools.translations import t


# How to update mmd_tools_local:
# MMD Tools is no longer a drop in replacement, manually work is required please ask
# us to update it instead.

# How to update google_trans_new:
# In google_trans.py comment out everything that has to do with urllib3
# This is done because 3.5 doesn't have urllib3 by default and it is only used
# to suppress debug logs in the console
# Done

# How to set up PyCharm with Blender:
# https://b3d.interplanety.org/en/using-external-ide-pycharm-for-writing-blender-scripts/


def remove_corrupted_files():
    """Validate the package without modifying files outside the extension.

    Older releases tried to repair malformed installs by deleting generic file
    and directory names from the package's parent directory.  With Blender
    extensions that parent can contain unrelated add-ons, so repair must never
    happen automatically.  Keep this legacy entry point for compatibility and
    report an incomplete package instead.
    """
    package_dir = pathlib.Path(__file__).resolve().parent
    required_paths = (
        package_dir / 'extern_tools',
        package_dir / 'resources',
        package_dir / 'tools',
        package_dir / 'ui',
        package_dir / 'globs.py',
        package_dir / 'updater.py',
    )
    missing = [path.name for path in required_paths if not path.exists()]
    if missing:
        sys.tracebacklimit = 0
        raise ImportError(
            'CATS installation is incomplete; missing: ' + ', '.join(missing)
        )


def check_unsupported_blender_versions():
    if not BLENDER_VERSION_MIN <= bpy.app.version < BLENDER_VERSION_MAX:
        minimum = '.'.join(str(part) for part in BLENDER_VERSION_MIN)
        maximum = '.'.join(str(part) for part in BLENDER_VERSION_MAX)
        sys.tracebacklimit = 0
        raise ImportError(
            f'CATS {CATS_VERSION} supports {minimum} <= Blender < {maximum}; '
            f'current Blender is {bpy.app.version_string}.'
        )

def set_cats_version_string():
    version_parts = CATS_VERSION.split(".")

    # Convert version parts to integers
    version_parts = [int(part) for part in version_parts]

    # Increment the last version component if in dev branch
    if dev_branch:
        version_parts[-1] += 1

    # Convert version back to string
    version_str = ".".join(str(part) for part in version_parts)

    # Add -dev if in dev version
    if dev_branch:
        version_str += "-dev"

    return version_str

def register():
    print("\n### Loading CATS...")

    _ensure_external_tools_path()

    # Check for unsupported Blender versions
    check_unsupported_blender_versions()

    # Check for faulty CATS installations
    remove_corrupted_files()

    # Set cats version string
    version_str = set_cats_version_string()

    # Register Updater and check for CATS update
    updater.register(dev_branch, version_str)

    # Set some global settings, first allowed use of globs
    globs.dev_branch = dev_branch
    globs.version_str = version_str

    # Load settings and show error if a faulty installation was deleted recently
    try:
        tools.settings.load_settings()
    except FileNotFoundError:
        sys.tracebacklimit = 0
        raise ImportError(t('Main.error.restartAndEnable_alt'))

    # if not tools.settings.use_custom_mmd_tools_local():
    #     bpy.utils.unregister_module("mmd_tools_local")

    # Load mmd_tools_local
    try:
        mmd_tools_local.register()
    except NameError:
        print('Could not register local mmd_tools_local')
    except AttributeError:
        print('Could not register local mmd_tools_local')
    except ValueError:
        print('mmd_tools_local is already registered')

    # Register immersive scaler if it's loaded
    if find_spec("imscale") and find_spec("imscale.immersive_scaler"):
        import imscale.immersive_scaler as imscale
        try:
            imscale.register()
        except ModuleNotFoundError:
            pass

    # Register all classes
    count = 0
    tools.register.order_classes()
    classes = tools.register.__bl_ordered_classes
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
            count += 1
        except ValueError:
            pass
    # print('Registered', count, 'CATS classes.')
    if count < len(classes):
        print('Skipped', len(classes) - count, 'CATS classes.')

    # Register Scene types
    extentions.register()
    
    # Load Icon Loader and settings icons and buttons
    tools.iconloader.load_other_icons()

    # Load the dictionaries and check if they are found.
    globs.dict_found = tools.translate.load_translations()

    # Set preferred Blender options
    if hasattr(tools.common.get_user_preferences(), 'system') and hasattr(tools.common.get_user_preferences().system, 'use_international_fonts'):
        tools.common.get_user_preferences().system.use_international_fonts = True
    elif hasattr(tools.common.get_user_preferences(), 'view') and hasattr(tools.common.get_user_preferences().view, 'use_international_fonts'):
        tools.common.get_user_preferences().view.use_international_fonts = True
    else:
        pass  # From 2.83 on this is no longer needed
    tools.common.get_user_preferences().filepaths.use_file_compression = True
    bpy.context.window_manager.addon_support = {'OFFICIAL', 'COMMUNITY'}

    # Add shapekey button to shapekey menu
    bpy.types.MESH_MT_shape_key_context_menu.append(tools.shapekey.addToShapekeyMenu)

    # Apply the settings after a short time, because you can't change checkboxes during register process
    tools.settings.start_apply_settings_timer()

    print("### Loaded CATS successfully!\n")


def unregister():
    print("### Unloading CATS...")

    # Stop callbacks before removing the Scene properties they access.
    tools.settings.stop_apply_settings_threads()

    # Unregister updater
    updater.unregister()

    # Unload mmd_tools_local
    try:
        mmd_tools_local.unregister()
    except NameError:
        print('mmd_tools_local was not registered')
        pass
    except AttributeError:
        print('Could not unregister local mmd_tools_local')
        pass
    except ValueError:
        print('mmd_tools_local was not registered')
        pass

    # Unload immersive scaler
    if find_spec("imscale") and find_spec("imscale.immersive_scaler"):
        import imscale.immersive_scaler as imscale
        try:
            imscale.unregister()
        except ModuleNotFoundError:
            pass 

    # Unload all classes in reverse order
    extentions.unregister()

    count = 0
    for cls in reversed(tools.register.__bl_ordered_classes):
        try:
            bpy.utils.unregister_class(cls)
            count += 1
        except ValueError:
            pass
        except RuntimeError:
            pass
    print('Unregistered', count, 'CATS classes.')

    # Unregister all dynamic buttons and icons
    tools.iconloader.unload_icons()

    # Remove shapekey button from shapekey menu
    try:
        bpy.types.MESH_MT_shape_key_context_menu.remove(tools.shapekey.addToShapekeyMenu)
    except (AttributeError, ValueError):
        print('shapekey button was not registered')

    # Remove folder from sys path
    if file_dir in sys.path:
        sys.path.remove(file_dir)

    print("### Unloaded CATS successfully!\n")


if __name__ == '__main__':
    register()
