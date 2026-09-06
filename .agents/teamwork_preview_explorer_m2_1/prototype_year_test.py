import re
from pathlib import Path

test_cases = [
    ("1917.2019.1080p.BluRay.x264.mkv", "1917", 2019),
    ("2001.A.Space.Odyssey.1968.REMASTERED.1080p.mkv", "2001 A Space Odyssey", 1968),
    ("Blade.Runner.2049.2017.2160p.UHD.BluRay.x265.mkv", "Blade Runner 2049", 2017),
    ("Wonder.Woman.1984.2020.1080p.WEB-DL.mkv", "Wonder Woman 1984", 2020),
    ("Class.of.1999.1990.720p.mkv", "Class of 1999", 1990),
    ("Kill.Bill.Vol.1.2003.1080p.BluRay.mkv", "Kill Bill Vol 1", 2003),
    ("Inception.2010.1080p.BluRay.x264-FraMeSToR.mkv", "Inception", 2010),
    ("Seven.Samurai.1954.Criterion.Collection.1080p.BluRay.mkv", "Seven Samurai", 1954),
    ("Interstellar.1920x1080.mkv", "Interstellar", None),
]

RE_YEAR_BOUND = re.compile(r"(?<![0-9a-zA-Z])(19\d{2}|20\d{2})(?![0-9a-zA-Z])")
RE_TECH = re.compile(r"(?i)\b(2160p|4k|1080p|1080i|720p|576p|480p|bluray|blu-ray|bdrip|web-dl|webrip|web|hdtv|dvdrip|dvd|remux|remastered|extended|directors\.cut|criterion|final\.cut|x265|x264|hevc|avc)\b")

def extract_movie_year_and_title(stem: str):
    # Check parenthesized year first: Title (2020)
    m_paren = re.search(r"\((19\d{2}|20\d{2})\)", stem)
    if m_paren:
        year = int(m_paren.group(1))
        prefix = stem[:m_paren.start()]
        title = re.sub(r"[\._]+", " ", prefix).strip(" -")
        return title, year

    # Find tech specs boundary
    tech_start = len(stem)
    for m in RE_TECH.finditer(stem):
        if m.start() < tech_start:
            tech_start = m.start()

    # Search year candidates up to tech_start or in full stem
    # Find all year matches
    matches = list(RE_YEAR_BOUND.finditer(stem))
    if not matches:
        # No year
        # Strip tech specs if any
        prefix = stem[:tech_start].strip(" .-_")
        title = re.sub(r"[\._]+", " ", prefix).strip(" -")
        return title, None

    # Filter matches: if there are matches before tech_start, use the rightmost match
    valid_matches = [m for m in matches if m.start() <= tech_start]
    if not valid_matches:
        valid_matches = matches

    # Take rightmost match
    best_match = valid_matches[-1]
    year = int(best_match.group(1))
    prefix = stem[:best_match.start()]
    title = re.sub(r"[\._]+", " ", prefix).strip(" -")
    return title, year

print("Testing extract_movie_year_and_title:")
for filename, exp_title, exp_year in test_cases:
    stem = Path(filename).stem
    act_title, act_year = extract_movie_year_and_title(stem)
    status = "OK" if (act_title == exp_title and act_year == exp_year) else "FAIL"
    print(f"[{status}] {filename}")
    print(f"    Title: exp={exp_title!r} act={act_title!r}")
    print(f"    Year:  exp={exp_year!r} act={act_year!r}")
