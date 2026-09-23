"""Bounded, explicit local MP4/H.264 keyframe decoding for SC02."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import numpy as np

MAX_VIDEO_BYTES = 1024**3
MAX_WIDTH, MAX_HEIGHT = 3840, 2160


@dataclass(frozen=True)
class VideoInfo:
    path: Path
    source_id: str
    byte_count: int
    coded_width: int
    coded_height: int
    display_width: int
    display_height: int
    codec: str
    rotation_degrees: int
    duration_seconds: float


@dataclass(frozen=True)
class Keyframe:
    requested_seconds: float
    pts: int
    time_base_num: int
    time_base_den: int
    actual_seconds: float
    seek_decode_ordinal: int
    sample_id: str
    width: int
    height: int
    rgb: np.ndarray
    pixel_sha256: str


def _rotation(stream) -> int:
    # A display matrix is handled by FFmpeg/PyAV where supported; the simple
    # rotate metadata is the explicit SC02 path. Unknown values are rejected.
    value = int(stream.metadata.get("rotate", "0")) % 360
    if value not in (0, 90, 180, 270):
        raise ValueError("unsupported_display_rotation")
    return value


def _main_stream(container):
    streams = [s for s in container.streams.video if s.codec_context.name == "h264"]
    if len(streams) != 1:
        raise ValueError("one_h264_video_stream_required")
    return streams[0]


def probe_video(path: Path) -> VideoInfo:
    import av  # Lazy: source probing occurs only after the permission profile is approved.

    source = Path(path).resolve(strict=True)
    if not source.is_file() or source.suffix.lower() != ".mp4":
        raise ValueError("approved_mp4_required")
    size = source.stat().st_size
    if size <= 0 or size > MAX_VIDEO_BYTES:
        raise ValueError("video_size_limit")
    with av.open(str(source), mode="r") as container:
        stream = _main_stream(container)
        width, height = stream.codec_context.width, stream.codec_context.height
        if stream.codec_context.name != "h264" or not 0 < width <= MAX_WIDTH or not 0 < height <= MAX_HEIGHT:
            raise ValueError("video_codec_or_size_limit")
        rotation = _rotation(stream)
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        if duration <= 0:
            raise ValueError("video_duration_unavailable")
    # Path and filesystem metadata identify this selected source without
    # copying it into the run. Pixel content receives a separate digest.
    stat = source.stat()
    identity = f"{source}|{stat.st_size}|{stat.st_mtime_ns}".encode("utf-8")
    display = (height, width) if rotation in (90, 270) else (width, height)
    return VideoInfo(source, sha256(identity).hexdigest(), size, width, height,
                     display[0], display[1], "h264", rotation, duration)


def decode_at(info: VideoInfo, requested_seconds: float) -> Keyframe:
    import av

    if not np.isfinite(requested_seconds) or not 0 <= requested_seconds < info.duration_seconds:
        raise ValueError("requested_time_out_of_range")
    with av.open(str(info.path), mode="r") as container:
        stream = _main_stream(container)
        seek_pts = int(Fraction(str(requested_seconds)) / stream.time_base)
        container.seek(seek_pts, stream=stream, backward=True, any_frame=False)
        for ordinal, frame in enumerate(container.decode(stream)):
            if ordinal > 30_000:
                raise TimeoutError("decode_frame_limit")
            if frame.pts is None or frame.time_base is None:
                continue
            actual = float(frame.pts * frame.time_base)
            if actual + 1e-9 < requested_seconds:
                continue
            rgb = np.ascontiguousarray(frame.to_ndarray(format="rgb24"))
            if info.rotation_degrees == 90:
                rgb = np.ascontiguousarray(np.rot90(rgb, k=3))
            elif info.rotation_degrees == 180:
                rgb = np.ascontiguousarray(np.rot90(rgb, k=2))
            elif info.rotation_degrees == 270:
                rgb = np.ascontiguousarray(np.rot90(rgb, k=1))
            height, width = rgb.shape[:2]
            if (width, height) != (info.display_width, info.display_height):
                raise ValueError("decoded_display_size_mismatch")
            pixels = sha256(rgb.tobytes(order="C")).hexdigest()
            sample = sha256(f"{info.source_id}|{frame.pts}|{frame.time_base}|{ordinal}|{pixels}".encode()).hexdigest()
            tb = Fraction(frame.time_base)
            return Keyframe(requested_seconds, int(frame.pts), tb.numerator, tb.denominator,
                            actual, ordinal, sample, width, height, rgb, pixels)
    raise EOFError("requested_frame_not_decoded")
