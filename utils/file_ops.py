import os
import json
import shutil
import sys
import time
from typing import List, Dict, Any


def default_config_file() -> str:
    if getattr(sys, "frozen", False):
        executable_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.join(executable_dir, "config.json")
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config.json",
    )


CONFIG_FILE = default_config_file()

RESOURCE_PROFILES = {
    "conservative": {
        "thumbnail_workers": 2,
        "thumbnail_cache_mb": 512,
        "crop_prefetch_mb": 256,
        "crop_prefetch_workers": 1,
    },
    "balanced": {
        "thumbnail_workers": 4,
        "thumbnail_cache_mb": 2048,
        "crop_prefetch_mb": 512,
        "crop_prefetch_workers": 2,
    },
    "performance": {
        "thumbnail_workers": 8,
        "thumbnail_cache_mb": 5120,
        "crop_prefetch_mb": 1024,
        "crop_prefetch_workers": 2,
    },
}

ADJUSTMENT_LIMITS = {
    "Brightness": (-100, 100, 0),
    "Contrast": (-100, 100, 0),
    "Gamma": (10, 300, 100),
    "Exposure": (-300, 300, 0),
    "Sharpness": (-100, 100, 0),
    "Temperature": (-100, 100, 0),
    "Tint": (-100, 100, 0),
    "Hue": (-180, 180, 0),
    "Saturation": (-100, 100, 0),
    "Red": (-100, 100, 0),
    "Green": (-100, 100, 0),
    "Blue": (-100, 100, 0),
    "Shadows": (-100, 100, 0),
    "Highlights": (-100, 100, 0),
}
ADJUSTMENT_TOGGLE_NAMES = (
    "Grayscale",
    "Invert",
    "Auto Contrast",
    "Equalize",
)
ADJUSTMENT_NAMES = tuple(ADJUSTMENT_LIMITS)

def load_config() -> Dict[str, Any]:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"recent_folders": []}

def save_config(config: Dict[str, Any]):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

def normalize_folder_path(folder_path: str) -> str:
    if not isinstance(folder_path, str) or not folder_path.strip():
        return ""
    return os.path.normpath(os.path.abspath(os.path.expanduser(folder_path.strip())))

def _folder_path_key(folder_path: str) -> str:
    return os.path.normcase(normalize_folder_path(folder_path))

def _normalized_folder_list(folder_paths) -> List[str]:
    normalized = []
    seen = set()
    for folder_path in folder_paths or []:
        path = normalize_folder_path(folder_path)
        key = os.path.normcase(path)
        if path and key not in seen:
            normalized.append(path)
            seen.add(key)
    return normalized

def add_recent_folder(folder_path: str):
    folder_path = normalize_folder_path(folder_path)
    if not folder_path:
        return
    config = load_config()
    key = _folder_path_key(folder_path)
    recent = [
        path for path in _normalized_folder_list(config.get("recent_folders", []))
        if _folder_path_key(path) != key
    ]
    recent.insert(0, folder_path)
    config["recent_folders"] = recent
    save_config(config)

def get_recent_folders() -> List[str]:
    return _normalized_folder_list(load_config().get("recent_folders", []))

def add_address_folder(folder_path: str):
    folder_path = normalize_folder_path(folder_path)
    if not folder_path:
        return
    config = load_config()
    key = _folder_path_key(folder_path)
    recent = [
        path for path in _normalized_folder_list(config.get("address_folders", []))
        if _folder_path_key(path) != key
    ]
    recent.insert(0, folder_path)
    config["address_folders"] = recent[:20]
    save_config(config)

def get_address_folders() -> List[str]:
    return _normalized_folder_list(load_config().get("address_folders", []))

def add_favorite_folder(folder_path: str):
    config = load_config()
    folder_path = os.path.abspath(folder_path)
    favorites = config.get("favorite_folders", [])
    favorites = [path for path in favorites if _favorite_key(path) != _favorite_key(folder_path)]
    favorites.append(folder_path)
    config["favorite_folders"] = favorites
    save_config(config)

def _favorite_key(folder_path: str) -> str:
    return os.path.normcase(os.path.abspath(folder_path))

def set_favorite_display_name(folder_path: str, display_name: str):
    config = load_config()
    names = config.get("favorite_display_names", {})
    key = _favorite_key(folder_path)
    display_name = (display_name or "").strip()
    if display_name:
        names[key] = display_name
    else:
        names.pop(key, None)
    config["favorite_display_names"] = names
    save_config(config)

def get_favorite_display_name(folder_path: str) -> str:
    names = load_config().get("favorite_display_names", {})
    return names.get(_favorite_key(folder_path), "")

def set_favorite_sort_setting(folder_path: str, sort_key: str, reverse: bool):
    if sort_key not in ("name", "date", "type"):
        return
    config = load_config()
    key = _favorite_key(folder_path)
    favorite_keys = {
        _favorite_key(path) for path in config.get("favorite_folders", [])
    }
    if key not in favorite_keys:
        return
    settings = config.get("favorite_sort_settings", {})
    settings[key] = {"key": sort_key, "reverse": bool(reverse)}
    config["favorite_sort_settings"] = settings
    save_config(config)

def get_favorite_sort_setting(folder_path: str):
    setting = load_config().get("favorite_sort_settings", {}).get(
        _favorite_key(folder_path)
    )
    if not isinstance(setting, dict):
        return None
    sort_key = setting.get("key")
    if sort_key not in ("name", "date", "type"):
        return None
    return sort_key, bool(setting.get("reverse", False))

def remove_favorite_folder(folder_path: str):
    config = load_config()
    folder_path = os.path.abspath(folder_path)
    config["favorite_folders"] = [
        path for path in config.get("favorite_folders", [])
        if _favorite_key(path) != _favorite_key(folder_path)
    ]
    names = config.get("favorite_display_names", {})
    names.pop(_favorite_key(folder_path), None)
    config["favorite_display_names"] = names
    sort_settings = config.get("favorite_sort_settings", {})
    sort_settings.pop(_favorite_key(folder_path), None)
    config["favorite_sort_settings"] = sort_settings
    save_config(config)

def get_favorite_folders() -> List[str]:
    return load_config().get("favorite_folders", [])

def set_last_folder(folder_path: str):
    config = load_config()
    config["last_folder"] = normalize_folder_path(folder_path)
    save_config(config)

def get_last_folder() -> str:
    return load_config().get("last_folder", "")

def set_thumbnail_size(size: int):
    config = load_config()
    config["thumbnail_size"] = size
    save_config(config)

def get_thumbnail_size() -> int:
    return load_config().get("thumbnail_size", 200)

def get_ui_theme() -> str:
    theme = load_config().get("ui_theme", "dark")
    return theme if theme in ("dark", "medium_dark", "light") else "dark"

def set_ui_theme(theme: str):
    config = load_config()
    config["ui_theme"] = theme if theme in ("dark", "medium_dark", "light") else "dark"
    save_config(config)

def set_fullscreen_hud_visible(visible: bool):
    config = load_config()
    config["fullscreen_hud_visible"] = bool(visible)
    save_config(config)

def get_fullscreen_hud_visible() -> bool:
    return bool(load_config().get("fullscreen_hud_visible", True))

def set_slideshow_mode(mode: str):
    config = load_config()
    config["slideshow_mode"] = "random" if mode == "random" else "ordered"
    save_config(config)

def get_slideshow_mode() -> str:
    mode = load_config().get("slideshow_mode", "ordered")
    return "random" if mode == "random" else "ordered"

def set_startup_behavior(behavior: str):
    config = load_config()
    config["startup_behavior"] = behavior
    save_config(config)

def get_startup_behavior() -> str:
    return load_config().get("startup_behavior", "last_used")

def get_resource_settings() -> Dict[str, Any]:
    config = load_config()
    profile = config.get("resource_profile", "balanced")
    if profile not in (*RESOURCE_PROFILES.keys(), "custom"):
        profile = "balanced"
    custom_workers = max(1, min(8, int(config.get("custom_thumbnail_workers", 4))))
    custom_cache_mb = max(256, min(5120, int(config.get("custom_thumbnail_cache_mb", 2048))))
    custom_prefetch_mb = max(128, min(1024, int(config.get("custom_crop_prefetch_mb", 512))))

    if profile == "custom":
        requested_workers = custom_workers
        thumbnail_cache_mb = custom_cache_mb
        crop_prefetch_mb = custom_prefetch_mb
        crop_prefetch_workers = 1 if requested_workers <= 2 else 2
    else:
        preset = RESOURCE_PROFILES[profile]
        requested_workers = preset["thumbnail_workers"]
        thumbnail_cache_mb = preset["thumbnail_cache_mb"]
        crop_prefetch_mb = preset["crop_prefetch_mb"]
        crop_prefetch_workers = preset["crop_prefetch_workers"]

    logical_cpus = os.cpu_count() or 2
    effective_workers = min(requested_workers, max(1, logical_cpus - 2))
    return {
        "profile": profile,
        "thumbnail_workers": effective_workers,
        "requested_thumbnail_workers": requested_workers,
        "thumbnail_cache_mb": thumbnail_cache_mb,
        "crop_prefetch_mb": crop_prefetch_mb,
        "crop_prefetch_workers": crop_prefetch_workers,
        "custom_thumbnail_workers": custom_workers,
        "custom_thumbnail_cache_mb": custom_cache_mb,
        "custom_crop_prefetch_mb": custom_prefetch_mb,
    }

def set_resource_settings(profile: str, thumbnail_workers: int, thumbnail_cache_mb: int, crop_prefetch_mb: int):
    if profile not in (*RESOURCE_PROFILES.keys(), "custom"):
        profile = "balanced"
    config = load_config()
    config["resource_profile"] = profile
    config["custom_thumbnail_workers"] = max(1, min(8, int(thumbnail_workers)))
    config["custom_thumbnail_cache_mb"] = max(256, min(5120, int(thumbnail_cache_mb)))
    config["custom_crop_prefetch_mb"] = max(128, min(1024, int(crop_prefetch_mb)))
    save_config(config)

def set_format_quality(format_name: str, quality: int):
    config = load_config()
    key = f"quality_{format_name.lower()}"
    config[key] = quality
    save_config(config)

def get_format_quality(format_name: str) -> int:
    default_quality = 90
    key = f"quality_{format_name.lower()}"
    return load_config().get(key, default_quality)

def set_convert_appendix(appendix: str):
    config = load_config()
    config["convert_appendix"] = appendix
    save_config(config)

def get_convert_appendix() -> str:
    return load_config().get("convert_appendix", "_result")

def set_crop_ask_overwrite(enabled: bool):
    config = load_config()
    config["crop_ask_overwrite"] = bool(enabled)
    save_config(config)

def get_crop_ask_overwrite() -> bool:
    return load_config().get("crop_ask_overwrite", True)

def get_crop_auto_name_copies() -> bool:
    return bool(load_config().get("crop_auto_name_copies", False))

def set_crop_auto_name_copies(enabled: bool):
    config = load_config()
    config["crop_auto_name_copies"] = bool(enabled)
    save_config(config)

def get_adjustment_settings():
    config = load_config()
    enabled = bool(config.get("remember_adjustments", False))
    stored = config.get("adjustment_values", {}) if enabled else {}
    values = {}
    for name, (minimum, maximum, default) in ADJUSTMENT_LIMITS.items():
        try:
            value = int(stored.get(name, default))
        except (TypeError, ValueError):
            value = default
        values[name] = max(minimum, min(maximum, value))
    for name in ADJUSTMENT_TOGGLE_NAMES:
        values[name] = bool(stored.get(name, False))
    return enabled, values

def get_adjust_auto_name_copies() -> bool:
    return bool(load_config().get("adjust_auto_name_copies", False))

def set_adjust_auto_name_copies(enabled: bool):
    config = load_config()
    config["adjust_auto_name_copies"] = bool(enabled)
    save_config(config)

def get_adjust_resampling() -> str:
    value = str(load_config().get("adjust_resampling", "auto")).lower()
    valid = {
        "auto", "lanczos", "lanczos_sharper", "bicubic",
        "bicubic_sharper", "bilinear", "hamming", "nearest", "box",
    }
    return value if value in valid else "auto"

def set_adjust_resampling(value: str):
    config = load_config()
    config["adjust_resampling"] = str(value).lower()
    save_config(config)

def set_adjustment_settings(enabled: bool, values=None):
    config = load_config()
    config["remember_adjustments"] = bool(enabled)
    if enabled:
        source = values or {}
        stored = {}
        for name, (minimum, maximum, default) in ADJUSTMENT_LIMITS.items():
            try:
                value = int(source.get(name, default))
            except (TypeError, ValueError):
                value = default
            stored[name] = max(minimum, min(maximum, value))
        for name in ADJUSTMENT_TOGGLE_NAMES:
            stored[name] = bool(source.get(name, False))
        config["adjustment_values"] = stored
    else:
        config.pop("adjustment_values", None)
    save_config(config)

import ctypes
from ctypes import wintypes

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),
        ("pTo", ctypes.c_void_p),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR)
    ]

FO_MOVE = 0x0001
FO_COPY = 0x0002
FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400
FOF_MULTIDESTFILES = 0x0001

def _windows_file_op_many(wFunc, sources, dest_folder: str, timeout_seconds: float = 3.0):
    source_paths = [
        os.path.abspath(source)
        for source in sources
        if source and os.path.exists(source)
    ]
    if not source_paths:
        return False

    if not os.path.exists(dest_folder):
        os.makedirs(dest_folder)

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    delay = 0.05
    while True:
        # SHFileOperation accepts every source in one double-null-terminated list.
        # Keeping the selection in one operation lets Windows offer batch-wide
        # Replace/Skip choices when several destination names already exist.
        src_buf = ctypes.create_unicode_buffer("\0".join(source_paths) + '\0\0')
        dst_buf = ctypes.create_unicode_buffer(os.path.abspath(dest_folder) + '\0\0')

        op = SHFILEOPSTRUCTW()
        op.hwnd = 0
        op.wFunc = wFunc
        op.pFrom = ctypes.addressof(src_buf)
        op.pTo = ctypes.addressof(dst_buf)
        op.fFlags = FOF_NOERRORUI

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        if result == 0 and not op.fAnyOperationsAborted:
            add_recent_folder(dest_folder)
            return True
        if op.fAnyOperationsAborted:
            return None
        if result not in (32, 33):
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(delay)
        delay = min(0.25, delay * 1.5)


def _windows_file_op(wFunc, source: str, dest_folder: str, timeout_seconds: float = 3.0):
    return _windows_file_op_many(wFunc, [source], dest_folder, timeout_seconds)


def _windows_file_op_pairs(wFunc, pairs, overwrite=False, owner_hwnd=0,
                           timeout_seconds: float = 3.0):
    exact_pairs = [
        (os.path.abspath(source), os.path.abspath(destination))
        for source, destination in pairs
        if source and destination and os.path.exists(source)
    ]
    if not exact_pairs:
        return False

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    delay = 0.05
    while True:
        source_buffer = ctypes.create_unicode_buffer(
            "\0".join(source for source, _ in exact_pairs) + "\0\0"
        )
        destination_buffer = ctypes.create_unicode_buffer(
            "\0".join(destination for _, destination in exact_pairs) + "\0\0"
        )

        operation = SHFILEOPSTRUCTW()
        operation.hwnd = owner_hwnd or 0
        operation.wFunc = wFunc
        operation.pFrom = ctypes.addressof(source_buffer)
        operation.pTo = ctypes.addressof(destination_buffer)
        operation.fFlags = FOF_NOERRORUI | FOF_MULTIDESTFILES
        if overwrite:
            operation.fFlags |= FOF_NOCONFIRMATION

        result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
        if result == 0 and not operation.fAnyOperationsAborted:
            for destination_folder in {
                os.path.dirname(destination) for _, destination in exact_pairs
            }:
                add_recent_folder(destination_folder)
            return True
        if operation.fAnyOperationsAborted:
            return None
        if result not in (32, 33):
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(delay)
        delay = min(0.25, delay * 1.5)

def copy_file(source: str, dest_folder: str):
    try:
        return _windows_file_op(FO_COPY, source, dest_folder)
    except Exception as e:
        print(f"Error copying {source} to {dest_folder}: {e}")
        return False

def move_file(source: str, dest_folder: str):
    try:
        return _windows_file_op(FO_MOVE, source, dest_folder)
    except Exception as e:
        print(f"Error moving {source} to {dest_folder}: {e}")
        return False


def copy_files(sources: List[str], dest_folder: str):
    try:
        return _windows_file_op_many(FO_COPY, sources, dest_folder)
    except Exception as e:
        print(f"Error copying files to {dest_folder}: {e}")
        return False


def move_files(sources: List[str], dest_folder: str):
    try:
        return _windows_file_op_many(FO_MOVE, sources, dest_folder)
    except Exception as e:
        print(f"Error moving files to {dest_folder}: {e}")
        return False


def copy_file_pairs(pairs, overwrite=False, owner_hwnd=0):
    try:
        return _windows_file_op_pairs(
            FO_COPY, pairs, overwrite=overwrite, owner_hwnd=owner_hwnd
        )
    except Exception as error:
        print(f"Error copying files to exact destinations: {error}")
        return False


def move_file_pairs(pairs, overwrite=False, owner_hwnd=0):
    try:
        return _windows_file_op_pairs(
            FO_MOVE, pairs, overwrite=overwrite, owner_hwnd=owner_hwnd
        )
    except Exception as error:
        print(f"Error moving files to exact destinations: {error}")
        return False

def delete_files(paths: List[str], permanent: bool = False, timeout_seconds: float = 3.0) -> bool:
    if not paths:
        return False
    try:
        existing_paths = [os.path.abspath(path) for path in paths if os.path.exists(path)]
        if not existing_paths:
            return False

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        delay = 0.05
        while True:
            src_buf = ctypes.create_unicode_buffer("\0".join(existing_paths) + "\0\0")
            op = SHFILEOPSTRUCTW()
            op.hwnd = 0
            op.wFunc = FO_DELETE
            op.pFrom = ctypes.addressof(src_buf)
            op.pTo = 0
            op.fFlags = FOF_NOCONFIRMATION | FOF_SILENT
            if not permanent:
                op.fFlags |= FOF_ALLOWUNDO

            result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
            if result == 0 and not op.fAnyOperationsAborted:
                return True
            if op.fAnyOperationsAborted or result not in (32, 33):
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(delay)
            delay = min(0.25, delay * 1.5)
    except Exception as e:
        print(f"Error deleting files: {e}")
        return False
