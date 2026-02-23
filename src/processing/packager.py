from __future__ import annotations

import logging
import math
import subprocess
from pathlib import Path

from src.processing.engine import EncodeJob
from src.core.models import MediaInfo, ThumbnailMode
from src.utils.platform import get_ffmpeg

logger = logging.getLogger("makave")

# --- Master Playlist ---


def patch_master_playlist(
    output_dir: Path,
    master_name: str,
    subtitle_entries: list[dict],
) -> None:
    """Añade entradas EXT-X-MEDIA de subtítulos al master.m3u8.

    Lee el master.m3u8 generado por ffmpeg, inserta las líneas de
    subtítulos y agrega SUBTITLES= a cada EXT-X-STREAM-INF.

    Args:
        output_dir: Directorio donde está el master.m3u8.
        master_name: Nombre del archivo master playlist.
        subtitle_entries: Lista de dicts con language, name, uri, forced, default.
    """
    master_path = output_dir / master_name
    if not master_path.exists():
        logger.warning("No se encontró master.m3u8 en %s", output_dir)
        return

    if not subtitle_entries:
        logger.debug("Sin subtítulos para agregar al master playlist")
        return

    content = master_path.read_text(encoding="utf-8").replace('\\', '/')
    lines = content.splitlines()

    # Construir líneas EXT-X-MEDIA para subtítulos
    sub_lines: list[str] = []
    for entry in subtitle_entries:
        default = "YES" if entry.get("default") else "NO"
        forced = "YES" if entry.get("forced") else "NO"
        safe_uri = Path(entry["uri"]).as_posix()
        
        sub_lines.append(
            f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",'
            f'NAME="{entry["name"]}",LANGUAGE="{entry["language"]}",'
            f"DEFAULT={default},FORCED={forced},"
            f'URI="{safe_uri}"'
        )

    # Insertar después de #EXTM3U y #EXT-X-VERSION
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.startswith("#EXTM3U") or line.startswith("#EXT-X-VERSION"):
            insert_idx = i + 1

    for i, sub_line in enumerate(sub_lines):
        lines.insert(insert_idx + i, sub_line)

    # Agregar SUBTITLES="subs" a cada EXT-X-STREAM-INF
    patched: list[str] = []
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:") and 'SUBTITLES=' not in line:
            line = line.rstrip() + ',SUBTITLES="subs"'
        patched.append(line)

    master_path.write_text("\n".join(patched) + "\n", encoding="utf-8")
    logger.info(
        "[success]Master playlist actualizado[/success] con %d pista(s) de subtítulos",
        len(subtitle_entries),
        extra={"markup": True},
    )


# --- Thumbnails ---


def generate_thumbnail_sprite(
    input_path: Path,
    output_dir: Path,
    duration: float,
    interval: int = 10,
    thumb_width: int = 160,
    cols: int = 10,
) -> tuple[Path, Path] | None:
    """Genera un sprite sheet de thumbnails y su archivo VTT.

    Args:
        input_path: Archivo fuente de video.
        output_dir: Directorio de salida.
        duration: Duración del video en segundos.
        interval: Segundos entre cada thumbnail.
        thumb_width: Ancho de cada thumbnail (alto proporcional).
        cols: Columnas por fila en el sprite.

    Returns:
        Tupla (sprite_path, vtt_path) o None si falla.
    """
    if duration <= 0:
        logger.warning("Duración inválida para generar thumbnails")
        return None

    thumbs_dir = output_dir / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)

    total_frames = math.ceil(duration / interval)
    rows = math.ceil(total_frames / cols)

    sprite_path = thumbs_dir / "sprite.jpg"

    # Generar sprite con ffmpeg
    ffmpeg = get_ffmpeg()
    cmd = [
        str(ffmpeg),
        "-hide_banner",
        "-y",
        "-i", str(input_path),
        "-vf", f"fps=1/{interval},scale={thumb_width}:-1,tile={cols}x{rows}",
        "-frames:v", "1",
        "-q:v", "5",
        str(sprite_path),
    ]

    logger.debug("Generando sprite de thumbnails: %s", " ".join(cmd))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("No se pudo generar sprite de thumbnails: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning(
            "ffmpeg falló al generar sprite: %s",
            result.stderr.strip()[-300:],
        )
        return None

    # Calcular dimensiones reales del thumbnail
    # Asumimos ratio 16:9 si no podemos detectar
    thumb_height = round(thumb_width * 9 / 16)

    # Generar archivo VTT
    vtt_path = thumbs_dir / "thumbnails.vtt"
    vtt_lines = ["WEBVTT", ""]

    for i in range(total_frames):
        start_sec = i * interval
        end_sec = min((i + 1) * interval, duration)

        col = i % cols
        row = i // cols

        x = col * thumb_width
        y = row * thumb_height

        start_ts = _seconds_to_vtt_time(start_sec)
        end_ts = _seconds_to_vtt_time(end_sec)

        vtt_lines.append(f"{start_ts} --> {end_ts}")
        vtt_lines.append(f"sprite.jpg#xywh={x},{y},{thumb_width},{thumb_height}")
        vtt_lines.append("")

    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")

    logger.info(
        "[success]Thumbnails generados[/success]: sprite (%dx%d, %d frames) + VTT",
        cols, rows, total_frames,
        extra={"markup": True},
    )
    return sprite_path, vtt_path


def _seconds_to_vtt_time(seconds: float) -> str:
    """Convierte segundos a formato VTT HH:MM:SS.mmm."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


# --- Orquestación ---


def post_process(
    job: EncodeJob,
    media: MediaInfo,
    subtitle_entries: list[dict],
    thumbnail_mode: ThumbnailMode,
) -> None:
    """Ejecuta todo el post-procesamiento tras la codificación.

    Args:
        job: Trabajo de codificación completado.
        media: Info del archivo fuente.
        subtitle_entries: Subtítulos procesados (del subtitle_proc).
        thumbnail_mode: Modo de generación de thumbnails.
    """
    # Parchear master.m3u8 con subtítulos
    if subtitle_entries:
        patch_master_playlist(job.output_dir, job.master_playlist, subtitle_entries)

    # Generar thumbnails
    if thumbnail_mode == ThumbnailMode.SPRITE and media.duration > 0:
        generate_thumbnail_sprite(
            media.path,
            job.output_dir,
            media.duration,
        )
