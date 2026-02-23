from __future__ import annotations

import platform
import shutil
from pathlib import Path

from src.core.exceptions import BinaryNotFoundError

def find_binary(name: str) -> Path:
    """Busca un binario en el PATH del sistema.

    Args:
        name: Nombre del binario (e.g. 'ffmpeg', 'ffprobe').

    Returns:
        Path absoluto al binario.

    Raises:
        BinaryNotFoundError: Si el binario no se encuentra.
    """
    path = shutil.which(name)
    if path is None:
        raise BinaryNotFoundError(name)
    return Path(path)


def get_ffmpeg() -> Path:
    """Devuelve la ruta a ffmpeg."""
    return find_binary("ffmpeg")


def get_ffprobe() -> Path:
    """Devuelve la ruta a ffprobe."""
    return find_binary("ffprobe")


def current_os() -> str:
    """Devuelve el sistema operativo actual: 'windows', 'darwin', 'linux'."""
    system = platform.system().lower()
    if system == "darwin":
        return "darwin"
    if system == "windows":
        return "windows"
    return "linux"


def is_windows() -> bool:
    return current_os() == "windows"


def is_macos() -> bool:
    return current_os() == "darwin"


def is_linux() -> bool:
    return current_os() == "linux"


def safe_filename(name: str) -> str:
    """Sanitiza un nombre de archivo eliminando caracteres problemáticos."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "_")
    return name.strip(". ")
