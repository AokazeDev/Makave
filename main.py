#!/usr/bin/env python3
"""Makave Transcoder — MKV → HLS.

Uso:
    python main.py video.mkv
    python main.py *.mkv -o ./output --profile action
    python main.py --help

También se puede ejecutar como módulo:
    python -m makave video.mkv
"""

from src.__main__ import main

if __name__ == "__main__":
    main()
