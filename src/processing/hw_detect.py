from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass

from src.core.models import HWAccel
from src.utils.platform import get_ffmpeg, current_os

logger = logging.getLogger("makave")


@dataclass(frozen=True)
class EncoderInfo:
    """Información del encoder seleccionado."""
    name: str           # e.g. "h264_nvenc", "libx264"
    is_hardware: bool
    preset_arg: str     # Nombre del preset apropiado para este encoder
    extra_args: list[str]  # Argumentos adicionales específicos del encoder


# Mapeo de encoders por plataforma
_PLATFORM_ENCODERS: dict[str, list[tuple[HWAccel, str]]] = {
    "windows": [
        (HWAccel.NVENC, "h264_nvenc"),
        (HWAccel.QSV, "h264_qsv"),
    ],
    "linux": [
        (HWAccel.NVENC, "h264_nvenc"),
        (HWAccel.QSV, "h264_qsv"),
    ],
    "darwin": [
        (HWAccel.VIDEOTOOLBOX, "h264_videotoolbox"),
    ],
}

# Argumentos extra por encoder
_ENCODER_EXTRA_ARGS: dict[str, list[str]] = {
    "h264_nvenc": ["-rc", "vbr", "-rc-lookahead", "32"],
    "h264_qsv": ["-look_ahead", "1"],
    "h264_videotoolbox": ["-realtime", "false", "-allow_sw", "true"],
    "libx264": [],
}

# Presets válidos por encoder
_ENCODER_PRESETS: dict[str, dict[str, str]] = {
    "h264_nvenc": {
        "slow": "p7",
        "medium": "p4",
        "fast": "p1",
    },
    "h264_qsv": {
        "slow": "veryslow",
        "medium": "medium",
        "fast": "veryfast",
    },
    "h264_videotoolbox": {
        # VideoToolbox no usa preset de la misma manera
        "slow": "slow",
        "medium": "medium",
        "fast": "fast",
    },
    "libx264": {
        "slow": "slow",
        "medium": "medium",
        "fast": "fast",
    },
}


def _test_encoder(encoder_name: str) -> bool:
    """Prueba si un encoder está disponible ejecutando una codificación mínima.

    Genera 0.1 segundos de video negro y lo codifica con el encoder.
    Si el proceso termina sin error, el encoder está disponible.
    """
    try:
        ffmpeg = get_ffmpeg()
        cmd = [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "nullsrc=s=256x256:d=0.1",
            "-c:v", encoder_name,
            "-f", "null",
            "-",
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=15,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def detect_encoder(accel_mode: HWAccel, preset: str = "slow") -> EncoderInfo:
    """Detecta el mejor encoder disponible según el modo de aceleración.

    Args:
        accel_mode: Modo de aceleración solicitado.
        preset: Preset de velocidad/calidad.

    Returns:
        EncoderInfo con el encoder seleccionado.
    """
    if accel_mode == HWAccel.CPU:
        logger.info("Usando encoder por software: [info]libx264[/info]", extra={"markup": True})
        return _build_encoder_info("libx264", preset)

    if accel_mode == HWAccel.AUTO:
        return _auto_detect(preset)

    # Modo específico solicitado
    encoder_name = _accel_to_encoder(accel_mode)
    if encoder_name and _test_encoder(encoder_name):
        logger.info(
            "Encoder HW disponible: [success]%s[/success]",
            encoder_name,
            extra={"markup": True},
        )
        return _build_encoder_info(encoder_name, preset)

    # Fallback
    logger.warning(
        "Encoder '%s' no disponible, usando fallback: [info]libx264[/info]",
        encoder_name or accel_mode.value,
        extra={"markup": True},
    )
    return _build_encoder_info("libx264", preset)


def _auto_detect(preset: str) -> EncoderInfo:
    """Detecta automáticamente el mejor encoder disponible."""
    os_name = current_os()
    candidates = _PLATFORM_ENCODERS.get(os_name, [])

    for _, encoder_name in candidates:
        logger.debug("Probando encoder: %s", encoder_name)
        if _test_encoder(encoder_name):
            logger.info(
                "Encoder HW detectado: [success]%s[/success]",
                encoder_name,
                extra={"markup": True},
            )
            return _build_encoder_info(encoder_name, preset)

    logger.info("No se detectó aceleración HW, usando: [info]libx264[/info]", extra={"markup": True})
    return _build_encoder_info("libx264", preset)


def _accel_to_encoder(accel: HWAccel) -> str | None:
    """Mapea un modo de aceleración al nombre del encoder ffmpeg."""
    mapping = {
        HWAccel.NVENC: "h264_nvenc",
        HWAccel.QSV: "h264_qsv",
        HWAccel.VIDEOTOOLBOX: "h264_videotoolbox",
    }
    return mapping.get(accel)


def _build_encoder_info(encoder_name: str, preset: str) -> EncoderInfo:
    """Construye un EncoderInfo para el encoder dado."""
    presets = _ENCODER_PRESETS.get(encoder_name, {})
    mapped_preset = presets.get(preset, preset)
    extra = list(_ENCODER_EXTRA_ARGS.get(encoder_name, []))

    return EncoderInfo(
        name=encoder_name,
        is_hardware=encoder_name != "libx264",
        preset_arg=mapped_preset,
        extra_args=extra,
    )
