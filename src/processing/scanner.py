from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from src.core.exceptions import ProbeError
from src.core.models import (
    AudioStream,
    BITMAP_SUBTITLE_CODECS,
    MediaInfo,
    SubtitleStream,
    VideoStream,
)
from src.utils.platform import get_ffprobe

logger = logging.getLogger("makave")


def probe(input_path: Path) -> dict:
    """Ejecuta ffprobe y devuelve el JSON completo.

    Args:
        input_path: Ruta al archivo multimedia.

    Returns:
        Diccionario con la salida JSON de ffprobe.

    Raises:
        ProbeError: Si ffprobe falla o el archivo no existe.
    """
    if not input_path.exists():
        raise ProbeError(str(input_path), "el archivo no existe")

    ffprobe = get_ffprobe()
    cmd = [
        str(ffprobe),
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(input_path),
    ]

    logger.debug("Ejecutando: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeError(str(input_path), "ffprobe tardó demasiado (timeout 60s)") from exc
    except FileNotFoundError as exc:
        raise ProbeError(str(input_path), "ffprobe no encontrado") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise ProbeError(str(input_path), stderr or f"código de salida {result.returncode}")

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ProbeError(str(input_path), f"JSON inválido de ffprobe: {exc}") from exc


def _parse_float(value: str | None, default: float = 0.0) -> float:
    """Parsea un string a float de forma segura."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def _parse_int(value: str | int | None, default: int = 0) -> int:
    """Parsea un string/int a int de forma segura."""
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _parse_fps(stream: dict) -> float:
    """Extrae FPS de un stream de video."""
    # Intentar r_frame_rate primero (más preciso)
    r_frame_rate = stream.get("r_frame_rate", "")
    if r_frame_rate and "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        try:
            num_f, den_f = float(num), float(den)
            if den_f > 0:
                return round(num_f / den_f, 3)
        except ValueError:
            pass

    # Fallback a avg_frame_rate
    avg_frame_rate = stream.get("avg_frame_rate", "")
    if avg_frame_rate and "/" in avg_frame_rate:
        num, den = avg_frame_rate.split("/")
        try:
            num_f, den_f = float(num), float(den)
            if den_f > 0:
                return round(num_f / den_f, 3)
        except ValueError:
            pass

    return 0.0


def _is_disposition_set(stream: dict, key: str) -> bool:
    """Verifica si una disposición está activa en el stream."""
    disposition = stream.get("disposition", {})
    return bool(disposition.get(key, 0))


def scan(input_path: Path) -> MediaInfo:
    """Analiza un archivo multimedia y devuelve información estructurada.

    Args:
        input_path: Ruta al archivo MKV (o cualquier contenedor soportado).

    Returns:
        MediaInfo con todos los streams detectados.

    Raises:
        ProbeError: Si el análisis falla.
    """
    data = probe(input_path)

    # Formato general
    fmt = data.get("format", {})
    format_name = fmt.get("format_name", "unknown")
    duration = _parse_float(fmt.get("duration"))
    size = _parse_int(fmt.get("size"))

    # Parsear streams
    video: VideoStream | None = None
    audio_tracks: list[AudioStream] = []
    subtitle_tracks: list[SubtitleStream] = []

    audio_index = 0
    subtitle_index = 0

    for stream in data.get("streams", []):
        codec_type = stream.get("codec_type", "")
        codec_name = stream.get("codec_name", "unknown")
        stream_idx = _parse_int(stream.get("index"))
        tags = stream.get("tags", {})

        if codec_type == "video" and video is None:
            # Ignorar streams de video que son imágenes adjuntas (posters, etc.)
            if stream.get("disposition", {}).get("attached_pic", 0):
                continue

            video = VideoStream(
                index=0,
                codec=codec_name,
                width=_parse_int(stream.get("width")),
                height=_parse_int(stream.get("height")),
                fps=_parse_fps(stream),
                duration=_parse_float(stream.get("duration", fmt.get("duration"))),
                bitrate=_parse_int(stream.get("bit_rate")) or None,
                pix_fmt=stream.get("pix_fmt"),
            )

        elif codec_type == "audio":
            language = tags.get("language", f"und")
            title = tags.get("title")

            audio_tracks.append(AudioStream(
                index=audio_index,
                stream_index=stream_idx,
                codec=codec_name,
                language=language,
                channels=_parse_int(stream.get("channels"), default=2),
                bitrate=_parse_int(stream.get("bit_rate")) or None,
                title=title,
                is_default=_is_disposition_set(stream, "default"),
            ))
            audio_index += 1

        elif codec_type == "subtitle":
            language = tags.get("language", "und")
            title = tags.get("title")
            is_bitmap = codec_name.lower() in BITMAP_SUBTITLE_CODECS

            subtitle_tracks.append(SubtitleStream(
                index=subtitle_index,
                stream_index=stream_idx,
                codec=codec_name,
                language=language,
                title=title,
                is_bitmap=is_bitmap,
                is_default=_is_disposition_set(stream, "default"),
                is_forced=_is_disposition_set(stream, "forced"),
            ))
            subtitle_index += 1

    info = MediaInfo(
        path=input_path,
        format_name=format_name,
        duration=duration,
        size=size,
        video=video,
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
    )

    logger.info("Escaneado: %s", input_path.name)
    logger.debug("%s", info.summary())
    return info
