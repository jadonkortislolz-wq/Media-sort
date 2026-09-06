# Survey Report: Media Sorter Pattern Matching, Classification, Tokenization, Naming & Destination Routing Logic

## 1. Observation

A systematic codebase survey and empirical execution audit of Media Sorter was performed against the Python packages in `src/media_sorter/` (specifically `tokenizer.py`, `classifier.py`, `namer.py`, `sorter.py`, `scanner.py`, `models.py`, `library.py`, `config.py`, and `server.py`) and existing test suites in `tests/`.

### 1.1 Existing Architecture & Module Responsibilities

| Module | Core Responsibility | Current State & Limitations |
|---|---|---|
| `tokenizer.py` | Extracts tokens (title, year, season, episode, codecs, group) from filenames | Heuristics based on 7 regexes. Misses editions, multi-part splits, season packs, specials/OVAs, daily shows, and non-hyphenated or parenthesized anime titles. |
| `classifier.py` | Multi-signal category assignment (movie, tv, anime, music, photo, etc.) with confidence scores | Strict 0.75 threshold. Daily shows and season packs get misclassified as movies or quarantined. Hardcoded list of 4 anime fansub groups. |
| `namer.py` | Destination path generation, template rendering, and cross-platform sanitization | Bugs in Season 0 (`S00` rendered as `S01`), quarantine paths double-extending `.mkv.mkv`, default group token inserting `[UnknownGroup]`, and multi-episode discarding subsequent episode numbers. |
| `sorter.py` | Orchestrates discovery, scanning, analysis, planning, and transactional execution | Anime files moved to `Anime/` trigger `ValueError` on `relative_to(shows_dir)` during library indexing, silently dropping anime from `library_items`. |
| `scanner.py` | Directory traversal, file lock checks, and sidecar pairing | Subtitle pairing only matches if subtitle stem starts with primary stem (`s_stem.startswith(c_stem)`); fails if subtitle has clean name (e.g. `Movie.2023.srt` vs `Movie.2023.1080p.mkv`). |
| `models.py` | SQLAlchemy database models (`BatchRecord`, `FileRecord`, `Operation`, `QuarantineRecord`, `LibraryItem`) | No `MediaType` enum. `LibraryItem.category` is documented as `# "tv" or "movie"` with unique constraint on `(title, category)`. No dedicated anime library category. |
| `library.py` | Show and movie library cataloging and disk synchronization | Hardcoded to only scan `tv` and `movie` destination folders. `record_detected_item` forces any non-movie category to `"tv"`. |
| `server.py` | FastAPI dashboard endpoints and downloads directory inspector | Duplicates title cleaning (`clean_detected_show_name` vs `extract_clean_stem` vs `_clean_title`). Does not display anime directory in `/api/files`. |

---

### 1.2 Current Regex Patterns in `src/media_sorter/tokenizer.py`

Directly observed in `src/media_sorter/tokenizer.py`:

1. **Season / Episode Regex** (`tokenizer.py`, lines 16-29):
   ```python
   RE_SEASON_EPISODE = re.compile(
       r"""(?ix)
       (?:
           (?<![0-9a-z])s(?P<season>\d{1,2})[\.\s_-]*(?:e|ep|ed|op)(?P<episode>\d{1,3})
           (?:[\.\s_-]*(?:e|x|-)(?P<episode_end>\d{1,3}))?(?![0-9]) # multi-episode like S01E01-E02
       |
           (?<![0-9a-z])(?P<season_x>\d{1,2})x(?!(?:264|265|vid|hevc|avc))(?P<episode_x>\d{1,3})(?![0-9])
       |
           \bseason[\.\s_-]*(?P<season_word>\d{1,2})[\.\s_-]*(?:episode|ep)[\.\s_-]*(?P<episode_word>\d{1,3})\b
       |
           \b(?:episodes?|ep)[\.\s_-]*(?P<episode_standalone>\d{1,4})(?![0-9])\b
       )
       """
   )
   ```
2. **Anime Release Regex** (`tokenizer.py`, lines 31-39):
   ```python
   RE_ANIME_RELEASE = re.compile(
       r"""(?ix)
       ^\s*(?:\[(?P<group>[^\]]+)\]\s*)?
       (?P<title>[^\[\]\(\)]+?)\s*-\s*
       (?P<episode>\d{1,4})(?:v\d+)?(?![xX\w])\s*
       (?:\s*(?:\[?[0-9A-Fa-f]{8}\]?|\[(?P<tag>[^\]]+)\]|\((?P<tag_paren>[^\)]+)\))|\s+[A-Za-z0-9_.-]+)*\s*\]?$
       """
   )
   ```
3. **Year Regex** (`tokenizer.py`, line 42):
   ```python
   RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
   ```
4. **Technical Specs Regexes** (`tokenizer.py`, lines 45-50):
   ```python
   RE_RESOLUTION = re.compile(r"\b(2160p|4k|1080p|1080i|720p|576p|480p)\b", re.IGNORECASE)
   RE_DIMENSIONS = re.compile(r"\b(?:\d{3,4})x(?P<height>2160|1080|720|576|480)\b", re.IGNORECASE)
   RE_SOURCE = re.compile(r"\b(bluray|blu-ray|bdrip|web-dl|webrip|web|hdtv|dvdrip|dvd|remux)\b", re.IGNORECASE)
   RE_VIDEO_CODEC = re.compile(r"\b(x265|x264|h\.?265|h\.?264|hevc|avc|av1|xvid|divx)\b", re.IGNORECASE)
   RE_AUDIO_CODEC = re.compile(r"\b(truehd|atmos|dts-hd|dts|flac|aac|ac3|ddp?5\.1|mp3)\b", re.IGNORECASE)
   RE_RELEASE_GROUP = re.compile(r"-([A-Za-z0-9_]+)(?:\[.*?\])?$", re.IGNORECASE)
   ```
5. **Music & Audio Track Regex** (`tokenizer.py`, lines 53-57):
   ```python
   RE_MUSIC_TRACK = re.compile(r"(?ix)^(?P<disc>\d{1,2})[-_.])?(?P<track>\d{1,3})[\.\s_-]+(?P<title>.+)$")
   ```
6. **Date & Camera Stamps Regexes** (`tokenizer.py`, lines 60-72):
   ```python
   RE_CAMERA_DATE = re.compile(
       r"""(?ix)
       (?:img|vid|dsc|pano|mov)?[-_]?(?P<year>19\d{2}|20\d{2})[-_]?(?P<month>\d{2})[-_]?(?P<day>\d{2})
       (?:[-_](?P<hour>\d{2})[-_]?(?P<minute>\d{2})[-_]?(?P<second>\d{2}))?
       """
   )
   RE_PODCAST_DATE = re.compile(
       r"""(?ix)
       ^(?P<show>.+?)\s*-\s*(?P<year>20\d{2})-(?P<month>\d{2})-(?P<day>\d{2})\s*-\s*(?P<title>.+)$
       """
   )
   ```

---

### 1.3 Identified Bugs & Empirical Evidence

The following empirical results were directly reproduced using `.venv/bin/python`:

#### Empirical Finding 1: Left-to-Right `RE_YEAR.search` Corrupts Titles Containing 4-Digit Numbers
When a movie filename contains a 4-digit number in the title (e.g. `1917`, `2001`, `1984`, `2049`, `2077`), `RE_YEAR.search(stem)` in `tokenizer.py:235` matches the *first* number:
- `Blade.Runner.2049.2017.1080p.mkv` -> `title: 'Blade Runner'`, `year: 2049` (lost `2049` from title, assigned wrong year `2049` instead of `2017`).
- `1917.2019.1080p.BluRay.x264.mkv` -> `title: ''`, `year: 1917` (prefix is empty).
  In `namer.py:168`, `tokens.title or src_path.stem` falls back to the entire raw filename stem!
  Destination path: `/organized/Movies/1917.2019.1080p.BluRay.x264 (1917)/1917.2019.1080p.BluRay.x264.mkv`.
- `2001.A.Space.Odyssey.1968.1080p.mkv` -> `title: ''`, `year: 2001` (entire title lost).
- `Wonder.Woman.1984.2020.1080p.mkv` -> `title: 'Wonder Woman'`, `year: 1984`.

#### Empirical Finding 2: Movie Editions and Multi-Part Suffixes are Completely Discarded
- `Blade.Runner.1982.Final.Cut.1080p.mkv` -> `edition` is not in `TokenizedFilename`; `Final Cut` is completely ignored.
- `The.Lord.of.the.Rings.Extended.Edition.2001.1080p.mkv` -> Because the edition is before the year, `prefix` includes `Extended Edition`. Title becomes `'The Lord of the Rings Extended Edition'`, polluting the canonical title.
- Multi-part split files:
  `Titanic.1997.DVD.CD1.avi` -> `dest: /organized/Movies/Titanic (1997)/Titanic.avi`
  `Titanic.1997.DVD.CD2.avi` -> `dest: /organized/Movies/Titanic (1997)/Titanic.avi`
  Both parts resolve to the exact same destination path, causing collision/overwrite!

#### Empirical Finding 3: Season 00 Specials Overwritten into Season 01
In `src/media_sorter/namer.py`, line 164:
```python
season_num = (tokens.season if tokens else 1) or 1
```
Because `0` is falsy in Python, `0 or 1` evaluates to `1`.
When given `Doctor.Who.S00E01.The.Christmas.Invasion.mkv`:
- `tokens.season` is `0`, `tokens.episode` is `1`.
- Line 164 sets `season_num = 1`.
- Destination becomes: `/organized/TV Shows/Doctor Who/Season 01/Doctor Who_S01E01.mkv`.
Season 00 specials are moved into Season 01 and renamed `S01E01`, overwriting or conflicting with the actual Season 1 Episode 1 pilot!

#### Empirical Finding 4: Daily/Dated Shows Classified as Movies and Overwriting Each Other
When given `The.Daily.Show.2024.03.15.1080p.mkv`:
- `RE_SEASON_EPISODE` does not match.
- `RE_PODCAST_DATE` does not match (dots instead of hyphens, no trailing episode title).
- `RE_YEAR` matches `2024`.
- In `classifier.py:364`, `movie_score` reaches `0.40 (base) + 0.35 (year) + 0.15 (1080p) = 0.90`.
- Result: `category="movie"`!
- Destination: `/organized/Movies/The Daily Show (2024)/The Daily Show.mkv`.
Episodes from `2024-03-15`, `2024-03-16`, etc., all map to `/organized/Movies/The Daily Show (2024)/The Daily Show.mkv` and overwrite each other.

#### Empirical Finding 5: Anime Absolute Numbering and Fansub Bracket Failures
- `[SubsPlease] Kaguya-sama (TV) - 05 [1080p].mkv`
  In `tokenizer.py:35`, `RE_ANIME_RELEASE` has `(?P<title>[^\[\]\(\)]+?)\s*-\s*`.
  The character class `[^\[\]\(\)]` forbids `(` and `)`.
  Result: `RE_ANIME_RELEASE` does not match. Fallback title becomes `'Kaguya-sama (TV) - 05 [1080p'` with `episode=None`.
- `[Erai-raws] One Piece (01-12) [1080p] [Batch].mkv`:
  Does not match `RE_ANIME_RELEASE`. Triggers low-confidence quarantine (`confidence=0.70`).
- Anime destination path for `[Erai-raws] One Piece - 1085 [1080p].mkv`:
  Destination: `/organized/Anime/One Piece/Season 01/One Piece_S01E1085 [Erai-raws].mkv`.
  Episode 1085 is assigned to `Season 01` as `S01E1085` instead of `One Piece - 1085.mkv`.

#### Empirical Finding 6: Double Extension Bug in Quarantine Destination
In `src/media_sorter/namer.py`, lines 93-95:
```python
filename = sanitize_filename_component(src_path.name)
rel_str = q_template.format(reason=safe_reason, filename=filename, ext=ext)
```
And `TemplateSettings.quarantine` in `config.py:129`:
`"Quarantine/{reason}/{filename}.{ext}"`
Because `filename` is `src_path.name` (which already includes `.mkv`), formatting `{filename}.{ext}` generates `.mkv.mkv`:
`/organized/Quarantine/Quarantine/Low confidence anime release/[SubsPlease] One Piece (01-12) [1080p] (Batch).mkv.mkv`.

#### Empirical Finding 7: Anime Files Trigger Exception and Silent Drop in Library Indexing
In `src/media_sorter/sorter.py`, lines 274-289:
```python
if cat in ("tv", "anime"):
    try:
        rel_tv = dst_p.relative_to(shows_dir)
        show_title = rel_tv.parts[0]
        dest_folder = str(shows_dir / show_title)
        record_detected_item(session, self.settings, show_title, "tv", destination_folder=dest_folder, delta_count=1)
    except Exception:
        pass
```
When `cat == "anime"`, `dst_p` is located in `/organized/Anime/...`, but `shows_dir` is `/organized/TV Shows`.
`dst_p.relative_to(shows_dir)` raises `ValueError: '/organized/Anime/...' is not in the subpath of '/organized/TV Shows'`.
The exception is swallowed by `except Exception: pass`, and the anime item is never saved to the `library_items` table.
Furthermore, in `library.py:40`, `sync_library_from_disk()` only scans `shows_dir` and `movies_dir`. It never scans `settings.get_destination_path("anime")`.

#### Empirical Finding 8: Subtitle Pairing Asymmetry
In `src/media_sorter/scanner.py`, line 228:
```python
if s_stem == c_stem or s_stem.startswith(c_stem):
    matched_primary = c
```
If a user has `Movie.2023.1080p.mkv` and a clean subtitle `Movie.2023.srt`:
`s_stem` is `"movie.2023"`. `c_stem` is `"movie.2023.1080p"`.
`s_stem.startswith(c_stem)` is False.
`c_stem.startswith(s_stem)` is never checked.
The subtitle is not paired with the movie and becomes an orphaned file.

#### Empirical Finding 9: UnknownGroup Injected into Filenames
In `src/media_sorter/namer.py`, line 187:
```python
"group": (tokens.group if tokens else "UnknownGroup") or "UnknownGroup",
```
When `tokens.group` is None, `_build_context` populates `"UnknownGroup"`.
Template `anime: str = "{title}/Season {season:02d}/{show_name}_{season_episode} [{group}].{ext}"`
renders: `Show_S01E01 [UnknownGroup].mkv`.
Although `_render_template` lines 258-259 has logic to clean empty brackets (`re.sub(r"\[\s*\]", "", rendered)`), line 187 defeats it by ensuring `group` is never empty.

---

## 2. Logic Chain

1. **Movie Parsing Logic**:
   - `RE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")` searches left-to-right from the beginning of the filename.
   - When titles include historical dates (`1917`, `2001`, `1984`) or futuristic years (`2049`, `2077`), the first occurrence matches.
   - The tokenization splits at `yr_m.start()`, leaving an empty prefix or truncating the actual title.
   - Suffix parsing only extracts `RE_RELEASE_GROUP`. Editions (`Extended`, `Director's Cut`, `Remastered`) and part indicators (`CD1`, `pt1`) are neither recognized nor modeled in `TokenizedFilename`.
   - Therefore, multi-part files map to identical destination strings, and editions cannot be placed into `[Edition]` tags in compliance with Plex/Kodi conventions.

2. **TV Show Parsing Logic**:
   - `RE_SEASON_EPISODE` requires an episode number in all branches.
   - Season packs (`Season 01`, `S01 Complete`, `Season 1-3 Complete`) lack episode numbers and fail `RE_SEASON_EPISODE`.
   - Specials (`S00E01`, `OVA`, `Special`) either fail to match or match with `season=0`. In `namer.py:164`, Python's falsy evaluation of `0` in `(tokens.season or 1)` transforms `season=0` into `season=1`.
   - Daily shows (`2024.03.15`, `2024-03-15`) contain a year but no episode tag. `classifier.py` calculates `movie_score >= 0.75` based on the year and resolution tags, misclassifying daily TV broadcasts as movies.

3. **Anime Parsing Logic**:
   - `RE_ANIME_RELEASE` relies on `(?P<title>[^\[\]\(\)]+?)\s*-\s*(?P<episode>\d{1,4})`.
   - The exclusion of `()` causes any anime title with parentheses (e.g. `(TV)`, `(2023)`) to fail matching.
   - The pattern requires a hyphen followed immediately by digits; anime with cour names (`DanMachi 4th Season - 11`) or batch tags (`[Batch]`) fail.
   - `classifier.py` relies on hardcoded string checks for 4 fansub groups (`horriblesubs`, `subsplease`, `judas`, `erai-raws`). Releases from other groups (e.g. `Golumpa`, `ASAP`, `Yameii`, `Commie`) with absolute numbering fail if syntax match fails.
   - `MediaNamer` has no token for absolute episodes (`{absolute_episode}` or `{episode_abs}`), forcing anime into `Season 01` with `S01E1085`.

4. **Normalization & Tag Stripping Logic**:
   - `_clean_title()` in `tokenizer.py:249` only strips leading brackets and replaces dots/underscores. It does not strip resolution, audio codecs, or edition tokens from titles when year matching fails.
   - Redundant and conflicting title cleaners exist across `server.py:147` (`clean_detected_show_name`), `server.py:264` (`extract_clean_stem`), `library.py:25` (`clean_show_title`), and `tokenizer.py:249` (`_clean_title`).
   - Normalization regexes lack modern codecs and specs: `10bit`, `HDR`, `HDR10+`, `DV`, `DDP5.1`, `EAC3`, `Opus`, `UHD`.

5. **Routing & Library Synchronization Logic**:
   - `sorter.py` hardcodes `dst_p.relative_to(shows_dir)` for all TV and Anime operations.
   - Because `Settings.storage.destination_dirs.anime` defaults to `"Anime"`, anime files are not descendants of `shows_dir`, throwing an unhandled `ValueError` that is caught and suppressed.
   - `LibraryItem` table schema and `library.py` only support categories `"tv"` and `"movie"`. Anime entries cannot be properly indexed or retrieved via `/api/library`.

---

## 3. Caveats

1. **Read-Only Investigation**: Source files were inspected and empirically analyzed via external non-mutating python runs; no production or test files were modified.
2. **Library Schema Migration**: Adding an `"anime"` category to `LibraryItem` in `models.py` must consider database backward compatibility (e.g. existing SQLite tables with `CHECK` constraints or unique constraints `(title, category)`).
3. **Roman Numerals vs Series Suffixes**: Differentiating between movie titles with roman numerals (e.g. `The Godfather Part II`, `Final Fantasy VII`) and episodic/split indicators (e.g. `Part 2`, `CD2`) requires contextual awareness of whether the token precedes or follows the release year.
4. **Year Ranges**: Detection of 4-digit numbers as years must remain bounded (typically `1900 <= year <= current_year + 2`) to avoid confusing bitrates (`2500k`), dimensions (`1920x1080`), or episode numbers (`1085`).

---

## 4. Conclusion & Recommendations

To satisfy Requirements R1, R2, and R3, the following concrete improvements are recommended:

### 4.1 Data Structure Extensions

1. **`MediaType` Enum** (New in `models.py` and `config.py`):
   ```python
   class MediaType(str, Enum):
       MOVIE = "movie"
       TV = "tv"
       ANIME = "anime"
       MUSIC = "music"
       AUDIOBOOK = "audiobook"
       PODCAST = "podcast"
       HOME_VIDEO = "home_video"
       PHOTO = "photo"
       ARCHIVE = "archive"
       SUBTITLE = "subtitle"
       ARTWORK = "artwork"
       METADATA = "metadata"
       UNKNOWN = "unknown"
   ```
2. **`TokenizedFilename` Extensions** (`tokenizer.py`):
   ```python
   @dataclass
   class TokenizedFilename:
       raw_name: str
       title: Optional[str] = None
       year: Optional[int] = None
       season: Optional[int] = None
       episode: Optional[int] = None
       multi_episodes: List[int] = field(default_factory=list)
       episode_title: Optional[str] = None
       edition: Optional[str] = None           # "Director's Cut", "Extended", "Remastered", "Criterion", etc.
       part: Optional[int] = None              # 1, 2 (for multi-part / split movie files)
       part_label: Optional[str] = None        # "CD1", "pt1", "Part 1"
       is_season_pack: bool = False            # True for Season 01, S01 Complete, etc.
       season_pack_seasons: List[int] = field(default_factory=list)
       is_special: bool = False                # True for S00Exx, OVA, SP, Special
       special_type: Optional[str] = None      # "OVA", "SP", "Special", "OAV"
       is_daily: bool = False                  # True for daily dated shows (2024-03-15)
       absolute_episode: Optional[int] = None  # 1085 (for anime absolute numbering)
       version: Optional[int] = None           # 2 for v2
       crc32: Optional[str] = None             # ABCD1234
       hdr: Optional[str] = None               # "HDR", "HDR10+", "DV"
       audio_channels: Optional[str] = None    # "5.1", "7.1", "2.0"
       ...
   ```

### 4.2 Pattern Matching & Regex Enhancements

1. **Movie Release Year Regex**:
   Instead of left-to-right `RE_YEAR.search(stem)`, match year right-to-left or before known technical tags/edition tokens:
   ```python
   # Explicit year in parentheses e.g. "Title (2023)"
   RE_PAREN_YEAR = re.compile(r"\((19\d{2}|20\d{2})\)")
   # Year preceding quality tags or end of stem
   RE_SCENE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b(?=[.\s_-]+(?:2160p|1080p|720p|4k|bluray|web|remux|edition|director|extended|x264|x265|hevc|dvd)\b|\s*$)", re.I)
   ```
2. **Movie Edition Regex**:
   ```python
   RE_EDITION = re.compile(
       r"(?ix)\b("
       r"director(?:'?s)?(?:\s+cut)?"
       r"|extended(?:\s+edition|\s+cut)?"
       r"|theatrical(?:\s+cut)?"
       r"|remastered"
       r"|criterion(?:\s+collection)?"
       r"|unrated(?:\s+cut)?"
       r"|ultimate(?:\s+edition)?"
       r"|special\s+edition"
       r"|anniversary(?:\s+edition)?"
       r"|imax(?:\s+edition)?"
       r"|final\s+cut"
       r"|open\s+matte"
       r"|uncut"
       r")\b"
   )
   ```
3. **Multi-Part Split Files Regex**:
   ```python
   RE_MOVIE_PART = re.compile(r"(?ix)\b(?:cd|disc|disk|part|pt)[\.\s_-]*(?P<part>\d{1,2})\b")
   ```
4. **Daily / Dated Show Regex**:
   ```python
   RE_DAILY_DATE = re.compile(r"(?ix)\b(?P<year>19\d{2}|20\d{2})[\.\s_-]+(?P<month>0[1-9]|1[0-2])[\.\s_-]+(?P<day>0[1-9]|[12]\d|3[01])\b")
   ```
5. **Specials & OVAs Regex**:
   ```python
   RE_SPECIAL = re.compile(r"(?ix)\b(?:s00[\.\s_-]*(?:e|ep)(?P<special_ep>\d{1,3})|(?:special|ova|oav|sp)[\.\s_-]*(?P<special_num>\d{1,3})?)\b")
   ```
6. **Season Packs Regex**:
   ```python
   RE_SEASON_PACK = re.compile(
       r"(?ix)\b(?:season|series|s)\s*(?P<season_start>\d{1,2})"
       r"(?:[\s._-]*(?:-|to|through)[\s._]*(?:season|series|s)?\s*(?P<season_end>\d{1,2}))?\b"
       r"(?:\s*complete)?(?!\s*(?:e|ep|x|\d{1,3}))"
   )
   ```
7. **Robust Anime Fansub Regex**:
   Allow parentheses in titles and cour markers:
   ```python
   RE_ANIME_RELEASE = re.compile(
       r"""(?ix)
       ^\s*(?:\[(?P<group>[^\]]+)\]\s*)?
       (?P<title>.+?)\s+-\s+
       (?P<episode>\d{1,4})(?:v(?P<version>\d+))?(?![xX\w])\s*
       (?:\s*(?:\[(?P<crc>[0-9A-Fa-f]{8})\]|\[(?P<tag>[^\]]+)\]|\((?P<tag_paren>[^\)]+)\))|\s+[A-Za-z0-9_.-]+)*$
       """
   )
   ```
8. **Comprehensive Technical Tag Stripping & Normalization**:
   Expand audio/video codecs to include: `10bit`, `hdr`, `hdr10`, `hdr10+`, `dv`, `dolby vision`, `ddp`, `dd+`, `eac3`, `opus`, `vorbis`, `7.1`, `5.1`, `remux`, `proper`, `repack`.
   Consolidate title cleaning into a single shared utility (`normalize_media_title`) to replace divergent logic in `server.py`, `library.py`, and `tokenizer.py`.

### 4.3 Destination Path Routing Recommendations

1. **Season 00 Specials**:
   Fix line 164 in `src/media_sorter/namer.py`:
   ```python
   season_num = tokens.season if (tokens and tokens.season is not None) else 1
   ```
   If `season_num == 0`:
   Format folder as `Season 00` (or `Specials`) and filename as `S00E{episode:02d}`.
2. **Multi-Episode Formatting**:
   If `tokens.multi_episodes`:
   Format `season_episode` as `S{season:02d}E{ep1:02d}-E{ep2:02d}` (e.g. `S04E01-E02`).
3. **Anime Absolute Ordering Support**:
   In `MediaNamer._build_context`:
   Provide `abs_episode = f"{tokens.absolute_episode:02d}" if tokens.absolute_episode else f"{episode_num:02d}"`.
   Support template: `{title}/{show_name} - {abs_episode} [{group}].{ext}` or `{title}/Season {season:02d}/{show_name} - S{season:02d}E{episode:02d}.{ext}`.
4. **Fix Quarantine Double Extension**:
   In `src/media_sorter/namer.py`, line 93:
   Use `src_path.stem` instead of `src_path.name`, or sanitize the stem so formatting `{filename}.{ext}` does not duplicate `.mkv.mkv`.
5. **Fix Anime Library Recording in `sorter.py`**:
   In `src/media_sorter/sorter.py:274`, check destination relative to `settings.get_destination_path("anime")` when `cat == "anime"`, and record `category="anime"` in `library_items`.
6. **Fix Subtitle Pairing in `scanner.py`**:
   In `src/media_sorter/scanner.py:228`, allow bidirectional prefix matching:
   ```python
   if s_stem == c_stem or s_stem.startswith(c_stem) or c_stem.startswith(s_stem):
       matched_primary = c
   ```

---

## 5. Verification Method

### 5.1 Test Suite Verification
Run the existing automated test suite using the project virtual environment:
```bash
.venv/bin/pytest tests/
```
Expected output: 75 passed.

### 5.2 Specific Code Locations for Verification
1. `src/media_sorter/tokenizer.py`:
   - Lines 16-29: `RE_SEASON_EPISODE`
   - Lines 31-39: `RE_ANIME_RELEASE`
   - Line 42: `RE_YEAR`
   - Lines 75-98: `TokenizedFilename`
   - Lines 148-169: Anime release parsing
   - Lines 171-215: TV episodic parsing
   - Lines 234-247: Movie year and title fallback
   - Lines 249-256: `_clean_title`
2. `src/media_sorter/classifier.py`:
   - Lines 283-307: Anime scoring & hardcoded group list
   - Lines 312-361: TV show scoring & duration checks
   - Lines 363-404: Movie scoring & quarantine triggers
3. `src/media_sorter/namer.py`:
   - Line 93: Quarantine filename doubling bug (`src_path.name` + `.{ext}`)
   - Line 164: `(tokens.season or 1)` falsy bug turning Season 0 into Season 1
   - Line 166: `season_ep_str` ignoring `multi_episodes`
   - Line 187: `"UnknownGroup"` default defeating bracket stripping
4. `src/media_sorter/sorter.py`:
   - Lines 274-289: `rel_tv = dst_p.relative_to(shows_dir)` throwing `ValueError` on anime paths
5. `src/media_sorter/scanner.py`:
   - Line 228: Subtitle stem pairing asymmetry
6. `src/media_sorter/library.py`:
   - Lines 40-154: `sync_library_from_disk` ignoring `anime_dir`
   - Lines 167-170: `record_detected_item` dropping non-`tv`/`movie` categories

### 5.3 Invalidation Conditions
This report's findings would be invalidated if:
- Media Sorter moves to an external third-party parsing library (e.g. `guessit`) that replaces all regex logic.
- The project deprecates distinct Anime routing and merges all TV and Anime into a unified directory structure.
