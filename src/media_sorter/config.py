"""Configuration management for Media Sorter.

Provides Pydantic-based settings validated from YAML, TOML, JSON, or environment variables.
"""

from __future__ import annotations

import os
import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ActionType(str, Enum):
    MOVE = "move"
    COPY = "copy"
    LINK = "link"
    HARDLINK = "hardlink"


class ConflictPolicy(str, Enum):
    SKIP = "skip"
    RENAME_UNIQUE = "rename_unique"
    QUARANTINE = "quarantine"
    REPLACE_IF_HIGHER_QUALITY = "replace_if_higher_quality"
    ERROR = "error"


class DestinationDirs(BaseModel):
    movies: str = "Movies"
    tv: str = "TV Shows"
    anime: str = "Anime"
    music: str = "Music"
    audiobooks: str = "Audiobooks"
    podcasts: str = "Podcasts"
    home_videos: str = "Home Videos"
    photos: str = "Photos"
    archives: str = "Archives"
    quarantine: str = "Quarantine"


class GeneralSettings(BaseModel):
    dry_run: bool = True
    confidence_threshold: float = 0.75
    worker_count: int = 4
    min_file_age_seconds: int = 300
    action: ActionType = ActionType.MOVE
    preserve_permissions: bool = True
    log_level: str = "INFO"
    scan_interval_seconds: int = 0

    @field_validator("confidence_threshold")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 < v <= 1.0:
            raise ValueError("confidence_threshold must be between 0.0 and 1.0")
        return v

    @field_validator("worker_count")
    @classmethod
    def validate_worker_count(cls, v: int) -> int:
        if v < 1:
            raise ValueError("worker_count must be at least 1")
        return v

    @field_validator("min_file_age_seconds")
    @classmethod
    def validate_min_file_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError("min_file_age_seconds cannot be negative")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}")
        return upper


class StorageSettings(BaseModel):
    source_dirs: List[str] = Field(default_factory=lambda: ["incoming"])
    destination_base: str = "organized"
    destination_dirs: DestinationDirs = Field(default_factory=DestinationDirs)


class ConflictSettings(BaseModel):
    policy: ConflictPolicy = ConflictPolicy.RENAME_UNIQUE
    allow_overwrite: bool = False
    backup_dir: Optional[str] = None


class FilterSettings(BaseModel):
    include_patterns: List[str] = Field(default_factory=lambda: ["*"])
    exclude_patterns: List[str] = Field(
        default_factory=lambda: [
            ".*",
            "*.part",
            "*.crdownload",
            "*.!qB",
            "Thumbs.db",
            "desktop.ini",
            "@eaDir",
            "$RECYCLE.BIN",
        ]
    )


class TemplateSettings(BaseModel):
    movie: str = "{title} ({year})/{title} ({year}) [{resolution} {codec}].{ext}"
    tv: str = "{title}/Season {season:02d}/{title} - S{season:02d}E{episode:02d} - {episode_title}.{ext}"
    anime: str = "{title}/Season {season:02d}/{title} - S{season:02d}E{episode:02d} [{group}].{ext}"
    music: str = "{artist}/{album} ({year})/{disc:01d}{track:02d} - {title}.{ext}"
    audiobook: str = "{author}/{title}/{track:02d} - {chapter}.{ext}"
    podcast: str = "{show}/{year}/{show} - {date} - {title}.{ext}"
    home_video: str = "{year}/{year}-{month:02d} - {event}/{filename}.{ext}"
    photo: str = "{year}/{year}-{month:02d}/{year}{month:02d}{day:02d}_{time}_{camera}.{ext}"
    archive: str = "Archives/{filename}.{ext}"
    quarantine: str = "Quarantine/{reason}/{filename}.{ext}"


class SubtitleSettings(BaseModel):
    match_video_basename: bool = True
    preserve_language_code: bool = True


class ArtworkSettings(BaseModel):
    match_parent_folder: bool = True


class ExtrasSettings(BaseModel):
    detect_trailers: bool = True
    trailer_suffix: str = "-trailer"


class SidecarSettings(BaseModel):
    enabled: bool = True
    subtitles: SubtitleSettings = Field(default_factory=SubtitleSettings)
    artwork: ArtworkSettings = Field(default_factory=ArtworkSettings)
    extras: ExtrasSettings = Field(default_factory=ExtrasSettings)


class DatabaseSettings(BaseModel):
    path: str = "media_sorter.db"
    wal_mode: bool = True


class ServerSettings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    enabled: bool = True


class ProviderSettings(BaseModel):
    enable_online_metadata: bool = False
    tmdb_api_key: Optional[str] = None
    tvdb_api_key: Optional[str] = None
    rate_limit_per_second: float = 2.0
    cache_expiry_hours: int = 72


class NotificationSettings(BaseModel):
    enabled: bool = False
    webhook_url: Optional[str] = None
    notify_on_complete: bool = True
    notify_on_failure: bool = True


class SymlinkSettings(BaseModel):
    follow_symlinks: bool = False
    handle_broken_symlinks: str = "skip"  # skip | quarantine


class PermissionSettings(BaseModel):
    preserve_attributes: bool = True
    file_mode: Optional[str] = None  # e.g. "0644"
    dir_mode: Optional[str] = None   # e.g. "0755"
    owner: Optional[str] = None
    group: Optional[str] = None


class QuarantineSettings(BaseModel):
    move_to_quarantine_folder: bool = True
    directory: str = "Quarantine"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEDIA_SORTER_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    general: GeneralSettings = Field(default_factory=GeneralSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    conflicts: ConflictSettings = Field(default_factory=ConflictSettings)
    filters: FilterSettings = Field(default_factory=FilterSettings)
    templates: TemplateSettings = Field(default_factory=TemplateSettings)
    sidecars: SidecarSettings = Field(default_factory=SidecarSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    symlinks: SymlinkSettings = Field(default_factory=SymlinkSettings)
    permissions: PermissionSettings = Field(default_factory=PermissionSettings)
    quarantine: QuarantineSettings = Field(default_factory=QuarantineSettings)

    def model_post_init(self, __context: Any) -> None:
        super().model_post_init(__context)
        # Check intuitive environment variable overrides from .env only if not explicitly supplied
        if "storage" not in self.model_fields_set:
            downloads_dir = os.getenv("DOWNLOADS_DIR") or os.getenv("SOURCE_DIR")
            if downloads_dir:
                self.storage.source_dirs = [downloads_dir]

            movies_dir = os.getenv("MOVIES_DIR")
            if movies_dir:
                self.storage.destination_dirs.movies = movies_dir

            shows_dir = os.getenv("SHOWS_DIR") or os.getenv("TV_DIR")
            if shows_dir:
                self.storage.destination_dirs.tv = shows_dir

            anime_dir = os.getenv("ANIME_DIR")
            if anime_dir:
                self.storage.destination_dirs.anime = anime_dir
            elif shows_dir:
                self.storage.destination_dirs.anime = shows_dir

        if "general" not in self.model_fields_set:
            dry_run_env = os.getenv("DRY_RUN")
            if dry_run_env is not None:
                self.general.dry_run = dry_run_env.strip().lower() in ("true", "1", "yes", "on")

            action_env = os.getenv("ACTION")
            if action_env:
                try:
                    self.general.action = ActionType(action_env.lower())
                except ValueError:
                    pass

            conf_env = os.getenv("CONFIDENCE_THRESHOLD")
            if conf_env:
                try:
                    self.general.confidence_threshold = float(conf_env)
                except ValueError:
                    pass

            min_age_env = os.getenv("MIN_FILE_AGE_SECONDS")
            if min_age_env:
                try:
                    self.general.min_file_age_seconds = int(min_age_env)
                except ValueError:
                    pass

            scan_int_env = os.getenv("SCAN_INTERVAL_SECONDS")
            if scan_int_env:
                try:
                    self.general.scan_interval_seconds = int(scan_int_env)
                except ValueError:
                    pass

        if "server" not in self.model_fields_set:
            host_env = os.getenv("SERVER_HOST") or os.getenv("HOST")
            if host_env:
                self.server.host = host_env

            port_env = os.getenv("SERVER_PORT") or os.getenv("PORT")
            if port_env:
                try:
                    self.server.port = int(port_env)
                except ValueError:
                    pass

        if "database" not in self.model_fields_set:
            db_path_env = os.getenv("DATABASE_PATH")
            if db_path_env:
                self.database.path = db_path_env

    def resolve_path(self, raw_path: str) -> Path:
        """Expand environment variables and user home, returning resolved Path."""
        expanded = os.path.expandvars(raw_path)
        return Path(expanded).expanduser().resolve()

    def get_source_paths(self) -> List[Path]:
        return [self.resolve_path(p) for p in self.storage.source_dirs]

    def get_destination_base_path(self) -> Path:
        return self.resolve_path(self.storage.destination_base)

    def get_destination_path(self, category: str) -> Path:
        """Return the destination path for a given category."""
        base = self.get_destination_base_path()
        cat_map = {
            "movie": "movies",
            "movies": "movies",
            "tv": "tv",
            "show": "tv",
            "shows": "tv",
            "audiobook": "audiobooks",
            "podcast": "podcasts",
            "photo": "photos",
            "home_video": "home_videos",
            "archive": "archives",
        }
        lookup_key = cat_map.get(category, category)
        dest_field = getattr(self.storage.destination_dirs, lookup_key, category)
        path = Path(dest_field)
        # If dest_field is an explicit relative path (e.g. ./movies, ./shows) or absolute path
        if path.is_absolute() or str(dest_field).startswith(("./", "../")):
            return path.resolve()
        return (base / path).resolve()

    @classmethod
    def load_from_env_file(cls, env_path: Path | str = ".env") -> Settings:
        """Load configuration from a .env file."""
        path = Path(env_path).expanduser().resolve()
        settings = cls()
        if not path.is_file():
            return settings

        from dotenv import dotenv_values
        values = dotenv_values(path)

        downloads_dir = os.getenv("DOWNLOADS_DIR") or values.get("DOWNLOADS_DIR") or os.getenv("SOURCE_DIR") or values.get("SOURCE_DIR")
        if downloads_dir:
            settings.storage.source_dirs = [downloads_dir]

        movies_dir = os.getenv("MOVIES_DIR") or values.get("MOVIES_DIR")
        if movies_dir:
            settings.storage.destination_dirs.movies = movies_dir

        shows_dir = os.getenv("SHOWS_DIR") or values.get("SHOWS_DIR") or os.getenv("TV_DIR") or values.get("TV_DIR")
        if shows_dir:
            settings.storage.destination_dirs.tv = shows_dir

        anime_dir = os.getenv("ANIME_DIR") or values.get("ANIME_DIR")
        if anime_dir:
            settings.storage.destination_dirs.anime = anime_dir
        elif shows_dir:
            settings.storage.destination_dirs.anime = shows_dir

        dry_run = os.getenv("DRY_RUN") if os.getenv("DRY_RUN") is not None else values.get("DRY_RUN")
        if dry_run is not None:
            settings.general.dry_run = dry_run.strip().lower() in ("true", "1", "yes", "on")

        action = os.getenv("ACTION") or values.get("ACTION")
        if action:
            try:
                settings.general.action = ActionType(action.lower())
            except ValueError:
                pass

        conf = os.getenv("CONFIDENCE_THRESHOLD") or values.get("CONFIDENCE_THRESHOLD")
        if conf:
            try:
                settings.general.confidence_threshold = float(conf)
            except ValueError:
                pass

        min_age = os.getenv("MIN_FILE_AGE_SECONDS") or values.get("MIN_FILE_AGE_SECONDS")
        if min_age:
            try:
                settings.general.min_file_age_seconds = int(min_age)
            except ValueError:
                pass

        scan_int = os.getenv("SCAN_INTERVAL_SECONDS") or values.get("SCAN_INTERVAL_SECONDS")
        if scan_int:
            try:
                settings.general.scan_interval_seconds = int(scan_int)
            except ValueError:
                pass

        host = os.getenv("SERVER_HOST") or values.get("SERVER_HOST") or os.getenv("HOST") or values.get("HOST")
        if host:
            settings.server.host = host

        port = os.getenv("SERVER_PORT") or values.get("SERVER_PORT") or os.getenv("PORT") or values.get("PORT")
        if port:
            try:
                settings.server.port = int(port)
            except ValueError:
                pass

        db_path = os.getenv("DATABASE_PATH") or values.get("DATABASE_PATH")
        if db_path:
            settings.database.path = db_path

        return settings

    def save_to_env_file(self, env_path: Path | str = ".env") -> None:
        """Persist key user-configurable settings to a .env file."""
        path = Path(env_path)
        content = (
            f"# Media Sorter Configuration\n"
            f"DOWNLOADS_DIR={self.storage.source_dirs[0] if self.storage.source_dirs else './downloads'}\n"
            f"MOVIES_DIR={self.storage.destination_dirs.movies}\n"
            f"SHOWS_DIR={self.storage.destination_dirs.tv}\n"
            f"DRY_RUN={'true' if self.general.dry_run else 'false'}\n"
            f"ACTION={self.general.action.value}\n"
            f"CONFIDENCE_THRESHOLD={self.general.confidence_threshold}\n"
            f"MIN_FILE_AGE_SECONDS={self.general.min_file_age_seconds}\n"
            f"SCAN_INTERVAL_SECONDS={self.general.scan_interval_seconds}\n"
            f"SERVER_HOST={self.server.host}\n"
            f"SERVER_PORT={self.server.port}\n"
            f"DATABASE_PATH={self.database.path}\n"
        )
        path.write_text(content, encoding="utf-8")

    def get_database_path(self) -> Path:
        return self.resolve_path(self.database.path)

    @classmethod
    def load_from_file(cls, config_path: Path | str) -> Settings:
        """Load configuration from YAML, TOML, or JSON file."""
        path = Path(config_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        ext = path.suffix.lower()
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        if ext in (".yaml", ".yml"):
            data = yaml.safe_load(content) or {}
        elif ext == ".json":
            data = json.loads(content)
        elif ext == ".toml":
            try:
                import tomllib  # Python 3.11+
                data = tomllib.loads(content)
            except ImportError:
                import tomli
                data = tomli.loads(content)
        else:
            # Fallback to YAML loader which can parse JSON and YAML
            data = yaml.safe_load(content) or {}

        return cls(**data)

    def dump_yaml(self, target_path: Path | str) -> None:
        """Dump settings to YAML format."""
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
