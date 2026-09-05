<div align="center">

# 🎬 Media Sorter

**High-performance, automated media classification and organization engine with defensive data safety, atomic operations, transactional rollback, and modern web UI.**

[![Release](https://img.shields.io/badge/release-v1.0.0-blue.svg)](https://github.com/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![SQLite WAL](https://img.shields.io/badge/SQLite-WAL%20Journaling-003B57.svg)](https://www.sqlite.org/wal.html)
[![Tests Passing](https://img.shields.io/badge/tests-51%20passing-brightgreen.svg)]()
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

---

## 🌟 Highlights

- 🛡️ **Zero Silent Data Loss Guarantee**: Files are never deleted or silently overwritten. Unsure files are safely quarantined.
- 🔍 **Multi-Signal Classification Engine**: Classifies media using filename patterns, tokens, codecs, container streams, ID3v2/Vorbis tags, and episode hierarchies.
- 🎨 **Modern Interactive Web UI**: Fully responsive dashboard with customizable themes, Folder Explorer with show detection & live TV show artwork, Quarantine Queue, and Settings.
- ⚡ **Non-Shifting Scrollable Viewport**: Smoothly scroll through 500+ file libraries with sticky table headers without shifting the top navigation bar.
- ↩️ **Atomic Operations & 1-Click Rollback**: Every batch is journaled in SQLite WAL mode. Easily invert any batch with a single click or CLI command.
- 🚀 **Production Ready**: Native PM2 integration, Docker & Docker Compose setup, and systemd service templates included.

---

## 📑 Table of Contents

- [Supported Media Types](#-supported-media-types)
- [Safety & Reliability Principles](#-safety--reliability-principles)
- [Web Dashboard Features](#-web-dashboard-features)
- [Quickstart & Installation](#-quickstart--installation)
  - [Option A: Python Virtualenv](#option-a-python-virtualenv)
  - [Option B: PM2 Process Manager](#option-b-pm2-process-manager-recommended-for-servers)
  - [Option C: Docker & Docker Compose](#option-c-docker--docker-compose)
- [Configuration (.env)](#-configuration-env)
- [CLI Reference](#-cli-reference)
- [REST API Reference](#-rest-api-reference)
- [Testing & Quality Assurance](#-testing--quality-assurance)
- [License](#-license)

---

## 🎯 Supported Media Types

| Category | Typical Formats | Detection Signals |
| :--- | :--- | :--- |
| **Movies** | `.mkv`, `.mp4`, `.avi`, `.m4v` | Year tags, edition flags (Extended/Director's Cut), resolution tokens, single file structures. |
| **TV Shows** | `.mkv`, `.mp4`, `.ts` | `S01E05`, `1x05`, season pack structures, multi-episode tokens, episode titles. |
| **Anime** | `.mkv`, `.mp4` | Fansub release brackets `[SubsPlease]`, absolute numbering (`Episode 500`), CRC32 hashes. |
| **Music** | `.flac`, `.mp3`, `.m4a`, `.opus` | ID3v2/Vorbis metadata, disc/track tags, multi-disc hierarchies, artist tokens. |
| **Audiobooks** | `.m4b`, `.mp3` | Chapter tags, narrator metadata, audiobook series tags. |
| **Podcasts** | `.mp3`, `.m4a` | Release dates (`YYYY-MM-DD`), episode numbers, show titles. |
| **Documentaries**| `.mkv`, `.mp4` | Miniseries tags, broadcast metadata, documentary tokens. |
| **Sidecars** | `.srt`, `.ass`, `.nfo`, images | Automatically mapped and moved alongside parent media files. |
| **Quarantine** | Any unclassified / low confidence | Isolated safely in the quarantine queue for user review. |

---

## 🛡️ Safety & Reliability Principles

1. **Dry-Run by Default**: All actions run in simulation mode unless explicitly triggered as Live.
2. **Confidence Thresholding**: Items with classification score `< 0.75` (configurable) are diverted to Quarantine rather than misplaced.
3. **Collision Avoidance**: If a target file already exists, Media Sorter executes your collision policy (`rename_unique`, `replace_if_higher_quality`, `quarantine`, `skip`, or `error`).
4. **Atomic Two-Stage Moves**: Same-filesystem operations use atomic `os.replace`. Cross-filesystem operations write to hidden temporary files, verify size and integrity, atomically link, and only then unlink the source.
5. **Active File Protection**: Files actively being written by BitTorrent or downloading clients (or modified within `min_file_age_seconds`) are skipped until finished.
6. **Transactional Journaling**: Every operation logs old path, new path, file size, hash, and status into a SQLite database with WAL journaling.

---

## 🖥️ Web Dashboard Features

### 1. Folder Explorer with Live Show Artwork & Accordions
- **Intelligent Grouping**: Automatically identifies episodes belonging to the same series in your downloads folder.
- **Show Artwork**: Displays official high-resolution posters from TVmaze and local directories next to the believed show name.
- **Collapsible Cards**: Expand and collapse individual shows or use "Expand All" / "Collapse All" controls.
- **Single Files Table**: Non-episodic files and movies are cleanly separated with detected metadata.

### 2. Dedicated Settings Modal & Process Control
- Access settings via the **⚙️ Settings** button in the header.
- Switch visual themes with live color cards.
- **Restart Server Process**: Restarts the PM2 process with an automatic reconnection overlay.
- **Clear Activity History**: Wipes historical batch records with a single click.

### 3. Quarantine Review & Resolution
- Review items with lower confidence.
- Sort them into **Movies** or **Shows** with one click.

---

## 🚀 Quickstart & Installation

### Option A: Python Virtualenv

```bash
# 1. Clone repository
git clone https://github.com/yourusername/media-sorter.git
cd media-sorter

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install package and dependencies
pip install -e .

# 4. Copy and configure .env
cp .env.example .env
nano .env

# 5. Start the web dashboard
media-sorter web --host 0.0.0.0 --port 8085
```

### Option B: PM2 Process Manager (Recommended for Servers)

```bash
# 1. Install PM2 globally (if not already installed)
npm install -g pm2

# 2. Start Media Sorter using ecosystem.config.js
pm2 start ecosystem.config.js

# 3. Save PM2 startup list
pm2 save
pm2 startup
```

To view logs or restart:
```bash
pm2 logs media-sorter
pm2 restart media-sorter --update-env
```

### Option C: Docker & Docker Compose

```bash
# Configure paths in docker-compose.yml or .env, then launch:
docker compose up -d
```

---

## ⚙️ Configuration (.env)

Create a `.env` file in the project root:

```ini
# Directories (Absolute or Relative Paths)
DOWNLOADS_DIR=/path/to/downloads   # Incoming media source
MOVIES_DIR=/path/to/movies         # Destination for movies
SHOWS_DIR=/path/to/tv              # Destination for TV shows and anime

# Operational Mode
DRY_RUN=false                      # true = preview only, false = perform actual moves
CONFIDENCE_THRESHOLD=0.75          # Minimum confidence to automatically sort (0.0 - 1.0)
ACTION=move                        # 'move', 'copy', or 'hardlink'
SCAN_INTERVAL=0                    # Background daemon scan interval in seconds (0 = disabled)
MIN_FILE_AGE=0                     # Minimum file age in seconds before processing

# Web Server
PORT=8085
HOST=0.0.0.0
```

---

## 💻 CLI Reference

Media Sorter includes a full CLI for scripting and headless servers:

```bash
# Run a dry-run preview on downloads
media-sorter run --dry-run

# Run live sorting
media-sorter run --live

# Rollback a specific batch
media-sorter rollback --batch-id <BATCH_UUID>

# Rollback the most recent batch
media-sorter rollback --latest

# Review quarantined files
media-sorter quarantine list

# Launch web dashboard
media-sorter web --port 8085
```

---

## 🌐 REST API Reference

The built-in FastAPI server provides endpoints for dashboard integrations:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/` | Serves the interactive web interface. |
| `GET` | `/api/status` | Current server configuration, paths, and stats. |
| `GET` | `/api/files` | Discovered files, show groupings, and poster URLs. |
| `POST` | `/api/run` | Execute sort run (`{"dry_run": true/false}`). |
| `POST` | `/api/rollback` | Rollback a previous batch (`{"batch_id": "..."}`). |
| `GET` | `/api/batches` | List batch history and statuses. |
| `POST` | `/api/batches/clear` | Clear batch and activity history. |
| `GET` | `/api/quarantine` | List files currently held in quarantine. |
| `POST` | `/api/quarantine/resolve`| Manually resolve a quarantined item (`movie` or `tv`). |
| `GET` | `/api/poster` | Query or fetch show poster artwork URL. |
| `POST` | `/api/settings` | Save updated `.env` configuration. |
| `POST` | `/api/restart` | Gracefully restart the server process. |

---

## 🧪 Testing & Quality Assurance

Media Sorter includes a comprehensive suite of 51 unit, integration, and fuzz tests:

```bash
# Run tests
pytest

# Run tests with verbose output
pytest -v
```

Test coverage includes:
- Multi-token classification and fuzzy filename parsing.
- High-concurrency database journaling in SQLite WAL mode.
- Cross-filesystem atomic transfer simulation.
- 100% rollback fidelity across complex batches.
- Web API endpoints and environment reconfiguration.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
