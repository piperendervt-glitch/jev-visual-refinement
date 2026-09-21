"""Opaque upload store and bounded, original-PTS media input adapter."""
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import math
from pathlib import Path
import secrets
import time
from contextlib import contextmanager


@contextmanager
def open_media(path):
    import av
    # File-like IO and a fixed demuxer prevent playlist/protocol/device dispatch.
    def deny_nested(*args):
        raise PermissionError('nested_media_io_denied')
    kind = 'matroska' if Path(path).suffix in ('.mkv', '.webm') else 'mov'
    with Path(path).open('rb') as stream:
        with av.open(stream, format=kind, options={'protocol_whitelist': ''}, io_open=deny_nested) as container:
            yield container


def plain_path(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        if item.exists() and (item.is_symlink() or item.is_junction()):
            raise ValueError('reparse_denied')
    return path


@dataclass(frozen=True)
class InputPacket:
    provenance: dict
    frame: object
    pcm: object


class Assets:
    def __init__(self, root, profile):
        self.root = plain_path(root)
        self.root.mkdir(parents=True, exist_ok=False)
        self.profile = profile
        self.items = {}
        self.created = time.time()

    def import_stream(self, stream, size, suffix):
        if suffix not in ('.mp4', '.webm', '.mov', '.m4v', '.mkv'):
            raise ValueError('unsupported_container')
        if not 0 < size <= self.profile['max_asset_bytes']:
            raise ValueError('asset_size_limit')
        if len(self.items) >= self.profile['max_assets'] or size + sum(x['size'] for x in self.items.values()) > self.profile['max_total_bytes']:
            raise ValueError('total_capacity')
        ident = secrets.token_hex(16)
        path = self.root / (ident + suffix)
        digest = hashlib.sha256()
        try:
            with path.open('xb') as target:
                remaining = size
                while remaining:
                    data = stream.read(min(remaining, 1024 * 1024))
                    if not data:
                        raise ValueError('upload_cancelled')
                    target.write(data)
                    digest.update(data)
                    remaining -= len(data)
            if self.profile.get('allowed_asset_sha256') and digest.hexdigest() not in self.profile['allowed_asset_sha256']:
                raise ValueError('asset_not_in_grant')
            metadata = probe(path, self.profile)
            self.items[ident] = dict(id=ident, path=path, size=size, sha256=digest.hexdigest(), **metadata)
            return ident
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    def get(self, ident):
        if time.time() - self.created >= self.profile['retention_seconds']:
            raise ValueError('asset_expired')
        if ident not in self.items:
            raise ValueError('unknown_asset')
        item = self.items[ident]
        if plain_path(item['path']).parent != self.root:
            raise ValueError('asset_path_boundary')
        return item

    def public(self):
        return [{k: v for k, v in item.items() if k != 'path'} for item in self.items.values()]

    def close(self):
        for item in self.items.values():
            plain_path(item['path']).unlink(missing_ok=True)
        self.items.clear()
        self.root.rmdir()


def probe(path, profile):
    try:
        import av
    except ImportError:
        return dict(decoder='BLOCKED_missing_PyAV', duration=None, has_audio=None)
    try:
        with open_media(path) as container:
            if not container.streams.video:
                raise ValueError('no_video_track')
            if not container.duration or container.start_time is None:
                raise ValueError('unsupported_timestamp_structure')
            video = container.streams.video[0]
            if video.width * video.height > profile['max_pixels']:
                raise ValueError('pixel_limit')
            tracks = []
            for stream in (*container.streams.video, *container.streams.audio):
                if stream.time_base is None or stream.start_time is None:
                    raise ValueError('unsupported_timestamp_structure')
                tracks.append(dict(index=stream.index, type=stream.type, codec=stream.codec_context.name,
                                   start_pts=stream.start_time, time_base=[stream.time_base.numerator, stream.time_base.denominator],
                                   duration_pts=stream.duration,
                                   end_s=None if stream.duration is None else float((stream.start_time+stream.duration)*stream.time_base)-container.start_time/av.time_base))
            return dict(decoder='ready', duration=container.duration / av.time_base,
                        origin_s=container.start_time / av.time_base, has_audio=bool(container.streams.audio),
                        width=video.width, height=video.height, tracks=tracks)
    except av.error.FFmpegError as error:
        raise ValueError('corrupt_encrypted_or_unsupported_codec:' + type(error).__name__) from error
    except ValueError:
        raise
    except Exception as error:
        raise ValueError('corrupt_encrypted_or_unsupported_codec:' + type(error).__name__) from error


class SavedVideoSource:
    def __init__(self, profile):
        self.profile = profile

    def decode(self, asset, start, end, envelope, *, lane=None):
        import av
        import numpy as np
        if lane not in (None,'asr','image'):raise ValueError('invalid_decode_lane')
        if asset['decoder'] != 'ready':
            raise ValueError(asset['decoder'])
        if not 0 <= start < end <= asset['duration'] + 0.001 or end-start > self.profile['max_chunk_seconds']:
            raise ValueError('invalid_interval')
        origin = asset['origin_s']
        selected = None
        frame_meta = None
        if lane != 'asr':
            with open_media(asset['path']) as container:
                stream = container.streams.video[0]
                if lane:stream.codec_context.thread_count=self.profile['decoder_threads']
                container.seek(int((end + origin) / stream.time_base), stream=stream, backward=True)
                for count, frame in enumerate(container.decode(stream)):
                    self.bounded(count, frame, origin, start)
                    stamp = float(frame.pts * frame.time_base) - origin
                    if stamp > end:
                        break
                    if stamp >= start:
                        width = min(640, frame.width)
                        selected = frame.reformat(width=width, height=max(2, round(frame.height*width/frame.width)), format='bgr24').to_ndarray()
                        frame_meta = dict(track=stream.index, pts=frame.pts,
                                          time_base=[frame.time_base.numerator, frame.time_base.denominator], media_s=stamp,
                                          root=f"{asset['sha256']}:v{stream.index}:{frame.pts}")
        pieces, mapping = [], []
        if asset['has_audio'] and lane != 'image':
            with open_media(asset['path']) as container:
                stream = container.streams.audio[0]
                if lane:stream.codec_context.thread_count=self.profile['decoder_threads']
                container.seek(int((start + origin) / stream.time_base), stream=stream, backward=True)
                resampler = av.AudioResampler(format='fltp', layout='mono', rate=16000)
                for count, frame in enumerate(container.decode(stream)):
                    self.bounded(count, frame, origin, start)
                    if float(frame.pts * frame.time_base) - origin > end:
                        break
                    for out in resampler.resample(frame):
                        if out.pts is None:
                            raise ValueError('audio_pts_missing')
                        stamp = Fraction(out.pts) * out.time_base - Fraction(str(origin))
                        lo = max(0, math.ceil((Fraction(str(start)) - stamp) * 16000))
                        hi = min(out.samples, math.floor((Fraction(str(end)) - stamp) * 16000))
                        if hi <= lo:
                            continue
                        a, b = float(stamp + Fraction(lo, 16000)), float(stamp + Fraction(hi, 16000))
                        if mapping and abs(a - mapping[-1]['end_exclusive_s']) > 2/16000:
                            raise ValueError('audio_discontinuity')
                        pieces.append(out.to_ndarray().reshape(-1)[lo:hi].copy())
                        mapping.append(dict(track=stream.index, pts=frame.pts, time_base=[frame.time_base.numerator, frame.time_base.denominator],
                                            source_rate=frame.sample_rate, source_channels=len(frame.layout.channels),
                                            converted_pts=out.pts, converted_time_base=[out.time_base.numerator, out.time_base.denominator],
                                            sample_offset=lo, samples=hi-lo, start_s=a, end_exclusive_s=b))
        pcm = np.concatenate(pieces) if pieces else np.empty(0, dtype=np.float32)
        pcm.setflags(write=False)
        if selected is not None:
            selected.setflags(write=False)
        # Track offsets are preserved; missing coverage is explicit, never padded with invented sound.
        audio = dict(status='no_audio_track' if not asset['has_audio'] else 'audio_gap' if not len(pcm) else 'decoded',
                     sample_rate=16000, channels=1, samples=len(pcm), mapping=mapping,
                     rms=float(np.sqrt(np.mean(pcm**2))) if len(pcm) else None,
                     root=f"{asset['sha256']}:a:{start:.9f}:{end:.9f}")
        if len(pcm) and audio['rms'] < 0.00001:
            audio['status'] = 'digital_silence'
        delta = abs(frame_meta['media_s'] - mapping[-1]['end_exclusive_s']) if frame_meta and mapping else None
        provenance = dict(**envelope, source_kind='saved_video', asset_id=asset['id'], asset_sha256=asset['sha256'],
                          interval=[start, end], media_origin_s=origin, frame=frame_meta, audio=audio,
                          av_end_delta_s=delta, sync_within_tolerance=None if delta is None else delta <= self.profile['sync_tolerance_seconds'],
                          mode='LOCAL_OBSERVATION_NO_JEV', context='observation_only')
        if lane:
            provenance['lane']=lane
            if lane=='image':provenance['audio']=None
        return InputPacket(provenance, selected, pcm)

    def bounded(self, count, frame, origin, start):
        if frame.pts is None or frame.time_base is None:
            raise ValueError('timestamp_missing')
        if count >= self.profile['decoder_frame_limit']:
            raise ValueError('decoder_frame_limit')
        if float(frame.pts * frame.time_base)-origin < start-self.profile['decoder_preroll_seconds']:
            raise ValueError('decoder_preroll_limit')
