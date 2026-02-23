from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

# Tema personalizado para el transcoder
THEME = Theme({
    "info": "cyan",
    "warning": "yellow",
    "error": "bold red",
    "success": "bold green",
    "progress": "magenta",
    "filename": "bold blue",
})

# Consola global del transcoder
console = Console(theme=THEME, stderr=True)


def setup_logging(log_file: Path | None = None, verbose: bool = False) -> logging.Logger:
    """Configura logging con salida a consola (rich) y opcionalmente a archivo.

    Args:
        log_file: Ruta opcional para el archivo de log.
        verbose: Si True, muestra mensajes DEBUG en consola.

    Returns:
        Logger configurado.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logger = logging.getLogger("makave")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # Handler de consola con rich
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=verbose,
        level=level,
    )
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console_handler)

    # Handler de archivo
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8", mode="a")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Obtiene el logger del transcoder."""
    return logging.getLogger("makave")
