# Media Sorter

A reliable, high-performance media classification and organization engine engineered with defensive data safety, atomic operations, dry-run simulation, operation journaling, transactional rollback, and review quarantine.

Supported media types:
- **Movies** (Feature films, scene releases, REMUX, UHD/4K, multi-part)
- **TV Shows** (Episodic series, multi-episode files, season packages)
- **Anime** (Fansub groups, absolute numbering, season/episode mapping)
- **Music** (Multi-disc albums, flac/mp3, ID3v2/Vorbis tags, track/artist tokens)
- **Audiobooks** (M4B, chapter tags, narrator metadata, multi-part)
- **Podcasts** (Dated releases, show prefixes, episode titles)
- **Documentaries** (Documentary flags, broadcast tags)
- **Home Videos & Photos** (EXIF datetime, camera models, smartphone naming schemes)
- **Sidecars & Companions** (Subtitles `.srt/.ass`, Artwork `poster/cover`, Metadata `.nfo`, Extras `-trailer/-sample`)
- **Archives & Unknowns** (Zip, rar, 7z, and unclassified files isolated safely)

---

## Key Safety Guarantees

1. **Zero Silent Data Loss**: Files are never deleted by default.
2. **Dry-Run by Default**: Operations always default to dry-run preview unless explicitly launched with `--live` or configured otherwise.
3. **No Guessing / Quarantine Queue**: If classification confidence falls below the configured threshold (default `0.75`), the file is placed into the Quarantine queue for human inspection.
4. **Collision & Conflict Prevention**: Destination paths are validated beforehand. If a collision is detected, the configurable policy (`rename_unique`, `replace_if_higher_quality`, `quarantine`, `skip`, or `error`) is triggered safely.
5. **Atomic Moves**: Moves on the same filesystem use `os.replace`. Moves across filesystems write to hidden temporary files (`.tmp_media_sorter_*`), verify integrity/size, atomically replace into destination, and only then remove source files.
6. **Transactional Journaling & Instant Rollback**: All operations are recorded in a SQLite WAL database (`OperationStatus.PLANNED` -> `IN_PROGRESS` -> `COMMITTED`). Any batch can be cleanly inverted with `media-sorter rollback --batch-id <id>`.
7. **Active Download / Lock Protection**: Automatically ignores files modified within the minimum file age (default 300s) or locked by downloading torrent/browser clients.

---

## Architecture

```
                                  +-----------------------+
                                  |   Source Directories  |
                                  +-----------+-----------+
                                              |
                                              v
                                  +-----------------------+
                                  |  Scanner (Lock/Age)   |
                                  +-----------+-----------+
                                              |
                     +------------------------+------------------------+
                     |                        |                        |
                     v                        v                        v
          +--------------------+    +-------------------+    +-------------------+
          | Filename Tokenizer |    |  Media Analyzer   |    | External Provider |
          | (Regex / Patterns) |    | (Headers/Atoms)   |    | (TMDB/MusicBrainz)|
          +----------+---------+    +---------+---------+    +---------+---------+
                     |                        |                        |
                     +------------------------+------------------------+
                                              |
                                              v
                                  +-----------------------+
                                  | Multi-Signal          |
                                  | Classifier & Scorer   |
                                  +-----------+-----------+
                                              |
                        +---------------------+---------------------+
                        | (Confidence >= 0.75)|                     | (Confidence < 0.75)
                        v                                           v
            +-----------------------+                   +-----------------------+
            | Namer & Path Sanitizer|                   | Quarantine Manager    |
            +-----------+-----------+                   +-----------------------+
                        |
                        v
            +-----------------------+
            |  Executor & Journal   | <==== SQLite WAL Database (media_sorter.db)
            +-----------+-----------+
                        |
            +-----------+-----------+
            | Organized Destination |
            +-----------------------+
```

---

## Quickstart

### 1. Installation

```bash
# Clone repository
git clone https://github.com/example/media-sorter.git
cd media-sorter

# Create virtual environment and install
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 2. Configuration (.env)

Media Sorter supports simple, editable settings directly in a `.env` file in the project root:

```ini
# .env
DOWNLOADS_DIR=./downloads     # Source folder where downloads arrive
MOVIES_DIR=./movies           # Destination for Movies
SHOWS_DIR=./shows             # Destination for TV Series
DRY_RUN=false                 # false = move files live; true = simulation preview
ACTION=move                   # move | copy | link | hardlink
CONFIDENCE_THRESHOLD=0.75     # Minimum classification confidence (0.0 - 1.0)
MIN_FILE_AGE_SECONDS=0        # Ignore files modified within N seconds
SERVER_HOST=0.0.0.0
SERVER_PORT=8085
DATABASE_PATH=media_sorter.db
```

Check your active configuration at any time:

```bash
media-sorter config show
```

### 3. Web Dashboard & Management UI

Start the responsive, modern Web Management Dashboard:

```bash
media-sorter server
```

Open `http://localhost:8085` (or `http://<your-host-ip>:8085`) in your browser. The web UI includes:
- **Dashboard & Activity**: Live metrics, mode badge, 1-click Dry-Run Preview & Live Sort buttons, 1-click Server Restart button, and past batch history.
- **Folder Explorer**: Live view of files in `downloads/`, `movies/`, and `shows/` with file sizes and timestamps.
- **Quarantine Review**: Visual approval queue for ambiguous media with 1-click "Approve as Movie" or "Approve as Show".
- **Settings & .env**: Interactive settings form where you can update directory paths, toggle dry-run mode, and save directly to `.env`.

### 4. Running with PM2 (Production Process Manager)

Media Sorter includes an [`ecosystem.config.js`](file:///md0/media-sorter/ecosystem.config.js) file for daemonizing under PM2:

```bash
# Start Media Sorter with PM2
pm2 start ecosystem.config.js

# View status
pm2 status

# View live stream logs
pm2 logs media-sorter

# Restart or reload
pm2 restart media-sorter

# Enable PM2 to auto-start on machine boot
pm2 save
pm2 startup
```

The web dashboard's **🔄 Restart Server** button connects natively with PM2: clicking it restarts the process and automatically refreshes the web page once back online.

### 5. Scan & Preview (Dry-Run)

Preview classification without touching any files:

```bash
media-sorter scan
```

Generate a dry-run batch preview:

```bash
media-sorter organize --dry-run
```

### 5. Execute Live Organization

Sort files from `downloads/` into `movies/` or `shows/`:

```bash
media-sorter organize --live
```

### 6. Instant Rollback

If you ever need to undo an organization run:

```bash
# Revert latest batch
media-sorter rollback

# Revert specific batch
media-sorter rollback --batch-id <batch-uuid>
```

### 7. Review Quarantine Queue

List and resolve files requiring manual verification via CLI:

```bash
media-sorter quarantine list
media-sorter quarantine resolve 1 --category movie
```

---

## CLI Reference

| Command | Description |
|---|---|
| `media-sorter scan` | Discover and analyze source media, displaying classification table |
| `media-sorter organize` | Execute organization or dry-run preview (`--dry-run` or `--live`) |
| `media-sorter rollback` | Roll back a batch and restore files to source paths |
| `media-sorter history` | View audit trail of past batches and metrics |
| `media-sorter quarantine list` | List items pending manual human review |
| `media-sorter quarantine resolve` | Approve or reclassify a quarantined item |
| `media-sorter server` | Start FastAPI REST API and web management dashboard |
| `media-sorter config show` | Display active configuration settings in YAML |
| `media-sorter config init` | Generate a starter configuration file |

---

## Database & State Tracking

The system utilizes SQLite in **Write-Ahead Logging (WAL)** mode with `PRAGMA synchronous=NORMAL` and `PRAGMA foreign_keys=ON`:
- `batches`: High-level run records with status (`IN_PROGRESS`, `COMPLETED`, `ROLLED_BACK`), dry-run indicator, counts of moved, skipped, failed, and quarantined files.
- `operations`: Fine-grained journal entries tracking `src`, `dst`, `action` (`move`, `copy`, `link`, `hardlink`), `src_hash`, `dst_hash`, `backup_path`, diagnostic details, and timestamps.
- `files`: File fingerprint cache (`path`, `size`, `mtime`, `hash`) to avoid redundant metadata probing on unchanged files.
- `quarantine`: Audit log for low-confidence or conflicting files holding reason, signals, and resolution states.

### Migrations with Alembic

Run database migrations:

```bash
alembic upgrade head
```

Create a new migration:

```bash
alembic revision --autogenerate -m "Add custom column"
```

---

## Deployment

### Docker

Build and run with Docker Compose:

```bash
docker-compose up -d
```

Check health status:

```bash
curl -f http://localhost:8080/api/status
```

### Systemd Service

1. Copy repository to `/opt/media-sorter`.
2. Copy `media-sorter.service` to `/etc/systemd/system/media-sorter.service`.
3. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now media-sorter
sudo systemctl status media-sorter
```

---

## Backup & Upgrade Instructions

### Database Backup

Because SQLite uses WAL mode, use the standard SQLite online backup or VACUUM INTO command:

```bash
# Safe hot-backup of live database
sqlite3 media_sorter.db ".backup 'media_sorter.backup.db'"
```

Or backup directory before upgrading:

```bash
cp media_sorter.db media_sorter.db.bak
```

### Upgrading

1. Pull latest release:
   ```bash
   git pull origin main
   ```
2. Update dependencies:
   ```bash
   pip install -e .
   ```
3. Run Alembic schema migrations:
   ```bash
   alembic upgrade head
   ```
4. Restart service:
   ```bash
   sudo systemctl restart media-sorter
   ```

---

## Testing

Run the full test suite (unit tests, integration tests, and Hypothesis property-based fuzz tests):

```bash
pytest -v
```
