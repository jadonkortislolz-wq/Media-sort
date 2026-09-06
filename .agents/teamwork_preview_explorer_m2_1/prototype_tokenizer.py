import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field

# Import original classes
import sys
sys.path.insert(0, "/md0/media-sorter")
from media_sorter.tokenizer import (
    TokenizedFilename,
    RE_RESOLUTION,
    RE_DIMENSIONS,
    RE_SOURCE,
    RE_VIDEO_CODEC,
    RE_AUDIO_CODEC,
    RE_RELEASE_GROUP,
    RE_MUSIC_TRACK,
    RE_CAMERA_DATE,
    RE_PODCAST_DATE,
)
from tests.benchmark.benchmark_cases import BENCHMARK_CASES

print("Imported successfully")
