from __future__ import annotations

import secrets
from pathlib import Path

from src.core.exceptions import EncryptionError


def generate_aes_key() -> bytes:
    """Genera una clave AES-128 aleatoria de 16 bytes."""
    return secrets.token_bytes(16)


def generate_iv() -> str:
    """Genera un IV aleatorio como string hexadecimal."""
    return secrets.token_hex(16)


def write_key_file(key: bytes, path: Path) -> None:
    """Escribe la clave AES en un archivo binario."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)


def create_key_info_file(
    key_uri: str,
    key_file_path: Path,
    output_path: Path,
    iv: str | None = None,
) -> Path:
    """Crea el archivo key_info para ffmpeg HLS encryption.

    El formato del archivo es:
        <key_uri>       ← URL desde donde el player descarga la clave
        <key_file_path> ← Ruta local al archivo de clave (para ffmpeg)
        <iv>            ← IV hexadecimal (opcional)

    Args:
        key_uri: URI de la clave para el manifiesto HLS.
        key_file_path: Ruta local al archivo con la clave binaria.
        output_path: Dónde escribir el archivo key_info.
        iv: IV hexadecimal opcional.

    Returns:
        Ruta al archivo key_info generado.
    """
    if not key_file_path.exists():
        raise EncryptionError(f"Archivo de clave no encontrado: {key_file_path}")

    lines = [key_uri, str(key_file_path)]
    if iv:
        lines.append(iv)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def setup_encryption(output_dir: Path, key_uri: str = "key.bin") -> Path:
    """Genera clave, IV y archivo key_info para cifrado AES-128.

    Args:
        output_dir: Directorio de salida del paquete HLS.
        key_uri: URI relativa de la clave para el manifiesto.

    Returns:
        Ruta al archivo key_info listo para ffmpeg.
    """
    key = generate_aes_key()
    iv = generate_iv()

    key_file = output_dir / "key.bin"
    write_key_file(key, key_file)

    key_info = output_dir / "key_info.txt"
    return create_key_info_file(key_uri, key_file, key_info, iv)
