import ctypes
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from ctypes import wintypes


SUPPORTED_SEND_TO_EXTENSIONS = {".lnk", ".exe", ".com", ".bat", ".cmd"}
MAX_SHELL_PARAMETERS = 30000
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x0001
SPIF_SENDCHANGE = 0x0002


@dataclass(frozen=True)
class SendToTarget:
    path: str
    display_name: str
    kind: str


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_string(cls, value):
        raw = uuid.UUID(value).bytes_le
        return cls(
            int.from_bytes(raw[0:4], "little"),
            int.from_bytes(raw[4:6], "little"),
            int.from_bytes(raw[6:8], "little"),
            (ctypes.c_ubyte * 8).from_buffer_copy(raw[8:16]),
        )


FOLDERID_SEND_TO = GUID.from_string("8983036C-27C0-404B-8F08-102D10DCFD74")

SHELL_ERROR_MESSAGES = {
    0: "Windows is out of memory or system resources.",
    2: "The file was not found.",
    3: "The path was not found.",
    5: "Access was denied.",
    8: "Windows is out of memory or system resources.",
    11: "The file is not a valid executable.",
    26: "A sharing violation occurred.",
    27: "The file association is incomplete.",
    28: "The operation timed out.",
    29: "The associated application is busy.",
    30: "The operation could not be completed.",
    31: "No application is associated with this file type.",
    32: "A required library was not found.",
}


def is_windows():
    return sys.platform == "win32"


def get_send_to_folder():
    if not is_windows():
        return ""

    path_ptr = ctypes.c_wchar_p()
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(GUID),
            wintypes.DWORD,
            wintypes.HANDLE,
            ctypes.POINTER(ctypes.c_wchar_p),
        ]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        result = shell32.SHGetKnownFolderPath(
            ctypes.byref(FOLDERID_SEND_TO), 0, None, ctypes.byref(path_ptr)
        )
        if result == 0 and path_ptr.value:
            return path_ptr.value
    except (AttributeError, OSError):
        pass
    finally:
        if path_ptr.value:
            try:
                ole32 = ctypes.WinDLL("ole32", use_last_error=True)
                ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
                ole32.CoTaskMemFree(path_ptr)
            except (AttributeError, OSError):
                pass

    app_data = os.environ.get("APPDATA", "")
    if not app_data:
        return ""
    return os.path.join(app_data, "Microsoft", "Windows", "SendTo")


def list_send_to_targets():
    folder = get_send_to_folder()
    if not folder or not os.path.isdir(folder):
        return []

    targets = []
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return []

    for entry in entries:
        if entry.name.lower() == "desktop.ini":
            continue
        try:
            is_directory = entry.is_dir()
        except OSError:
            continue
        if is_directory:
            targets.append(SendToTarget(entry.path, entry.name, "folder"))
            continue

        extension = os.path.splitext(entry.name)[1].lower()
        if extension not in SUPPORTED_SEND_TO_EXTENSIONS:
            continue
        display_name = os.path.splitext(entry.name)[0]
        targets.append(SendToTarget(entry.path, display_name, "application"))

    return sorted(targets, key=lambda target: target.display_name.casefold())


def open_associated_file(file_path, verb="open", owner_hwnd=0):
    if not is_windows():
        return False, "This Windows Shell action is not available on this platform."
    if not file_path or not os.path.exists(file_path):
        return False, "The selected file no longer exists."
    return _shell_execute(file_path, verb=verb, owner_hwnd=owner_hwnd)


def print_file(file_path, owner_hwnd=0):
    return open_associated_file(file_path, verb="print", owner_hwnd=owner_hwnd)


def set_desktop_wallpaper(file_path):
    if not is_windows():
        return False, "Desktop wallpaper integration is only available on Windows."
    if not file_path or not os.path.isfile(file_path):
        return False, "The selected image no longer exists."

    absolute_path = os.path.abspath(file_path)
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        set_parameter = user32.SystemParametersInfoW
        set_parameter.argtypes = [
            wintypes.UINT,
            wintypes.UINT,
            wintypes.LPWSTR,
            wintypes.UINT,
        ]
        set_parameter.restype = wintypes.BOOL
        path_buffer = ctypes.create_unicode_buffer(absolute_path)
        result = set_parameter(
            SPI_SETDESKWALLPAPER,
            0,
            path_buffer,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
        )
    except (AttributeError, OSError) as error:
        return False, str(error)

    if result:
        return True, ""
    error_code = ctypes.get_last_error()
    if error_code:
        return False, ctypes.FormatError(error_code).strip()
    return False, "Windows could not set the selected image as desktop wallpaper."


def launch_send_to_target(target, file_paths, owner_hwnd=0):
    if not is_windows():
        return False, "Windows Send To is not available on this platform."
    if not target or target.kind != "application" or not os.path.exists(target.path):
        return False, "The selected Send To target no longer exists."

    paths = [os.path.abspath(path) for path in file_paths if path and os.path.exists(path)]
    if not paths:
        return False, "None of the selected files still exist."
    parameters = subprocess.list2cmdline(paths)
    if len(parameters) > MAX_SHELL_PARAMETERS:
        return False, "Too many files or file paths are too long for this Send To target."
    return _shell_execute(target.path, parameters=parameters, owner_hwnd=owner_hwnd)


def _shell_execute(file_path, verb="open", parameters=None, owner_hwnd=0):
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        shell_execute = shell32.ShellExecuteW
        shell_execute.argtypes = [
            wintypes.HWND,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.c_int,
        ]
        shell_execute.restype = ctypes.c_void_p
        result = shell_execute(
            owner_hwnd or None,
            verb,
            os.path.abspath(file_path),
            parameters,
            os.path.dirname(os.path.abspath(file_path)) or None,
            1,
        )
        result_code = int(result or 0)
    except (AttributeError, OSError) as error:
        return False, str(error)

    if result_code > 32:
        return True, ""
    return False, SHELL_ERROR_MESSAGES.get(
        result_code, f"Windows could not complete the operation (error {result_code})."
    )
