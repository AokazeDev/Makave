<p align="center">
  <img src="https://aokaze.vercel.app/favicon.svg" alt="Icono de la Aplicación" width="100">
</p>

<h1 align="center">Makave</h1>

<p align="center">
  Transcoder MKV → HLS multi-rendición con detección de hardware, subtítulos y normalización de audio.
</p>

![Python](https://img.shields.io/badge/Python-≥3.10-blue?logo=python&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-requerido-green?logo=ffmpeg&logoColor=white)
![Licencia](https://img.shields.io/badge/Licencia-MIT-yellow)

---

## Qué hace

Toma uno o más archivos `.mkv` y genera paquetes **HLS** listos para streaming, incluyendo:

- **Multi-rendición** en un solo paso (1080p / 720p / 480p, ajustable por perfil).
- **Pistas de audio separadas** como EXT-X-MEDIA (varios idiomas, sin duplicar audio en cada variante de video).
- **Subtítulos**: conversión a WebVTT segmentado para HLS, extracción como sidecar, o ignorar.
- **Normalización de audio** EBU R128 (`loudnorm`) activada por defecto.
- **Aceleración por hardware**: detecta automáticamente NVENC, QSV o VideoToolbox. Si no hay GPU compatible, usa `libx264`.
- **Cifrado AES-128** opcional para los segmentos HLS.
- **Thumbnails**: sprite sheet + archivo VTT para trickplay.
- **Interfaz en consola** con barras de progreso (powered by [rich](https://github.com/Textualize/rich)).

## Estructura del proyecto

```
MKV-to-HLS/
├── main.py                         # Entry point
├── requirements.txt
├── mkv_to_hls/
│   ├── __init__.py                 # Versión del paquete
│   ├── __main__.py                 # python -m mkv_to_hls
│   ├── cli.py                      # Argumentos CLI (argparse)
│   ├── pipeline.py                 # Orquestador principal
│   ├── core/                       # Tipos fundacionales
│   │   ├── exceptions.py           # Jerarquía de excepciones
│   │   ├── models.py               # Enums, dataclasses, perfiles
│   │   └── logger.py               # Logging + rich console
│   ├── processing/                 # Lógica de procesamiento
│   │   ├── scanner.py              # Análisis con ffprobe
│   │   ├── hw_detect.py            # Detección de encoder HW
│   │   ├── engine.py               # Construcción y ejecución ffmpeg
│   │   ├── subtitle_proc.py        # Extracción/conversión de subs
│   │   └── packager.py             # Post-proceso: master.m3u8 + thumbnails
│   └── utils/
│       ├── platform.py             # Detección de OS y binarios
│       └── crypto.py               # AES-128 key management
```

## Requisitos

| Herramienta | Versión mínima | Notas |
|---|---|---|
| **Python** | 3.10+ | Usa syntax moderna (`X \| None`, `match`, etc.) |
| **FFmpeg** | 4.4+ | Debe estar en el `PATH`. [Descarga](https://ffmpeg.org/download.html) |
| **ffprobe** | (incluido con FFmpeg) | Se usa para escanear los archivos de entrada |

### Hardware (opcional)

La aceleración por hardware acelera la codificación significativamente pero **no es obligatoria**. El transcoder detecta automáticamente qué está disponible y hace fallback a CPU.

| GPU | Encoder | Plataforma |
|---|---|---|
| NVIDIA (CUDA) | `h264_nvenc` | Windows / Linux |
| Intel (iGPU) | `h264_qsv` | Windows / Linux |
| Apple Silicon / AMD | `h264_videotoolbox` | macOS |

## Instalación

```bash
# Clonar el repo
git clone https://github.com/AokazeDev/Makave.git
cd Makave

# Instalar dependencias
pip install -r requirements.txt

# Verificar que ffmpeg esté accesible
ffmpeg -version
```

## Uso

### Básico

```bash
# Un solo archivo
python main.py video.mkv

# Varios archivos
python main.py S04E01.mkv S04E02.mkv S04E03.mkv

# Todos los MKV de un directorio
python main.py ./videos/

# También funciona como módulo
python -m makave video.mkv
```

### Con opciones

```bash
python main.py video.mkv \
  -o ./output \
  --profile action \
  --hw-accel auto \
  --subs-mode extract \
  --loudnorm on \
  --output-format fmp4 \
  --thumbnail sprite \
  --hls-time 6
```

### Todas las opciones

| Flag | Valores | Default | Descripción |
|---|---|---|---|
| `input` | archivos o directorio | — | Archivos MKV de entrada (posicional) |
| `-i, --input-file` | ruta | — | Archivo adicional (se puede repetir) |
| `-o, --output-dir` | ruta | `./output` | Directorio base de salida |
| `--subs-mode` | `convert`, `extract`, `keep` | `convert` | Modo de subtítulos |
| `--hw-accel` | `auto`, `nvenc`, `qsv`, `videotoolbox`, `cpu` | `auto` | Aceleración por hardware |
| `--output-format` | `ts`, `fmp4` | `ts` | Formato de segmentos HLS |
| `--loudnorm` | `on`, `off` | `on` | Normalización EBU R128 |
| `--encrypt` | `none`, `aes-128` | `none` | Cifrado de segmentos |
| `--thumbnail` | `none`, `sprite` | `none` | Generación de thumbnails |
| `--profile` | `default`, `action`, `animation`, `low` | `default` | Perfil de bitrates |
| `--hls-time` | entero | `10` | Duración de segmentos (segundos) |
| `--preset` | `slow`, `medium`, `fast` | `slow` | Preset de calidad ffmpeg |
| `--delete-source` | flag | — | Eliminar MKV original tras conversión exitosa |
| `--log-file` | ruta | auto | Ruta del archivo de log |
| `-v, --verbose` | flag | — | Salida detallada (debug) |

### Perfiles de codificación

| Perfil | Rendiciones | Bitrate video | Uso recomendado |
|---|---|---|---|
| `default` | 1080p / 720p / 480p | 5000k / 3000k / 1500k | Contenido general |
| `action` | 1080p / 720p / 480p | 8000k / 5000k / 2500k | Acción, deportes |
| `animation` | 1080p / 720p / 480p | 4000k / 2500k / 1200k | Anime, animación |
| `low` | 720p / 480p / 360p | 2500k / 1200k / 800k | Conexiones lentas |

### Modos de subtítulos

- **`convert`** (default): Convierte subtítulos de texto (SRT, ASS, etc.) a WebVTT y los segmenta para HLS. Los subtítulos bitmap (PGS) se extraen sin conversión con un aviso.
- **`extract`**: Extrae los subtítulos como archivos sidecar (`.srt`, `.ass`, `.sup`, etc.) sin integrarlos al HLS.
- **`keep`**: No procesa subtítulos.

## Salida generada

Para un archivo `S04E01.mkv` con 2 pistas de audio (inglés y español) y 1 subtítulo:

```
output/S04E01/
├── master.m3u8              # Playlist principal
├── 1080p/
│   ├── prog.m3u8
│   └── seg_000.ts, seg_001.ts, ...
├── 720p/
│   ├── prog.m3u8
│   └── seg_000.ts, ...
├── 480p/
│   ├── prog.m3u8
│   └── seg_000.ts, ...
├── audio_en_0/
│   ├── prog.m3u8
│   └── seg_000.ts, ...
├── audio_es_1/
│   ├── prog.m3u8
│   └── seg_000.ts, ...
├── subs/
│   └── sub_en_0/
│       ├── prog.m3u8
│       └── seg_000.vtt, ...
├── ffmpeg.log
└── transcode.log
```

## Cómo funciona (resumen técnico)

1. **Scan**: `ffprobe` analiza el archivo fuente → streams de video, audio y subtítulos.
2. **HW Detect**: Prueba el encoder HW con una codificación mínima de 0.1s (nullsrc). Si falla, cae a `libx264`.
3. **Encode**: Un solo comando ffmpeg genera todas las variantes de video y audio:
   - `filter_complex` con `split` + `scale` para multi-resolución.
   - `-var_stream_map` con `agroup:` para audio como rendiciones separadas.
   - `loudnorm` en el filter_complex si está habilitado.
   - `-progress pipe:1` para tracking en tiempo real.
4. **Subtítulos**: Se procesan en un paso separado por estabilidad.
5. **Post-proceso**: El `packager` parchea el `master.m3u8` con entradas de subtítulos y genera el sprite de thumbnails si fue solicitado.

## Licencia

Este proyecto está bajo la licencia MIT. Ver [LICENSE](LICENSE) para más detalles.

## Contribuciones

Las contribuciones son bienvenidas. Si querés aportar al proyecto, creá un Pull Request con tus sugerencias.
