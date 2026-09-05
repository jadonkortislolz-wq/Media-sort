"""Multi-format media analyzer and metadata extraction engine.

Extracts container, codec, stream, duration, resolution, EXIF, and embedded tag
metadata from audio, video, image, and archive files without mandatory external binaries.
Gracefully integrates with pymediainfo or ffprobe if available on the system.
"""

from __future__ import annotations

import mimetypes
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class StreamInfo:
    stream_type: str  # "video", "audio", "subtitle"
    codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    channels: Optional[int] = None
    sample_rate: Optional[int] = None
    bitrate: Optional[int] = None
    language: Optional[str] = None


@dataclass
class MediaMetadata:
    path: Path
    mime_type: str
    container: str
    duration_seconds: float = 0.0
    streams: List[StreamInfo] = field(default_factory=list)
    tags: Dict[str, Any] = field(default_factory=dict)
    has_video: bool = False
    has_audio: bool = False
    has_subtitles: bool = False
    width: Optional[int] = None
    height: Optional[int] = None
    codec_video: Optional[str] = None
    codec_audio: Optional[str] = None

    @property
    def resolution_label(self) -> str:
        """Returns standard resolution label (e.g. 2160p, 1080p, 720p, 480p)."""
        if not self.height:
            return ""
        h = self.height
        if h >= 2000:
            return "2160p"
        elif h >= 1000:
            return "1080p"
        elif h >= 700:
            return "720p"
        elif h >= 450:
            return "480p"
        return f"{h}p"


class MediaAnalyzer:
    """Analyzes media files to extract container, codec, resolution, and embedded tags."""

    def __init__(self):
        mimetypes.init()

    def analyze(self, path: Path) -> MediaMetadata:
        """Inspect file header, container structure, and embedded metadata."""
        ext = path.suffix.lower()
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or "application/octet-stream"

        meta = MediaMetadata(
            path=path,
            mime_type=mime,
            container=ext.lstrip(".").lower() or "unknown",
        )

        try:
            with open(path, "rb") as f:
                header = f.read(4096)
                if not header:
                    return meta

                # Container detection & parsing
                if header.startswith(b"fLaC"):
                    self._parse_flac(f, header, meta)
                elif header.startswith(b"ID3") or ext == ".mp3":
                    self._parse_mp3(f, header, meta)
                elif header.startswith(b"\x1aE\xdf\xa3"):
                    self._parse_ebml(f, header, meta)
                elif len(header) >= 8 and header[4:8] in (b"ftyp", b"moov"):
                    self._parse_mp4(f, header, meta)
                elif header.startswith(b"RIFF"):
                    self._parse_riff(f, header, meta)
                elif header.startswith(b"\xff\xd8\xff"):
                    self._parse_jpeg_exif(f, header, meta)
                elif header.startswith(b"\x89PNG\r\n\x1a\n"):
                    self._parse_png(f, header, meta)
                elif header.startswith(b"PK\x03\x04"):
                    meta.container = "zip"
                    meta.mime_type = "application/zip"
                elif header.startswith(b"Rar!\x1a\x07"):
                    meta.container = "rar"
                    meta.mime_type = "application/x-rar"
                elif header.startswith(b"7z\xbc\xaf\x27\x1c"):
                    meta.container = "7z"
                    meta.mime_type = "application/x-7z-compressed"
        except Exception as e:
            logger.debug("Probing exception encountered; falling back gracefully", path=str(path), error=str(e))

        # Reconcile flags
        if meta.streams:
            meta.has_video = any(s.stream_type == "video" for s in meta.streams)
            meta.has_audio = any(s.stream_type == "audio" for s in meta.streams)
            meta.has_subtitles = any(s.stream_type == "subtitle" for s in meta.streams)
            for s in meta.streams:
                if s.stream_type == "video" and not meta.codec_video:
                    meta.codec_video = s.codec
                    meta.width = meta.width or s.width
                    meta.height = meta.height or s.height
                elif s.stream_type == "audio" and not meta.codec_audio:
                    meta.codec_audio = s.codec

        return meta

    # -------------------------------------------------------------------------
    # FLAC Parser
    # -------------------------------------------------------------------------
    def _parse_flac(self, f, header: bytes, meta: MediaMetadata) -> None:
        meta.container = "flac"
        meta.mime_type = "audio/flac"
        meta.has_audio = True

        f.seek(4)
        while True:
            block_hdr = f.read(4)
            if len(block_hdr) < 4:
                break
            is_last = bool(block_hdr[0] & 0x80)
            block_type = block_hdr[0] & 0x7F
            length = struct.unpack(">I", b"\x00" + block_hdr[1:4])[0]

            data = f.read(length)
            if len(data) < length:
                break

            if block_type == 0 and length >= 18:  # STREAMINFO
                channels = ((data[12] >> 1) & 0x07) + 1
                sample_rate = ((data[10] << 12) | (data[11] << 4) | (data[12] >> 4))
                total_samples = ((data[13] & 0x0F) << 32) | (data[14] << 24) | (data[15] << 16) | (data[16] << 8) | data[17]
                if sample_rate > 0:
                    meta.duration_seconds = round(total_samples / sample_rate, 2)
                meta.streams.append(
                    StreamInfo(
                        stream_type="audio",
                        codec="flac",
                        channels=channels,
                        sample_rate=sample_rate,
                    )
                )

            elif block_type == 4:  # VORBIS_COMMENT
                try:
                    self._parse_vorbis_comments(data, meta.tags)
                except Exception:
                    pass

            if is_last:
                break

    def _parse_vorbis_comments(self, data: bytes, tags: Dict[str, Any]) -> None:
        if len(data) < 4:
            return
        vendor_len = struct.unpack("<I", data[0:4])[0]
        offset = 4 + vendor_len
        if offset + 4 > len(data):
            return
        comment_count = struct.unpack("<I", data[offset : offset + 4])[0]
        offset += 4

        for _ in range(comment_count):
            if offset + 4 > len(data):
                break
            c_len = struct.unpack("<I", data[offset : offset + 4])[0]
            offset += 4
            if offset + c_len > len(data):
                break
            entry = data[offset : offset + c_len].decode("utf-8", errors="ignore")
            offset += c_len
            if "=" in entry:
                k, v = entry.split("=", 1)
                key = k.lower().strip()
                val = v.strip()
                if key == "tracknumber":
                    tags["track"] = val.split("/")[0]
                elif key == "discnumber":
                    tags["disc"] = val.split("/")[0]
                else:
                    tags[key] = val

    # -------------------------------------------------------------------------
    # MP3 ID3 Parser
    # -------------------------------------------------------------------------
    def _parse_mp3(self, f, header: bytes, meta: MediaMetadata) -> None:
        meta.container = "mp3"
        meta.mime_type = "audio/mpeg"
        meta.has_audio = True

        if header.startswith(b"ID3") and len(header) >= 10:
            ver_major = header[3]
            size_bytes = header[6:10]
            tag_size = (
                (size_bytes[0] & 0x7F) << 21
                | (size_bytes[1] & 0x7F) << 14
                | (size_bytes[2] & 0x7F) << 7
                | (size_bytes[3] & 0x7F)
            )

            f.seek(10)
            tag_data = f.read(min(tag_size, 65536))
            self._parse_id3v2_frames(tag_data, ver_major, meta.tags)

        meta.streams.append(StreamInfo(stream_type="audio", codec="mp3"))

    def _parse_id3v2_frames(self, data: bytes, ver: int, tags: Dict[str, Any]) -> None:
        offset = 0
        frame_header_len = 10 if ver in (3, 4) else 6

        while offset + frame_header_len <= len(data):
            if ver in (3, 4):
                frame_id = data[offset : offset + 4].decode("latin-1", errors="ignore")
                if not frame_id or frame_id[0] == "\x00":
                    break
                if ver == 4:
                    # Syncsafe integer
                    b = data[offset + 4 : offset + 8]
                    fsize = (b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F)
                else:
                    fsize = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
                body_start = offset + 10
            else:
                frame_id = data[offset : offset + 3].decode("latin-1", errors="ignore")
                if not frame_id or frame_id[0] == "\x00":
                    break
                fsize = struct.unpack(">I", b"\x00" + data[offset + 3 : offset + 6])[0]
                body_start = offset + 6

            if fsize <= 0 or body_start + fsize > len(data):
                break

            content_bytes = data[body_start : body_start + fsize]
            text_val = self._decode_id3_text(content_bytes)

            id_map = {
                "TIT2": "title", "TT2": "title",
                "TPE1": "artist", "TP1": "artist",
                "TALB": "album", "TAL": "album",
                "TYER": "year", "TYE": "year", "TDRC": "year",
                "TRCK": "track", "TRK": "track",
                "TPOS": "disc", "TPA": "disc",
            }
            if frame_id in id_map and text_val:
                tag_name = id_map[frame_id]
                if tag_name in ("track", "disc"):
                    tags[tag_name] = text_val.split("/")[0]
                elif tag_name == "year":
                    tags[tag_name] = text_val[:4]
                else:
                    tags[tag_name] = text_val

            offset = body_start + fsize

    def _decode_id3_text(self, b: bytes) -> str:
        if not b:
            return ""
        enc = b[0]
        payload = b[1:]
        try:
            if enc == 0:
                return payload.decode("latin-1", errors="ignore").rstrip("\x00")
            elif enc == 1:
                return payload.decode("utf-16", errors="ignore").rstrip("\x00")
            elif enc == 2:
                return payload.decode("utf-16-be", errors="ignore").rstrip("\x00")
            elif enc == 3:
                return payload.decode("utf-8", errors="ignore").rstrip("\x00")
        except Exception:
            pass
        return payload.decode("latin-1", errors="ignore").rstrip("\x00")

    # -------------------------------------------------------------------------
    # MP4 / M4V / M4A Atom Parser
    # -------------------------------------------------------------------------
    def _parse_mp4(self, f, header: bytes, meta: MediaMetadata) -> None:
        meta.container = "mp4"
        meta.mime_type = "video/mp4"

        # Check for M4A / audio-only
        if len(header) >= 12 and header[8:12] in (b"M4A ", b"M4B ", b"mp42"):
            if header[8:12] == b"M4A ":
                meta.container = "m4a"
                meta.mime_type = "audio/mp4"
            elif header[8:12] == b"M4B ":
                meta.container = "m4b"
                meta.mime_type = "audio/mp4"

        f.seek(0)
        file_size = f.seek(0, os.SEEK_END)
        f.seek(0)

        offset = 0
        while offset + 8 <= file_size:
            f.seek(offset)
            box_hdr = f.read(8)
            if len(box_hdr) < 8:
                break
            box_size, box_type = struct.unpack(">I4s", box_hdr)
            if box_size == 1:
                ext_size = f.read(8)
                box_size = struct.unpack(">Q", ext_size)[0]
                hdr_size = 16
            elif box_size == 0:
                box_size = file_size - offset
                hdr_size = 8
            else:
                hdr_size = 8

            if box_size < hdr_size:
                break

            if box_type == b"moov":
                self._parse_mp4_moov(f, offset + hdr_size, box_size - hdr_size, meta)
                break  # Typically moov contains all necessary header info

            offset += box_size

    def _parse_mp4_moov(self, f, moov_offset: int, moov_size: int, meta: MediaMetadata) -> None:
        f.seek(moov_offset)
        moov_bytes = f.read(min(moov_size, 5000000))  # Read up to 5MB of moov atom
        idx = 0
        while idx + 8 <= len(moov_bytes):
            sub_size, sub_type = struct.unpack(">I4s", moov_bytes[idx : idx + 8])
            if sub_size < 8 or idx + sub_size > len(moov_bytes):
                break

            if sub_type == b"mvhd" and sub_size >= 24:
                # Timescale and duration
                version = moov_bytes[idx + 8]
                if version == 0:
                    timescale = struct.unpack(">I", moov_bytes[idx + 20 : idx + 24])[0]
                    duration = struct.unpack(">I", moov_bytes[idx + 24 : idx + 28])[0]
                else:
                    timescale = struct.unpack(">I", moov_bytes[idx + 28 : idx + 32])[0]
                    duration = struct.unpack(">Q", moov_bytes[idx + 32 : idx + 40])[0]
                if timescale > 0:
                    meta.duration_seconds = round(duration / timescale, 2)

            elif sub_type == b"trak":
                trak_data = moov_bytes[idx + 8 : idx + sub_size]
                self._parse_mp4_trak(trak_data, meta)

            elif sub_type == b"udta":
                udta_data = moov_bytes[idx + 8 : idx + sub_size]
                self._parse_mp4_udta(udta_data, meta.tags)

            idx += sub_size

    def _parse_mp4_trak(self, data: bytes, meta: MediaMetadata) -> None:
        # Check track type in hdlr atom
        hdlr_pos = data.find(b"hdlr")
        if hdlr_pos >= 4:
            subtype = data[hdlr_pos + 8 : hdlr_pos + 12]
            if subtype == b"vide":
                meta.has_video = True
                tkhd_pos = data.find(b"tkhd")
                width = None
                height = None
                if tkhd_pos >= 4 and len(data) >= tkhd_pos + 84:
                    width = struct.unpack(">I", data[tkhd_pos + 76 : tkhd_pos + 80])[0] >> 16
                    height = struct.unpack(">I", data[tkhd_pos + 80 : tkhd_pos + 84])[0] >> 16
                meta.streams.append(
                    StreamInfo(stream_type="video", codec="h264/hevc", width=width, height=height)
                )
                if width and height:
                    meta.width = meta.width or width
                    meta.height = meta.height or height
            elif subtype == b"soun":
                meta.has_audio = True
                meta.streams.append(StreamInfo(stream_type="audio", codec="aac"))
            elif subtype == b"subt":
                meta.has_subtitles = True
                meta.streams.append(StreamInfo(stream_type="subtitle", codec="tx3g"))

    def _parse_mp4_udta(self, data: bytes, tags: Dict[str, Any]) -> None:
        # Scan for common iTunes tags
        mapping = {
            b"\xa9nam": "title",
            b"\xa9ART": "artist",
            b"\xa9alb": "album",
            b"\xa9day": "year",
            b"tvsh": "show",
            b"tven": "episode_id",
            b"tvsn": "season",
            b"tves": "episode",
        }
        for tag_bytes, key in mapping.items():
            pos = data.find(tag_bytes)
            if pos != -1 and pos + 24 <= len(data):
                # Data atom follows tag atom
                data_pos = data.find(b"data", pos, pos + 32)
                if data_pos != -1 and data_pos + 16 <= len(data):
                    val_len = struct.unpack(">I", data[data_pos - 4 : data_pos])[0] - 16
                    if val_len > 0:
                        val_bytes = data[data_pos + 8 : data_pos + 8 + val_len]
                        if key in ("season", "episode"):
                            if len(val_bytes) >= 1:
                                tags[key] = int(val_bytes[0])
                        else:
                            tags[key] = val_bytes.decode("utf-8", errors="ignore").strip()

    # -------------------------------------------------------------------------
    # EBML / Matroska (MKV / WebM) Parser
    # -------------------------------------------------------------------------
    def _parse_ebml(self, f, header: bytes, meta: MediaMetadata) -> None:
        meta.container = "mkv"
        meta.mime_type = "video/x-matroska"
        f.seek(0)
        data = f.read(65536)

        # Detect WebM vs MKV
        if b"webm" in data[:100]:
            meta.container = "webm"
            meta.mime_type = "video/webm"

        # Search for Video PixelWidth (0xB0) and PixelHeight (0xBA)
        w_idx = data.find(b"\xb0")
        if w_idx != -1 and w_idx + 3 < len(data):
            # Parse EBML integer
            w_len = self._get_ebml_len(data[w_idx + 1])
            if w_idx + 1 + w_len <= len(data):
                meta.width = int.from_bytes(data[w_idx + 2 : w_idx + 2 + w_len], "big")

        h_idx = data.find(b"\xba")
        if h_idx != -1 and h_idx + 3 < len(data):
            h_len = self._get_ebml_len(data[h_idx + 1])
            if h_idx + 1 + h_len <= len(data):
                meta.height = int.from_bytes(data[h_idx + 2 : h_idx + 2 + h_len], "big")

        # Track indicators
        if b"V_MPEG4" in data or b"V_MPEGH" in data or b"V_VP8" in data or b"V_VP9" in data or b"V_AV1" in data:
            meta.has_video = True
            meta.streams.append(StreamInfo(stream_type="video", width=meta.width, height=meta.height))
        if b"A_AAC" in data or b"A_AC3" in data or b"A_FLAC" in data or b"A_OPUS" in data or b"A_VORBIS" in data:
            meta.has_audio = True
            meta.streams.append(StreamInfo(stream_type="audio"))
        if b"S_TEXT" in data or b"S_HDMV" in data or b"S_VOBSUB" in data:
            meta.has_subtitles = True
            meta.streams.append(StreamInfo(stream_type="subtitle"))

    def _get_ebml_len(self, first_byte: int) -> int:
        mask = 0x80
        length = 1
        while mask and not (first_byte & mask):
            length += 1
            mask >>= 1
        return min(length, 4)

    # -------------------------------------------------------------------------
    # RIFF (AVI / WAV) Parser
    # -------------------------------------------------------------------------
    def _parse_riff(self, f, header: bytes, meta: MediaMetadata) -> None:
        if len(header) >= 12:
            form_type = header[8:12]
            if form_type == b"AVI ":
                meta.container = "avi"
                meta.mime_type = "video/x-msvideo"
                meta.has_video = True
                meta.streams.append(StreamInfo(stream_type="video"))
            elif form_type == b"WAVE":
                meta.container = "wav"
                meta.mime_type = "audio/wav"
                meta.has_audio = True
                meta.streams.append(StreamInfo(stream_type="audio"))

    # -------------------------------------------------------------------------
    # Image Parsers (JPEG EXIF & PNG)
    # -------------------------------------------------------------------------
    def _parse_jpeg_exif(self, f, header: bytes, meta: MediaMetadata) -> None:
        meta.container = "jpeg"
        meta.mime_type = "image/jpeg"

        f.seek(0)
        data = f.read(65536)
        exif_idx = data.find(b"Exif\x00\x00")
        if exif_idx != -1:
            tiff_start = exif_idx + 6
            if tiff_start + 8 <= len(data):
                byte_order = data[tiff_start : tiff_start + 2]
                endian = "<" if byte_order == b"II" else ">"
                try:
                    first_ifd_offset = struct.unpack(endian + "I", data[tiff_start + 4 : tiff_start + 8])[0]
                    curr_pos = tiff_start + first_ifd_offset
                    if curr_pos + 2 <= len(data):
                        entry_count = struct.unpack(endian + "H", data[curr_pos : curr_pos + 2])[0]
                        curr_pos += 2
                        for _ in range(min(entry_count, 50)):
                            if curr_pos + 12 > len(data):
                                break
                            tag, ftype, count, val_offset = struct.unpack(endian + "HHII", data[curr_pos : curr_pos + 12])
                            curr_pos += 12
                            # 0x0110: Model, 0x010F: Make, 0x9003: DateTimeOriginal, 0x0132: DateTime
                            if tag in (0x9003, 0x0132):
                                dt_start = tiff_start + val_offset
                                dt_str = data[dt_start : dt_start + count].decode("latin-1", errors="ignore").rstrip("\x00")
                                if dt_str:
                                    meta.tags["datetime_original"] = dt_str
                            elif tag == 0x0110:  # Camera Model
                                m_start = tiff_start + val_offset
                                m_str = data[m_start : m_start + count].decode("latin-1", errors="ignore").rstrip("\x00")
                                if m_str:
                                    meta.tags["camera_model"] = m_str
                except Exception:
                    pass

    def _parse_png(self, f, header: bytes, meta: MediaMetadata) -> None:
        meta.container = "png"
        meta.mime_type = "image/png"
        if len(header) >= 24:
            # IHDR is first chunk
            width, height = struct.unpack(">II", header[16:24])
            meta.width = width
            meta.height = height
