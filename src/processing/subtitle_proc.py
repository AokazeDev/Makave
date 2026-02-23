from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.core.exceptions import SubtitleError
from src.core.models import (
    MediaInfo,
    SubsMode,
    SubtitleStream,
    TranscoderConfig,
)
from src.utils.platform import get_ffmpeg

logger = logging.getLogger("makave")


def _extension_for_codec(codec: str) -> str:
    """Devuelve la extensión de archivo para un codec de subtítulos."""
    mapping = {
        "subrip": "srt",
        "srt": "srt",
        "ass": "ass",
        "ssa": "ssa",
        "webvtt": "vtt",
        "mov_text": "srt",
        "text": "txt",
        "ttml": "ttml",
        # Bitmap
        "hdmv_pgs_subtitle": "sup",
        "pgssub": "sup",
        "dvd_subtitle": "sub",
        "dvdsub": "sub",
        "dvb_subtitle": "sub",
        "dvbsub": "sub",
    }
    return mapping.get(codec.lower(), "sub")


def _run_ffmpeg(cmd: list[str], description: str) -> None:
    """Ejecuta un comando ffmpeg auxiliar.

    Raises:
        SubtitleError: Si el comando falla.
    """
    logger.debug("Ejecutando: %s", " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubtitleError(description, "timeout de 120s") from exc
    except FileNotFoundError as exc:
        raise SubtitleError(description, "ffmpeg no encontrado") from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()[-500:]
        raise SubtitleError(description, stderr or f"código de salida {result.returncode}")


def extract_subtitle(
    input_path: Path,
    track: SubtitleStream,
    output_path: Path,
) -> Path:
    """Extrae un track de subtítulos como archivo sidecar.

    Args:
        input_path: Archivo fuente.
        track: Stream de subtítulos a extraer.
        output_path: Ruta de salida (sin extensión).

    Returns:
        Ruta al archivo extraído.
    """
    ext = _extension_for_codec(track.codec)
    out_file = output_path.with_suffix(f".{ext}")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg()
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i", str(input_path),
        "-map", f"0:s:{track.index}",
        "-c:s", "copy",
        str(out_file),
    ]

    _run_ffmpeg(cmd, f"extraer subtítulo #{track.index} ({track.language})")
    logger.info("Subtítulo extraído: %s", out_file.name)
    return out_file


def convert_subtitle_to_vtt(
    input_path: Path,
    track: SubtitleStream,
    output_path: Path,
) -> Path:
    """Convierte un track de subtítulos de texto a WebVTT.

    Args:
        input_path: Archivo fuente.
        track: Stream de subtítulos a convertir.
        output_path: Ruta de salida (sin extensión, se añade .vtt).

    Returns:
        Ruta al archivo VTT generado.

    Raises:
        SubtitleError: Si el subtítulo es bitmap (no convertible sin OCR).
    """
    if track.is_bitmap:
        raise SubtitleError(
            f"subtítulo #{track.index} ({track.codec})",
            "los subtítulos bitmap (PGS/VOBSUB) no se pueden convertir a WebVTT sin OCR",
        )

    out_file = output_path.with_suffix(".vtt")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = get_ffmpeg()
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i", str(input_path),
        "-map", f"0:s:{track.index}",
        "-c:s", "webvtt",
        str(out_file),
    ]

    _run_ffmpeg(cmd, f"convertir subtítulo #{track.index} a WebVTT")
    logger.info("Subtítulo convertido a VTT: %s", out_file.name)
    return out_file


def segment_vtt_for_hls(
    vtt_path: Path,
    output_dir: Path,
    hls_time: int = 10,
) -> Path:
    """Segmenta un archivo VTT para HLS, generando una playlist .m3u8.

    Args:
        vtt_path: Ruta al archivo WebVTT.
        output_dir: Directorio de salida para los segmentos.
        hls_time: Duración de cada segmento (segundos).

    Returns:
        Ruta a la playlist de subtítulos generada.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    playlist = output_dir / "prog.m3u8"

    ffmpeg = get_ffmpeg()
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i", str(vtt_path),
        "-c:s", "copy",
        "-f", "segment",
        "-segment_time", str(hls_time),
        "-segment_list", str(playlist),
        "-segment_format", "webvtt",
        str(output_dir / "seg_%03d.vtt"),
    ]

    _run_ffmpeg(cmd, f"segmentar VTT: {vtt_path.name}")
    logger.info("Subtítulos segmentados: %s", output_dir.name)
    return playlist


def process_subtitles(
    config: TranscoderConfig,
    media: MediaInfo,
    output_dir: Path,
) -> list[dict]:
    """Procesa todos los subtítulos según el modo configurado.

    Args:
        config: Configuración del transcoder.
        media: Información del archivo fuente.
        output_dir: Directorio de salida.

    Returns:
        Lista de diccionarios con info de los subtítulos procesados:
        [{"language": "en", "name": "English", "uri": "sub_en/prog.m3u8", "forced": False}]
    """
    if config.subs_mode == SubsMode.KEEP:
        logger.info("Modo subtítulos: keep → no se procesan")
        return []

    if not media.subtitle_tracks:
        logger.info("No se encontraron tracks de subtítulos")
        return []

    subs_dir = output_dir / "subs"
    subs_dir.mkdir(parents=True, exist_ok=True)
    processed: list[dict] = []

    for track in media.subtitle_tracks:
        lang = track.language or "und"
        label = track.title or lang.upper()
        sub_name = f"sub_{lang}_{track.index}"
        sub_output = subs_dir / sub_name

        if config.subs_mode == SubsMode.EXTRACT:
            # Extraer como sidecar
            try:
                extract_subtitle(media.path, track, sub_output / lang)
                logger.info(
                    "Subtítulo extraído [%s]: %s (%s)",
                    lang, label, track.codec,
                )
            except SubtitleError as exc:
                logger.warning("No se pudo extraer subtítulo #%d: %s", track.index, exc)

        elif config.subs_mode == SubsMode.CONVERT:
            # Convertir a WebVTT y segmentar para HLS
            if track.is_bitmap:
                logger.warning(
                    "Subtítulo #%d (%s) es bitmap (%s) → se extrae sin convertir",
                    track.index, lang, track.codec,
                )
                try:
                    extract_subtitle(media.path, track, sub_output / lang)
                except SubtitleError as exc:
                    logger.warning("No se pudo extraer subtítulo bitmap #%d: %s", track.index, exc)
                continue

            try:
                vtt_file = convert_subtitle_to_vtt(media.path, track, sub_output / lang)
                playlist = segment_vtt_for_hls(vtt_file, sub_output, config.hls_time)

                # Ruta relativa para el master.m3u8
                rel_uri = playlist.relative_to(output_dir).as_posix()
                processed.append({
                    "language": lang,
                    "name": label,
                    "uri": rel_uri,
                    "forced": track.is_forced,
                    "default": track.is_default,
                })

            except SubtitleError as exc:
                logger.warning(
                    "No se pudo convertir subtítulo #%d (%s): %s",
                    track.index, lang, exc,
                )

    return processed
