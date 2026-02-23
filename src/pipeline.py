from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from src import __version__
from src.processing.engine import build_encode_job, run_encode
from src.core.exceptions import TranscoderError
from src.processing.hw_detect import detect_encoder
from src.core.logger import console, setup_logging
from src.core.models import EncryptionMode, MediaInfo, TranscoderConfig
from src.processing.packager import post_process
from src.processing.scanner import scan
from src.processing.subtitle_proc import process_subtitles
from src.utils.crypto import setup_encryption
from src.utils.platform import safe_filename

logger = logging.getLogger("makave")


def _print_banner() -> None:
    """Muestra el banner de inicio."""
    console.print(
        Panel(
            f"[bold]Makave Transcoder[/bold]  v{__version__}",
            border_style="blue",
            padding=(0, 2),
        )
    )


def _print_media_table(media: MediaInfo) -> None:
    """Imprime una tabla con la información del archivo multimedia."""
    table = Table(title=f"[filename]{media.path.name}[/filename]", show_header=False)
    table.add_column("Campo", style="bold")
    table.add_column("Valor")

    if media.video:
        table.add_row(
            "Video",
            f"{media.video.codec}  {media.video.width}×{media.video.height}  "
            f"@ {media.video.fps:.2f} fps",
        )

    for a in media.audio_tracks:
        label = a.title or a.language
        default = " ★" if a.is_default else ""
        table.add_row(
            f"Audio #{a.index}",
            f"{a.codec}  {a.channels}ch  [{label}]{default}",
        )

    for s in media.subtitle_tracks:
        kind = "bitmap" if s.is_bitmap else "texto"
        label = s.title or s.language
        forced = " [forced]" if s.is_forced else ""
        table.add_row(
            f"Sub #{s.index}",
            f"{s.codec} ({kind})  [{label}]{forced}",
        )

    mins, secs = divmod(media.duration, 60)
    hours, mins = divmod(mins, 60)
    table.add_row("Duración", f"{int(hours):02d}:{int(mins):02d}:{secs:05.2f}")
    table.add_row("Tamaño", f"{media.size / (1024 * 1024):.1f} MB")

    console.print(table)


def _print_summary(results: list[dict]) -> None:
    """Muestra un resumen final de los resultados."""
    table = Table(title="Resumen", show_header=True)
    table.add_column("Archivo", style="filename")
    table.add_column("Estado")
    table.add_column("Tiempo")
    table.add_column("Salida")

    for r in results:
        status = "[success]✓ OK[/success]" if r["ok"] else "[error]✗ ERROR[/error]"
        elapsed = f"{r['elapsed']:.1f}s" if r.get("elapsed") else "—"
        output = str(r.get("output_dir", "—"))
        table.add_row(r["name"], status, elapsed, output)

    console.print(table)

    ok_count = sum(1 for r in results if r["ok"])
    fail_count = len(results) - ok_count
    total_time = sum(r.get("elapsed", 0) for r in results)

    if fail_count == 0:
        console.print(
            f"\n[success]Todo listo.[/success] {ok_count} archivo(s) procesado(s) "
            f"en {total_time:.1f}s.",
            highlight=False,
        )
    else:
        console.print(
            f"\n[warning]{ok_count} exitoso(s), {fail_count} con error(es)[/warning] "
            f"en {total_time:.1f}s.",
            highlight=False,
        )


def _process_single_file(
    input_path: Path,
    config: TranscoderConfig,
    encoder_name: str | None = None,
) -> dict:
    """Procesa un solo archivo MKV.

    Returns:
        Diccionario con resultado: name, ok, elapsed, output_dir, error.
    """
    start = time.monotonic()
    name = input_path.name
    result: dict = {"name": name, "ok": False, "elapsed": 0.0}

    try:
        # 1. Escanear archivo
        console.rule(f"[bold]{name}[/bold]")
        media = scan(input_path)
        _print_media_table(media)

        if media.video is None:
            logger.error("No se encontró stream de video en %s, saltando", name)
            result["error"] = "sin video"
            return result

        # 2. Determinar directorio de salida
        stem = safe_filename(input_path.stem)
        output_dir = config.output_dir / stem
        output_dir.mkdir(parents=True, exist_ok=True)
        result["output_dir"] = output_dir

        # 3. Detectar encoder (reutilizar si ya se detectó)
        encoder = detect_encoder(config.hw_accel, config.preset)

        # 4. Encryption setup
        keyfile = config.keyfile
        if config.encrypt == EncryptionMode.AES128 and keyfile is None:
            key_dir = output_dir / ".keys"
            keyfile = setup_encryption(key_dir)
            logger.info("Cifrado AES-128 configurado")

        # Crear config temporal con keyfile resuelto
        encode_config = TranscoderConfig(
            input_paths=config.input_paths,
            output_dir=config.output_dir,
            subs_mode=config.subs_mode,
            hw_accel=config.hw_accel,
            output_format=config.output_format,
            loudnorm=config.loudnorm,
            encrypt=config.encrypt,
            keyfile=keyfile,
            thumbnail=config.thumbnail,
            profile=config.profile,
            hls_time=config.hls_time,
            delete_source=config.delete_source,
            preset=config.preset,
            log_file=config.log_file,
        )

        # 5. Construir y ejecutar codificación
        job = build_encode_job(encode_config, media, encoder, output_dir)

        console.print(
            f"\n  Encoder: [info]{encoder.name}[/info]  "
            f"Presets: [info]{', '.join(p.name for p in job.presets_used)}[/info]  "
            f"Formato: [info]{config.output_format.value}[/info]",
            highlight=False,
        )
        console.print()

        ffmpeg_log = output_dir / "ffmpeg.log"
        run_encode(job, media.duration, log_file=ffmpeg_log)

        # 6. Procesar subtítulos
        sub_entries = process_subtitles(encode_config, media, output_dir)

        # 7. Post-procesamiento (master.m3u8 + thumbnails)
        post_process(job, media, sub_entries, config.thumbnail)

        # 8. Eliminar fuente si se solicitó
        if config.delete_source:
            input_path.unlink()
            logger.info("Archivo fuente eliminado: %s", name)

        result["ok"] = True

    except TranscoderError as exc:
        logger.error("[error]%s[/error]: %s", name, exc, extra={"markup": True})
        result["error"] = str(exc)

    except KeyboardInterrupt:
        logger.warning("Interrumpido por el usuario")
        result["error"] = "interrumpido"
        raise

    except Exception as exc:
        logger.exception("Error inesperado procesando %s", name)
        result["error"] = str(exc)

    finally:
        result["elapsed"] = time.monotonic() - start

    return result


def run(config: TranscoderConfig) -> None:
    """Ejecuta el pipeline completo de transcodificación.

    Args:
        config: Configuración parseada desde CLI.
    """
    # Configurar logging
    log_file = config.log_file or config.output_dir / "transcode.log"
    verbose = logger.isEnabledFor(logging.DEBUG)
    setup_logging(log_file=log_file, verbose=verbose)

    _print_banner()

    # Mostrar configuración
    console.print(f"  Archivos: [info]{len(config.input_paths)}[/info]", highlight=False)
    console.print(f"  Perfil: [info]{config.profile}[/info]", highlight=False)
    console.print(f"  Subtítulos: [info]{config.subs_mode.value}[/info]", highlight=False)
    console.print(f"  Loudnorm: [info]{'sí' if config.loudnorm else 'no'}[/info]", highlight=False)
    console.print(f"  Cifrado: [info]{config.encrypt.value}[/info]", highlight=False)
    console.print(f"  Salida: [filename]{config.output_dir}[/filename]", highlight=False)
    console.print()

    # Procesar cada archivo
    results: list[dict] = []

    try:
        for i, input_path in enumerate(config.input_paths, 1):
            if len(config.input_paths) > 1:
                console.print(
                    f"\n[bold]({i}/{len(config.input_paths)})[/bold]",
                    highlight=False,
                )
            result = _process_single_file(input_path, config)
            results.append(result)

    except KeyboardInterrupt:
        console.print("\n[warning]Proceso interrumpido por el usuario.[/warning]")

    # Resumen final
    if results:
        console.print()
        _print_summary(results)

    # Exit code basado en resultados
    if any(not r["ok"] for r in results):
        sys.exit(1)
