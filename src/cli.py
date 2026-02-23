from __future__ import annotations

import argparse
from pathlib import Path

from src import __version__
from src.core.models import (
    EncryptionMode,
    HWAccel,
    OutputFormat,
    SubsMode,
    ThumbnailMode,
    TranscoderConfig,
)


def build_parser() -> argparse.ArgumentParser:
    """Construye el parser de argumentos CLI."""
    parser = argparse.ArgumentParser(
        prog="makave",
        description="Makave MKV → HLS multi-rendición con soporte de hardware.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  makave video.mkv\n"
            "  makave *.mkv -o ./output --profile action\n"
            "  makave -i video.mkv --subs-mode extract --hw-accel nvenc\n"
            "  makave ./videos/ --loudnorm off --thumbnail sprite\n"
        ),
    )

    parser.add_argument(
        "input",
        nargs="*",
        type=Path,
        help="Archivos MKV o directorio con archivos MKV.",
    )
    parser.add_argument(
        "-i", "--input-file",
        action="append",
        type=Path,
        dest="input_files",
        default=[],
        help="Archivo MKV adicional (se puede repetir).",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=Path("./output"),
        help="Directorio base de salida (default: ./output).",
    )
    parser.add_argument(
        "--subs-mode",
        choices=[m.value for m in SubsMode],
        default=SubsMode.CONVERT.value,
        help="Modo de subtítulos: convert (WebVTT+HLS), extract (sidecar), keep (ignorar). Default: convert.",
    )
    parser.add_argument(
        "--hw-accel",
        choices=[h.value for h in HWAccel],
        default=HWAccel.AUTO.value,
        help="Aceleración por hardware: auto, nvenc, qsv, videotoolbox, cpu. Default: auto.",
    )
    parser.add_argument(
        "--output-format",
        choices=[f.value for f in OutputFormat],
        default=OutputFormat.TS.value,
        help="Formato de segmentos HLS: ts o fmp4. Default: ts.",
    )
    parser.add_argument(
        "--loudnorm",
        choices=["on", "off"],
        default="on",
        help="Normalización EBU R128: on u off. Default: on.",
    )
    parser.add_argument(
        "--encrypt",
        choices=[e.value for e in EncryptionMode],
        default=EncryptionMode.NONE.value,
        help="Encriptación HLS: none o aes-128. Default: none.",
    )
    parser.add_argument(
        "--thumbnail",
        choices=[t.value for t in ThumbnailMode],
        default=ThumbnailMode.NONE.value,
        help="Generación de thumbnails: none o sprite. Default: none.",
    )
    parser.add_argument(
        "--profile",
        choices=["default", "action", "animation", "low"],
        default="default",
        help="Perfil de codificación (bitrates). Default: default.",
    )
    parser.add_argument(
        "--hls-time",
        type=int,
        default=10,
        metavar="SEG",
        help="Duración de segmentos HLS en segundos. Default: 10.",
    )
    parser.add_argument(
        "--delete-source",
        action="store_true",
        help="Eliminar el archivo MKV original tras la conversión exitosa.",
    )
    parser.add_argument(
        "--preset",
        default="slow",
        metavar="PRESET",
        help="Preset de velocidad/calidad de ffmpeg (slow, medium, fast). Default: slow.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        metavar="PATH",
        help="Ruta del archivo de log (default: output_dir/transcode.log).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Salida detallada (nivel DEBUG).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    return parser


def _collect_input_paths(args: argparse.Namespace) -> list[Path]:
    """Recolecta y valida todas las rutas de entrada.

    Combina argumentos posicionales y --input-file.
    Expande directorios a archivos .mkv contenidos.
    """
    raw_paths: list[Path] = list(args.input or []) + list(args.input_files or [])

    if not raw_paths:
        return []

    resolved: list[Path] = []
    for p in raw_paths:
        p = p.resolve()
        if p.is_dir():
            mkv_files = sorted(p.glob("*.mkv"))
            if not mkv_files:
                mkv_files = sorted(p.glob("*.MKV"))
            resolved.extend(mkv_files)
        elif p.is_file():
            resolved.append(p)
        else:
            parent = p.parent
            if parent.exists():
                matches = sorted(parent.glob(p.name))
                resolved.extend(matches)

    # Elimina duplicados preservando orden
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in resolved:
        if p not in seen:
            seen.add(p)
            unique.append(p)

    return unique


def parse_args(argv: list[str] | None = None) -> TranscoderConfig:
    """Parsea argumentos CLI y construye la configuración.

    Args:
        argv: Lista de argumentos (default: sys.argv[1:]).

    Returns:
        TranscoderConfig validada.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    input_paths = _collect_input_paths(args)

    if not input_paths:
        parser.error(
            "No se proporcionaron archivos de entrada.\n"
            "Uso: mkv-to-hls video.mkv [video2.mkv ...]\n"
            "     mkv-to-hls ./directorio/"
        )

    # Validar que existen
    missing = [p for p in input_paths if not p.exists()]
    if missing:
        parser.error(f"Archivo(s) no encontrado(s): {', '.join(str(m) for m in missing)}")

    return TranscoderConfig(
        input_paths=input_paths,
        output_dir=args.output_dir.resolve(),
        subs_mode=SubsMode(args.subs_mode),
        hw_accel=HWAccel(args.hw_accel),
        output_format=OutputFormat(args.output_format),
        loudnorm=args.loudnorm == "on",
        encrypt=EncryptionMode(args.encrypt),
        thumbnail=ThumbnailMode(args.thumbnail),
        profile=args.profile,
        hls_time=args.hls_time,
        delete_source=args.delete_source,
        preset=args.preset,
        log_file=args.log_file,
    )
