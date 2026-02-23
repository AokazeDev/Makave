from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from src.core.exceptions import EncodingError
from src.processing.hw_detect import EncoderInfo
from src.core.logger import console
from src.core.models import (
    ENCODING_PROFILES,
    MediaInfo,
    OutputFormat,
    ResolutionPreset,
    TranscoderConfig,
)
from src.utils.platform import get_ffmpeg

logger = logging.getLogger("makave")


@dataclass
class EncodeJob:
    """Resultado de la preparación del comando de codificación."""
    cmd: list[str]
    output_dir: Path
    variant_dirs: list[str]
    presets_used: list[ResolutionPreset]
    master_playlist: str


def get_applicable_presets(
    media: MediaInfo,
    profile: str = "default",
) -> list[ResolutionPreset]:
    """Devuelve los presets aplicables filtrados por resolución fuente.

    No incluye presets con ancho mayor al video fuente (evita upscaling).
    """
    if media.video is None:
        return []

    all_presets = ENCODING_PROFILES.get(profile, ENCODING_PROFILES["default"])
    source_h = media.video.height

    # Filtrar: solo incluir resoluciones <= fuente
    applicable = [p for p in all_presets if p.height <= source_h]

    # Si no hay presets aplicables (fuente muy baja), usar el menor disponible
    if not applicable:
        applicable = [min(all_presets, key=lambda p: p.height)]

    return applicable


def _audio_bitrate_for_channels(channels: int) -> str:
    """Calcula bitrate de audio basado en cantidad de canales."""
    if channels >= 6:
        return "384k"
    if channels > 2:
        return "192k"
    return "128k"


def build_encode_job(
    config: TranscoderConfig,
    media: MediaInfo,
    encoder: EncoderInfo,
    output_dir: Path,
) -> EncodeJob:
    """Construye el comando ffmpeg para codificación HLS one-pass.

    Args:
        config: Configuración del transcoder.
        media: Información del archivo fuente.
        encoder: Encoder seleccionado (puede ser HW o SW).
        output_dir: Directorio de salida para esta codificación.

    Returns:
        EncodeJob con el comando y metadatos del trabajo.
    """
    if media.video is None:
        raise EncodingError(str(media.path), "no se encontró stream de video")

    presets = get_applicable_presets(media, config.profile)
    n_video = len(presets)
    has_audio = len(media.audio_tracks) > 0

    # --- Construir filter_complex ---
    filter_parts: list[str] = []
    map_args: list[str] = []

    # Video: split → scale por cada preset
    if n_video > 1:
        filter_parts.append(f"[0:v]split={n_video}" + "".join(f"[v{i}]" for i in range(n_video)))
        for i, preset in enumerate(presets):
            filter_parts.append(f"[v{i}]scale={preset.width}:-2[v{i}out]")
            map_args.extend(["-map", f"[v{i}out]"])
    else:
        # Un solo preset: escalar directamente
        filter_parts.append(f"[0:v]scale={presets[0].width}:-2[v0out]")
        map_args.extend(["-map", "[v0out]"])

    # Audio: loudnorm si está habilitado
    if has_audio and config.loudnorm:
        for track in media.audio_tracks:
            idx = track.index
            filter_parts.append(
                f"[0:a:{idx}]loudnorm=I=-16:TP=-1.5:LRA=11[a{idx}out]"
            )
            map_args.extend(["-map", f"[a{idx}out]"])
    elif has_audio:
        for track in media.audio_tracks:
            map_args.extend(["-map", f"0:a:{track.index}"])

    filter_complex = ";".join(filter_parts)

    # --- Construir codec args ---
    codec_args: list[str] = []

    # Video codec por variante
    for i, preset in enumerate(presets):
        codec_args.extend([f"-c:v:{i}", encoder.name])
        codec_args.extend([f"-b:v:{i}", preset.video_bitrate])
        if encoder.name == "libx264":
            codec_args.extend([f"-preset:v:{i}", encoder.preset_arg])
        elif encoder.name == "h264_nvenc":
            codec_args.extend([f"-preset:v:{i}", encoder.preset_arg])
        elif encoder.name == "h264_qsv":
            codec_args.extend([f"-preset:v:{i}", encoder.preset_arg])

    # Args extra del encoder (solo una vez)
    codec_args.extend(encoder.extra_args)

    # Flags comunes de video
    codec_args.extend([
        "-g", str(config.hls_time * 2),  # GOP = 2x segmento
        "-keyint_min", str(config.hls_time),
        "-sc_threshold", "0",
        "-pix_fmt", "yuv420p",
    ])

    # Audio codec
    if has_audio:
        codec_args.extend(["-c:a", "aac"])
        # Bitrate por track basado en canales
        for i, track in enumerate(media.audio_tracks):
            abr = _audio_bitrate_for_channels(track.channels)
            codec_args.extend([f"-b:a:{i}", abr])
            codec_args.extend([f"-ac:a:{i}", str(min(track.channels, 2))])

    # --- Construir var_stream_map ---
    vsm_parts: list[str] = []
    variant_dirs: list[str] = []

    for i, preset in enumerate(presets):
        part = f"v:{i}"
        if has_audio:
            part += ",agroup:audio"
        part += f",name:{preset.name}"
        vsm_parts.append(part)
        variant_dirs.append(preset.name)

    if has_audio:
        for track in media.audio_tracks:
            lang = track.language or "und"
            name = f"audio_{lang}_{track.index}"
            part = f"a:{track.index},agroup:audio,language:{lang},name:{name}"
            if track.is_default:
                part += ",default:yes"
            vsm_parts.append(part)
            variant_dirs.append(name)

    var_stream_map = " ".join(vsm_parts)

    # --- HLS args ---
    hls_args: list[str] = [
        "-f", "hls",
        "-hls_time", str(config.hls_time),
        "-hls_playlist_type", "vod",
        "-hls_list_size", "0",
        "-master_pl_name", "master.m3u8",
        "-var_stream_map", var_stream_map,
    ]

    # Formato de segmentos
    if config.output_format == OutputFormat.FMP4:
        hls_args.extend(["-hls_segment_type", "fmp4"])
        seg_ext = "m4s"
        hls_args.extend(["-hls_fmp4_init_filename", "init.mp4"])
    else:
        seg_ext = "ts"

    # Encryption
    if config.encrypt.value != "none" and config.keyfile:
        hls_args.extend(["-hls_key_info_file", str(config.keyfile)])

    hls_args.extend([
        "-hls_segment_filename", str(output_dir / "%v" / f"seg_%03d.{seg_ext}"),
    ])

    # --- Pre-crear directorios de variantes ---
    for vdir in variant_dirs:
        (output_dir / vdir).mkdir(parents=True, exist_ok=True)

    # --- Comando final ---
    ffmpeg = get_ffmpeg()
    cmd: list[str] = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i", str(media.path),
        "-filter_complex", filter_complex,
    ]
    cmd.extend(map_args)
    cmd.extend(codec_args)
    cmd.extend(["-map_metadata", "-1"])
    cmd.extend(["-movflags", "+faststart"])
    cmd.extend(hls_args)

    # Progreso machine-readable
    cmd.extend(["-progress", "pipe:1"])

    # Output path pattern (una playlist por variante)
    cmd.append(str(output_dir / "%v" / "prog.m3u8"))

    return EncodeJob(
        cmd=cmd,
        output_dir=output_dir,
        variant_dirs=variant_dirs,
        presets_used=presets,
        master_playlist="master.m3u8",
    )


# Regex para parsear out_time del progreso de ffmpeg
_TIME_RE = re.compile(r"out_time=\s*(\d+):(\d+):(\d+)\.(\d+)")
_PROGRESS_RE = re.compile(r"progress=(\w+)")


def _parse_progress_time(line: str) -> float | None:
    """Extrae el tiempo actual del progreso de ffmpeg (en segundos)."""
    match = _TIME_RE.search(line)
    if match:
        h, m, s, us = match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s) + int(us) / 1_000_000
    return None


def run_encode(
    job: EncodeJob,
    duration: float,
    log_file: Path | None = None,
) -> None:
    """Ejecuta el comando ffmpeg con barra de progreso en la consola.

    Args:
        job: Trabajo de codificación preparado.
        duration: Duración total del archivo fuente (segundos).
        log_file: Ruta opcional para guardar stderr de ffmpeg.

    Raises:
        EncodingError: Si ffmpeg termina con error.
    """
    logger.debug("Comando ffmpeg: %s", " ".join(job.cmd))

    stderr_file: IO[str] | None = None
    try:
        if log_file:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            stderr_file = open(log_file, "w", encoding="utf-8")  # noqa: SIM115

        process = subprocess.Popen(
            job.cmd,
            stdout=subprocess.PIPE,
            stderr=stderr_file or subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Codificando...", total=max(duration, 1.0))
            current_time = 0.0
            finished = False

            assert process.stdout is not None
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue

                time_val = _parse_progress_time(line)
                if time_val is not None:
                    current_time = time_val
                    progress.update(task, completed=min(current_time, duration))

                progress_match = _PROGRESS_RE.search(line)
                if progress_match and progress_match.group(1) == "end":
                    finished = True

            # Asegurar que la barra llega al 100%
            if finished:
                progress.update(task, completed=duration)

        returncode = process.wait()

        if returncode != 0:
            # Leer stderr para el mensaje de error
            stderr_text = ""
            if process.stderr:
                stderr_text = process.stderr.read()
            elif log_file and log_file.exists():
                stderr_text = log_file.read_text(encoding="utf-8")[-2000:]

            raise EncodingError(
                str(job.output_dir),
                f"ffmpeg terminó con código {returncode}\n{stderr_text}",
            )

        logger.info(
            "[success]Codificación completada[/success] → %s",
            job.output_dir,
            extra={"markup": True},
        )

    finally:
        if stderr_file:
            stderr_file.close()
