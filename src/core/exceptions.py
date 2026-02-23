from __future__ import annotations


class TranscoderError(Exception):
    """Excepción base para todos los errores del transcoder."""


class BinaryNotFoundError(TranscoderError):
    """No se encontró ffmpeg o ffprobe en el PATH."""

    def __init__(self, binary: str) -> None:
        self.binary = binary
        super().__init__(
            f"'{binary}' no se encontró en el PATH del sistema. "
            f"Instalalo desde https://ffmpeg.org/download.html y asegurate "
            f"de que esté accesible desde la terminal."
        )


class ProbeError(TranscoderError):
    """Error al analizar un archivo con ffprobe."""

    def __init__(self, path: str, detail: str = "") -> None:
        self.path = path
        msg = f"Error al analizar '{path}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class EncodingError(TranscoderError):
    """Error durante la codificación con ffmpeg."""

    def __init__(self, target: str, detail: str = "") -> None:
        self.target = target
        msg = f"Error de codificación en '{target}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class HWAccelError(TranscoderError):
    """El encoder de hardware solicitado no está disponible."""

    def __init__(self, encoder: str, reason: str = "") -> None:
        self.encoder = encoder
        msg = f"Aceleración por hardware '{encoder}' no disponible"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class SubtitleError(TranscoderError):
    """Error al procesar subtítulos."""

    def __init__(self, target: str, detail: str = "") -> None:
        self.target = target
        msg = f"Error de subtítulos en '{target}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)


class EncryptionError(TranscoderError):
    """Error al configurar cifrado HLS."""

    def __init__(self, target: str, detail: str = "") -> None:
        self.target = target
        msg = f"Error de cifrado en '{target}'"
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
