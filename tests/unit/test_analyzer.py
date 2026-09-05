import struct
from pathlib import Path
import pytest
from media_sorter.analyzer import MediaAnalyzer


@pytest.fixture
def analyzer():
    return MediaAnalyzer()


def test_flac_metadata_extraction(tmp_path: Path, analyzer):
    flac_file = tmp_path / "test.flac"
    # Create minimal synthetic FLAC file
    header = bytearray(b"fLaC")
    # STREAMINFO block (type 0, length 34, not last: block_hdr = 0x00 0x00 0x00 0x22)
    streaminfo_data = bytearray(34)
    # sample_rate = 44100, channels = 2, total_samples = 44100 * 10
    # byte 10..12: sample rate
    streaminfo_data[10] = (44100 >> 12) & 0xFF
    streaminfo_data[11] = (44100 >> 4) & 0xFF
    streaminfo_data[12] = ((44100 & 0x0F) << 4) | (1 << 1)  # 2 channels (bits 1..3 = 1)
    # total samples = 441000
    total_samples = 441000
    streaminfo_data[13] = (total_samples >> 32) & 0x0F
    streaminfo_data[14] = (total_samples >> 24) & 0xFF
    streaminfo_data[15] = (total_samples >> 16) & 0xFF
    streaminfo_data[16] = (total_samples >> 8) & 0xFF
    streaminfo_data[17] = total_samples & 0xFF

    header.extend(b"\x80\x00\x00\x22")  # is_last = 1, type = 0, len = 34
    header.extend(streaminfo_data)
    flac_file.write_bytes(header)

    meta = analyzer.analyze(flac_file)
    assert meta.container == "flac"
    assert meta.has_audio is True
    assert meta.duration_seconds == 10.0


def test_mp3_id3v2_extraction(tmp_path: Path, analyzer):
    mp3_file = tmp_path / "test.mp3"
    header = bytearray(b"ID3\x03\x00\x00")  # ID3v2.3
    # Build TIT2 frame (Title: Bohemian Rhapsody)
    tit2_val = b"\x00Bohemian Rhapsody"
    tit2_frame = b"TIT2" + struct.pack(">I", len(tit2_val)) + b"\x00\x00" + tit2_val
    # Build TPE1 frame (Artist: Queen)
    tpe1_val = b"\x00Queen"
    tpe1_frame = b"TPE1" + struct.pack(">I", len(tpe1_val)) + b"\x00\x00" + tpe1_val

    tag_content = tit2_frame + tpe1_frame
    tag_len = len(tag_content)
    # Syncsafe integer for tag size
    b0 = (tag_len >> 21) & 0x7F
    b1 = (tag_len >> 14) & 0x7F
    b2 = (tag_len >> 7) & 0x7F
    b3 = tag_len & 0x7F
    header.extend(bytes([b0, b1, b2, b3]))
    header.extend(tag_content)
    # Add dummy MP3 frame sync bytes
    header.extend(b"\xff\xfb\x90\x00")
    mp3_file.write_bytes(header)

    meta = analyzer.analyze(mp3_file)
    assert meta.container == "mp3"
    assert meta.has_audio is True
    assert meta.tags.get("title") == "Bohemian Rhapsody"
    assert meta.tags.get("artist") == "Queen"


def test_jpeg_exif_extraction(tmp_path: Path, analyzer):
    jpg_file = tmp_path / "test.jpg"
    # SOI marker + APP1 marker with Exif
    soi = b"\xff\xd8"
    exif_header = b"Exif\x00\x00"
    tiff_header = b"II\x2a\x00\x08\x00\x00\x00"  # Little endian, IFD at 8
    # 1 entry in IFD0: DateTimeOriginal (tag 0x9003)
    num_entries = struct.pack("<H", 1)
    tag_id = struct.pack("<H", 0x9003)
    type_ascii = struct.pack("<H", 2)
    count = struct.pack("<I", 20)
    val_offset = struct.pack("<I", 22)  # offset from tiff_header
    dt_str = b"2025:06:15 10:30:00\x00"

    tiff_body = tiff_header + num_entries + tag_id + type_ascii + count + val_offset + dt_str
    app1_len = struct.pack(">H", len(exif_header) + len(tiff_body) + 2)
    app1 = b"\xff\xe1" + app1_len + exif_header + tiff_body

    jpg_file.write_bytes(soi + app1)

    meta = analyzer.analyze(jpg_file)
    assert meta.container == "jpeg"
    assert meta.tags.get("datetime_original") == "2025:06:15 10:30:00"


def test_png_dimensions(tmp_path: Path, analyzer):
    png_file = tmp_path / "test.png"
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 13 bytes data (width=1920, height=1080)
    ihdr_data = struct.pack(">IIBBBBB", 1920, 1080, 8, 2, 0, 0, 0)
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + b"\x00\x00\x00\x00"
    png_file.write_bytes(sig + ihdr)

    meta = analyzer.analyze(png_file)
    assert meta.container == "png"
    assert meta.width == 1920
    assert meta.height == 1080
    assert meta.resolution_label == "1080p"


def test_archive_detection(tmp_path: Path, analyzer):
    zip_file = tmp_path / "test.zip"
    zip_file.write_bytes(b"PK\x03\x04\x14\x00\x00\x00")
    meta = analyzer.analyze(zip_file)
    assert meta.container == "zip"
    assert meta.mime_type == "application/zip"
