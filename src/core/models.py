from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


# Enums de configuración

class SubsMode(Enum):
    """Modo de procesamiento de subtítulos."""
    CONVERT = "convert"
    EXTRACT = "extract"
    KEEP = "keep"


class HWAccel(Enum):
    """Modo de aceleración por hardware."""
    AUTO = "auto"
    NVENC = "nvenc"
    QSV = "qsv"
    VIDEOTOOLBOX = "videotoolbox"
    CPU = "cpu"


class OutputFormat(Enum):
    """Formato de segmentos HLS."""
    TS = "ts"
    FMP4 = "fmp4"


class EncryptionMode(Enum):
    """Modo de cifrado HLS."""
    NONE = "none"
    AES128 = "aes-128"


class ThumbnailMode(Enum):
    """Modo de generación de thumbnails."""
    NONE = "none"
    SPRITE = "sprite"


# Constantes de codecs de subtítulos

BITMAP_SUBTITLE_CODECS: frozenset[str] = frozenset({
    "hdmv_pgs_subtitle",
    "pgssub",
    "dvd_subtitle",
    "dvdsub",
    "dvb_subtitle",
    "dvbsub",
    "xsub",
})

TEXT_SUBTITLE_CODECS: frozenset[str] = frozenset({
    "subrip",
    "srt",
    "ass",
    "ssa",
    "webvtt",
    "mov_text",
    "text",
    "ttml",
})

# Extensiones de archivo para cada codec de subtítulos
SUBTITLE_EXTENSIONS: dict[str, str] = {
    "subrip": ".srt",
    "srt": ".srt",
    "ass": ".ass",
    "ssa": ".ssa",
    "webvtt": ".vtt",
    "mov_text": ".srt",
    "text": ".srt",
    "ttml": ".ttml",
    "hdmv_pgs_subtitle": ".sup",
    "pgssub": ".sup",
    "dvd_subtitle": ".sub",
    "dvdsub": ".sub",
    "dvb_subtitle": ".sub",
    "dvbsub": ".sub",
}


# Modelos de media

@dataclass(frozen=True)
class VideoStream:
    """Stream de video del archivo fuente."""
    index: int
    codec: str
    width: int
    height: int
    fps: float
    duration: float
    bitrate: int | None = None
    pix_fmt: str | None = None


@dataclass(frozen=True)
class AudioStream:
    """Stream de audio del archivo fuente."""
    index: int
    stream_index: int
    codec: str
    language: str
    channels: int
    bitrate: int | None = None
    title: str | None = None
    is_default: bool = False


@dataclass(frozen=True)
class SubtitleStream:
    """Stream de subtítulos del archivo fuente."""
    index: int
    stream_index: int
    codec: str
    language: str
    title: str | None = None
    is_bitmap: bool = False
    is_default: bool = False
    is_forced: bool = False


@dataclass(frozen=True)
class MediaInfo:
    """Análisis completo de un archivo multimedia."""
    path: Path
    format_name: str
    duration: float
    size: int
    video: VideoStream | None
    audio_tracks: list[AudioStream]
    subtitle_tracks: list[SubtitleStream]

    def summary(self) -> str:
        """Resumen legible del archivo."""
        parts = [f"Archivo: {self.path.name}"]
        if self.video:
            parts.append(
                f"  Video: {self.video.codec} {self.video.width}x{self.video.height} "
                f"@ {self.video.fps:.2f} fps"
            )
        for a in self.audio_tracks:
            label = a.title or a.language
            parts.append(f"  Audio #{a.index}: {a.codec} {a.channels}ch [{label}]")
        for s in self.subtitle_tracks:
            kind = "bitmap" if s.is_bitmap else "texto"
            label = s.title or s.language
            parts.append(f"  Sub #{s.index}: {s.codec} ({kind}) [{label}]")
        mins, secs = divmod(self.duration, 60)
        hours, mins = divmod(mins, 60)
        parts.append(f"  Duración: {int(hours):02d}:{int(mins):02d}:{secs:05.2f}")
        parts.append(f"  Tamaño: {self.size / (1024 * 1024):.1f} MB")
        return "\n".join(parts)


# Perfiles de resolución y codificación

@dataclass(frozen=True)
class ResolutionPreset:
    """Preset de resolución y bitrate."""
    name: str
    width: int
    height: int
    video_bitrate: str
    audio_bitrate: str


ENCODING_PROFILES: dict[str, list[ResolutionPreset]] = {
    "default": [
        ResolutionPreset("1080p", 1920, 1080, "5000k", "128k"),
        ResolutionPreset("720p", 1280, 720, "3000k", "128k"),
        ResolutionPreset("480p", 854, 480, "1500k", "96k"),
    ],
    "action": [
        ResolutionPreset("1080p", 1920, 1080, "8000k", "192k"),
        ResolutionPreset("720p", 1280, 720, "5000k", "128k"),
        ResolutionPreset("480p", 854, 480, "2500k", "96k"),
    ],
    "animation": [
        ResolutionPreset("1080p", 1920, 1080, "4000k", "128k"),
        ResolutionPreset("720p", 1280, 720, "2500k", "128k"),
        ResolutionPreset("480p", 854, 480, "1200k", "96k"),
    ],
    "low": [
        ResolutionPreset("720p", 1280, 720, "2500k", "128k"),
        ResolutionPreset("480p", 854, 480, "1200k", "96k"),
        ResolutionPreset("360p", 640, 360, "800k", "64k"),
    ],
}


# Configuración principal

@dataclass
class TranscoderConfig:
    """Configuración principal del pipeline de transcodificación."""
    input_paths: list[Path]
    output_dir: Path
    subs_mode: SubsMode = SubsMode.CONVERT
    hw_accel: HWAccel = HWAccel.AUTO
    output_format: OutputFormat = OutputFormat.TS
    loudnorm: bool = True
    encrypt: EncryptionMode = EncryptionMode.NONE
    keyfile: Path | None = None
    thumbnail: ThumbnailMode = ThumbnailMode.NONE
    profile: str = "default"
    hls_time: int = 10
    delete_source: bool = False
    preset: str = "slow"
    log_file: Path | None = None

    def get_presets(self) -> list[ResolutionPreset]:
        """Devuelve los presets del perfil configurado."""
        return ENCODING_PROFILES.get(self.profile, ENCODING_PROFILES["default"])
