"""Scan an st123 project directory for stage status, images, and catalogs."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import (
    STAGES,
    campaign_targets,
    max_concurrent_jobs,
    quality_cuts,
    status_dir,
    status_path,
    target_config,
)
from .host_distance import format_distance, lookup_host_distance, warm_host_distances
from .photometry import build_epoch_plan, build_filter_plan, row_ab_mags, source_photometry_tables
from .sky import format_obs_datetime, pix_to_world, read_image_header, reference_heading
from .st123api import display_filter, instrument_name

_SCIENCE_SKIP = ('_pam.fits', '_c1m.fits')
_SCIENCE_SUFFIXES = ('_flc.fits', '_flt.fits', '_c0m.fits', '_cal.fits', '_i2d.fits')
# Match st123.datamodels.hst: only NORMAL (or missing) EXPFLAG is science-usable.
_GOOD_HST_EXPFLAGS = frozenset({None, '', 'NORMAL'})
_BOXED_COADD = re.compile(r'^coadd_\d+_[0-9a-z]+_', re.IGNORECASE)
_FILTER_IN_NAME = re.compile(r'_(f\d{3,4}w(?:n|m)?|f\d{3,4}lp|f150w2)_', re.IGNORECASE)
_INST_IN_NAME = re.compile(r'(?:^|_)(acs|wfc3|wfpc2|nircam|miri|niriss)(?:_|$)', re.IGNORECASE)
_COADD_SKIP_TOKENS = ('.sky.fits', '_wht', '_ctx', 'weight', 'context')
_LOG_NAME = re.compile(
    r'^(?P<prefix>.+)_(?P<stamp>\d{8}_\d{6})_[0-9a-f]+\.log$',
    re.IGNORECASE,
)
_LOG_TS = re.compile(r'(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})')
_ELAPSED_SEC = re.compile(r'ELAPSED_SEC\s*=\s*([0-9.]+)', re.IGNORECASE)
_LIST_TTL_SEC = 20.0
_LIST_LOCK = threading.Lock()
_LIST_CACHE: dict[Any, tuple[float, list[dict[str, Any]]]] = {}
_FITS_META_CACHE: dict[tuple[str, float], dict[str, Any]] = {}
_CATALOG_SUMMARY_CACHE: dict[tuple[str, float], dict[str, Any]] = {}
_FITS_META_CACHE_MAX = 4000


def _utc_from_mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _parse_log_stamp(stamp: str) -> datetime | None:
    try:
        return datetime.strptime(stamp, '%Y%m%d_%H%M%S').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _duration_seconds(start: datetime | None, end: datetime | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def _parse_stored_time(value: Any) -> datetime | None:
    if value is None or value == '':
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace('Z', '')
        parsed = None
        for fmt in ('%Y-%m-%dT%H:%M:%S', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M'):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(microsecond=0).strftime('%Y-%m-%dT%H:%M:%S')


def _format_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    total = int(round(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f'{hours}h {minutes:02d}m {secs:02d}s'
    if minutes:
        return f'{minutes}m {secs:02d}s'
    return f'{secs}s'


def _persist_n_images(base_dir: Path, stored: dict[str, Any], n_images: int) -> None:
    """Remember the science-image count so later list loads skip the download walk."""
    if not stored or stored.get('state') == 'running' or stored.get('n_images') == n_images:
        return
    path = status_path(base_dir)
    if not path.is_file():
        return
    stored['n_images'] = n_images
    try:
        tmp = path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(stored, indent=2))
        tmp.replace(path)
    except OSError:
        pass


def read_status_file(base_dir: Path) -> dict[str, Any]:
    path = status_path(base_dir)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def pid_is_running(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def _is_science_fits_name(name: str) -> bool:
    lower = name.lower()
    if any(lower.endswith(skip) for skip in _SCIENCE_SKIP):
        return False
    return any(lower.endswith(suffix) for suffix in _SCIENCE_SUFFIXES)


def iter_science_fits(download_root: Path):
    """Yield calibrated science FITS under *download_root* without sorting."""
    if not download_root.is_dir():
        return
    for dirpath, _dirnames, filenames in os.walk(download_root, followlinks=False):
        for name in filenames:
            if _is_science_fits_name(name):
                yield Path(dirpath, name)


def has_science_fits(download_root: Path) -> bool:
    return next(iter_science_fits(download_root), None) is not None


def count_science_fits(download_root: Path) -> int:
    return sum(1 for _ in iter_science_fits(download_root))


def _science_fits(download_root: Path) -> list[Path]:
    return sorted(iter_science_fits(download_root))


def _has_named_fits(root: Path, pattern: str) -> bool:
    if not root.is_dir():
        return False
    return next(root.rglob(pattern), None) is not None


def has_phot_files(base_dir: Path) -> bool:
    for root in (Path(base_dir) / 'dolphot', Path(base_dir) / 'reduction'):
        if not root.is_dir():
            continue
        for phot in root.rglob('*.phot'):
            name = phot.name
            if name.endswith('.phot.info') or name.endswith('.phot.ap'):
                continue
            try:
                if phot.is_file() and phot.stat().st_size > 0:
                    return True
            except OSError:
                continue
    return False


def has_mosaic_coadd(base_dir: Path) -> bool:
    root = Path(base_dir) / 'reduction' / 'reference'
    if not root.is_dir():
        return False
    for path in root.rglob('coadd_*.fits'):
        if _is_science_coadd(path):
            return True
    return False


def clear_campaign_list_cache() -> None:
    with _LIST_LOCK:
        _LIST_CACHE.clear()
    try:
        from .mast_updates import clear_updates_cache

        clear_updates_cache()
    except Exception:
        pass


_ANSI = re.compile(r'\x1b\[[0-9;]*m')


def mast_imaging_found_count(base_dir: Path) -> int | None:
    """Return the MAST cone-search hit count from the latest download log."""
    logs = _latest_logs(Path(base_dir) / 'logs', ('download',))
    if not logs:
        return None
    try:
        text = _ANSI.sub('', logs[-1].read_text(errors='replace'))
    except OSError:
        return None
    match = re.search(r'Found (\d+) HST imaging', text)
    return int(match.group(1)) if match else None


def is_empty_mast_download(base_dir: Path) -> bool:
    """True when MAST was queried and returned no imaging (0/0, not a timeout)."""
    if has_science_fits(Path(base_dir) / 'download'):
        return False
    return mast_imaging_found_count(base_dir) == 0


def count_raw_science_fits(base_dir: Path) -> int:
    """Count science FITS under ``reduction/raw`` (post link-raw / EXPFLAG gate)."""
    raw = Path(base_dir) / 'reduction' / 'raw'
    if not raw.is_dir():
        return 0
    return count_science_fits(raw)


def is_unusable_hst_download(base_dir: Path) -> bool:
    """True when MAST products exist but every frame was rejected at link-raw.

    Typical case: all ``flc``/``flt`` have ``EXPFLAG=EXCESSIVE DOWNTIME`` (or
    similar), so download "succeeds" with files on disk but ``reduction/raw``
    is empty and align would find nothing to JHAT.
    """
    if is_empty_mast_download(base_dir):
        return False
    if not has_science_fits(Path(base_dir) / 'download'):
        return False
    return count_raw_science_fits(base_dir) == 0


def revert_status_for_new_data(base_dir: Path) -> None:
    """Put an empty-field target back to pending when MAST later has data."""
    stored = read_status_file(base_dir)
    if stored.get('state') == 'running' and pid_is_running(stored.get('pid')):
        return
    stages = dict(stored.get('stages') or {})
    for spec in STAGES:
        record = dict(stages.get(spec.key) or {})
        if spec.key == 'download' or record.get('state') == 'skipped' or record.get('empty_mast'):
            record['state'] = 'pending'
        stages[spec.key] = record
    stored.update(
        {
            'state': 'idle',
            'message': 'New MAST data are available',
            'ended_at': None,
            'stages': stages,
        }
    )
    from .runner import write_status

    write_status(Path(base_dir), stored)


def _latest_logs(log_dir: Path, prefixes: Iterable[str]) -> list[Path]:
    if not log_dir.is_dir():
        return []
    matches: list[Path] = []
    prefixes = tuple(prefixes)
    for path in log_dir.glob('*.log'):
        for prefix in prefixes:
            if path.name.startswith(f'{prefix}_') or path.name.startswith(prefix):
                matches.append(path)
                break
    matches.sort(key=lambda p: p.stat().st_mtime)
    return matches


def _parse_elapsed_seconds(path: Path) -> float | None:
    try:
        text = path.read_text(errors='replace')
    except OSError:
        return None
    matches = _ELAPSED_SEC.findall(text)
    if not matches:
        return None
    try:
        return sum(float(item) for item in matches)
    except ValueError:
        return None


def _mtime_span(paths: Iterable[Path]) -> tuple[datetime | None, datetime | None]:
    times = []
    for path in paths:
        try:
            if path.is_file():
                times.append(_utc_from_mtime(path))
        except OSError:
            continue
    if not times:
        return None, None
    return min(times), max(times)


def _dolphot_run_timing(base_dir: Path) -> tuple[datetime | None, datetime | None, float | None]:
    starts: list[datetime] = []
    ends: list[datetime] = []
    elapsed = 0.0
    found_elapsed = False
    for root in (base_dir / 'dolphot', base_dir / 'reduction'):
        if not root.is_dir():
            continue
        for err in root.rglob('dolphot.err'):
            extra = _parse_elapsed_seconds(err)
            if extra:
                elapsed += extra
                found_elapsed = True
            ends.append(_utc_from_mtime(err))
        for out in root.rglob('dolphot.out'):
            ends.append(_utc_from_mtime(out))
        for phot in root.rglob('*.phot'):
            if phot.name.endswith(('.phot.info', '.phot.ap')):
                continue
            ends.append(_utc_from_mtime(phot))
        for param in root.rglob('dolphot.param'):
            starts.append(_utc_from_mtime(param))
    start = min(starts) if starts else None
    end = max(ends) if ends else None
    seconds = elapsed if found_elapsed else _duration_seconds(start, end)
    return start, end, seconds


def _write_stage_log(
    base_dir: Path,
    prefix: str,
    start: datetime,
    seconds: float,
    message: str,
) -> Path:
    log_dir = base_dir / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = start.astimezone(timezone.utc).strftime('%Y%m%d_%H%M%S')
    path = log_dir / f'{prefix}_{stamp}_backfill.log'
    end = start + timedelta(seconds=float(seconds))
    start_txt = start.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    end_txt = end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    path.write_text(
        f'[{start_txt}::logging.py::1] [INFO] Logging to {path}\n'
        f'[{start_txt}::logging.py::1] [INFO] {message}\n'
        f'[{end_txt}::logging.py::1] [INFO] ELAPSED_SEC={float(seconds):.2f}\n'
    )
    return path


def _ensure_missing_stage_logs(base_dir: Path) -> None:
    """Write a stage log when a finished run left only artifact timing."""
    logs = _latest_logs(base_dir / 'logs', ('run-dolphot',))
    if logs or not discover_phot_files(base_dir):
        return
    start, _end, seconds = _dolphot_run_timing(base_dir)
    if start is None or seconds is None:
        return
    _write_stage_log(
        base_dir,
        'run-dolphot',
        start,
        seconds,
        'Run DOLPHOT timing recovered from dolphot.err ELAPSED_SEC',
    )


def _log_times(path: Path, *, detailed: bool = True) -> tuple[datetime | None, datetime | None]:
    start = None
    match = _LOG_NAME.match(path.name)
    if match:
        start = _parse_log_stamp(match.group('stamp'))
    if not detailed:
        return start, _utc_from_mtime(path)
    try:
        text = path.read_text(errors='replace')
    except OSError:
        return start, _utc_from_mtime(path)
    stamps = _LOG_TS.findall(text)
    parsed: list[datetime] = []
    for raw in stamps:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S'):
            try:
                parsed.append(datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc))
                break
            except ValueError:
                continue
    if parsed:
        start = start or parsed[0]
        return start, parsed[-1]
    return start, _utc_from_mtime(path)


def _science_chip_shapes(hdul) -> list[tuple[int, int]]:
    """Chip sizes from NAXIS cards only — never load pixel arrays."""
    shapes: list[tuple[int, int]] = []
    for hdu in hdul:
        cards = getattr(hdu, 'header', None)
        if cards is None:
            continue
        name = str(getattr(hdu, 'name', '') or '').upper()
        if name and not name.startswith('SCI') and name not in {'', 'PRIMARY'}:
            continue
        try:
            naxis = int(cards.get('NAXIS') or 0)
        except (TypeError, ValueError):
            continue
        if naxis < 2:
            continue
        try:
            nx = int(cards['NAXIS1'])
            ny = int(cards['NAXIS2'])
        except (KeyError, TypeError, ValueError):
            continue
        n_plane = 1
        if naxis >= 3:
            try:
                n_plane = max(1, int(cards.get('NAXIS3') or 1))
            except (TypeError, ValueError):
                n_plane = 1
        if name.startswith('SCI'):
            shapes.append((ny, nx))
        elif name in {'', 'PRIMARY'} and not shapes:
            shapes.extend([(ny, nx)] * n_plane)
    return shapes


def _format_image_size(shapes: list[tuple[int, int]]) -> str | None:
    if not shapes:
        return None
    naxis2, naxis1 = shapes[0]
    if len(shapes) == 1:
        return f'{naxis1} × {naxis2}'
    if all(shape == shapes[0] for shape in shapes):
        return f'{len(shapes)} × {naxis1} × {naxis2}'
    return f'{len(shapes)} chips'


def _header_value(header, *keys):
    for key in keys:
        if key in header and header[key] not in (None, '', 'N/A'):
            return header[key]
    return None


def _fits_metadata(path: Path, download_root: Path) -> dict[str, Any]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    cache_key = (str(path), mtime)
    cached = _FITS_META_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    meta = _fits_metadata_uncached(path, download_root)
    if len(_FITS_META_CACHE) >= _FITS_META_CACHE_MAX:
        _FITS_META_CACHE.clear()
    _FITS_META_CACHE[cache_key] = meta
    return dict(meta)


def _fits_metadata_uncached(path: Path, download_root: Path) -> dict[str, Any]:
    try:
        rel = path.relative_to(download_root)
    except ValueError:
        rel = path
    parts = rel.parts
    telescope = parts[0] if len(parts) > 0 else ''
    instrument = parts[1] if len(parts) > 1 else ''
    filt = parts[2] if len(parts) > 2 else ''
    obsid = parts[3] if len(parts) > 3 else ''
    product = path.suffix.lower()
    stem = path.name.lower()
    for suffix in ('_flc', '_flt', '_c0m', '_c1m', '_cal', '_i2d', '_drc', '_drz'):
        if suffix in stem:
            product = suffix[1:]
            break

    meta = {
        'filename': path.name,
        'path': str(path),
        'relativepath': str(rel),
        'telescope': telescope,
        'instrument': instrument,
        'filter': filt,
        'obsid': obsid,
        'product': product,
        'exptime': None,
        'date_obs': None,
        'ra': None,
        'dec': None,
        'targname': None,
        'rootname': path.stem.split('_')[0],
        'naxis1': None,
        'naxis2': None,
        'n_sci': 0,
        'size_display': None,
    }
    try:
        from astropy.io import fits
    except Exception:
        return meta

    try:
        with fits.open(path, memmap=True, lazy_load_hdus=True) as hdul:
            header = hdul[0].header
            for hdu in hdul:
                cards = hdu.header
                if cards.get('INSTRUME') or cards.get('EXPTIME') or cards.get('FILTER'):
                    header = cards
                    break
            shapes = _science_chip_shapes(hdul)
    except Exception:
        return meta

    inst_hdr = _header_value(header, 'INSTRUME')
    if inst_hdr:
        meta['instrument'] = str(inst_hdr)
    tel_hdr = _header_value(header, 'TELESCOP')
    if tel_hdr:
        meta['telescope'] = str(tel_hdr)
    # Flat reduction/raw symlinks have no filter directory; read ACS/WFC3 cards.
    if not meta.get('filter'):
        from .sky import _science_filter_from_cards

        meta['filter'] = _science_filter_from_cards(header)
    meta['exptime'] = _header_value(header, 'EXPTIME', 'TEXPTIME')
    meta['expflag'] = _header_value(header, 'EXPFLAG')
    meta['date_obs'] = format_obs_datetime(
        _header_value(header, 'DATE-OBS', 'DATE_OBS'),
        _header_value(header, 'TIME-OBS', 'TIME_OBS'),
    )
    meta['ra'] = _header_value(header, 'RA_TARG', 'CRVAL1')
    meta['dec'] = _header_value(header, 'DEC_TARG', 'CRVAL2')
    meta['targname'] = _header_value(header, 'TARGNAME', 'TARG_ID')
    meta['rootname'] = _header_value(header, 'ROOTNAME') or meta['rootname']
    if shapes:
        meta['n_sci'] = len(shapes)
        meta['naxis2'], meta['naxis1'] = int(shapes[0][0]), int(shapes[0][1])
        meta['size_display'] = _format_image_size(shapes)
    try:
        if meta['exptime'] is not None:
            meta['exptime'] = float(meta['exptime'])
        if meta['ra'] is not None:
            meta['ra'] = float(meta['ra'])
        if meta['dec'] is not None:
            meta['dec'] = float(meta['dec'])
    except (TypeError, ValueError):
        pass
    return meta


def _is_usable_science_row(meta: dict[str, Any]) -> bool:
    """False for zero-time or bad-EXPFLAG frames the pipeline already rejects."""
    exp = meta.get('exptime')
    if exp is not None:
        try:
            if float(exp) <= 0.0:
                return False
        except (TypeError, ValueError):
            pass
    flag = meta.get('expflag')
    if flag is not None:
        text = str(flag).strip().upper()
        if text and text not in _GOOD_HST_EXPFLAGS:
            return False
    return True


def list_images(base_dir: Path) -> list[dict[str, Any]]:
    """List science frames shown on the campaign page.

    Prefer ``reduction/raw`` (post link-raw / EXPFLAG gate) when it has frames so
    the table matches what align/mosaic/DOLPHOT actually used. Fall back to
    ``download/``, still hiding zero-exptime and bad-EXPFLAG products.
    """
    root = Path(base_dir)
    raw_root = root / 'reduction' / 'raw'
    download_root = root / 'download'
    if raw_root.is_dir() and has_science_fits(raw_root):
        scan_root = raw_root
    else:
        scan_root = download_root
    rows = []
    for path in _science_fits(scan_root):
        meta = _fits_metadata(path, scan_root)
        if not meta.get('filter'):
            meta['filter'] = display_filter(_filter_from_name(path.name))
        else:
            meta['filter'] = display_filter(meta.get('filter')) or meta.get('filter')
        if not _is_usable_science_row(meta):
            continue
        rows.append(meta)
    return rows


def discover_phot_files(base_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root in (base_dir / 'dolphot', base_dir / 'reduction'):
        if not root.is_dir():
            continue
        for phot in sorted(root.rglob('*.phot')):
            if phot.name.endswith('.phot.info') or phot.name.endswith('.phot.ap'):
                continue
            if phot.is_file() and phot.stat().st_size > 0:
                found.append(phot)
    return found


def discover_param_files(base_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root in (base_dir / 'dolphot', base_dir / 'reduction'):
        if not root.is_dir():
            continue
        found.extend(sorted(root.rglob('dolphot.param')))
    return found


def discover_hdf5_files(base_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root in (base_dir / 'dolphot', base_dir / 'reduction'):
        if not root.is_dir():
            continue
        found.extend(sorted(p for p in root.rglob('*.h5') if p.is_file()))
    return found


def _img0_file_from_param(param: Path) -> str | None:
    for line in param.read_text(errors='replace').splitlines():
        if line.strip().startswith('img0_file'):
            ref = line.split('=', 1)[-1].strip()
            return ref or None
    return None


def _resolve_img0_candidates(base_dir: Path, param: Path, ref: str) -> list[Path]:
    names = [ref]
    if not ref.lower().endswith('.fits'):
        names.append(f'{ref}.fits')
    candidates: list[Path] = []
    for name in names:
        candidates.extend(
            (
                param.parent / name,
                param.parent / Path(name).name,
                Path(base_dir) / 'reduction' / 'reference' / Path(name).name,
            )
        )
    ref_root = Path(base_dir) / 'reduction' / 'reference'
    if ref_root.is_dir():
        stem = Path(ref).name
        if stem.lower().endswith('.fits'):
            stem = stem[:-5]
        candidates.extend(ref_root.rglob(f'{stem}.fits'))
    return candidates


def discover_dolphot_reference_paths(base_dir: Path) -> list[Path]:
    """Every DOLPHOT ``img0_file`` coadd on disk (one entry per photometry box)."""
    found: list[Path] = []
    seen: set[Path] = set()
    for param in discover_param_files(base_dir):
        ref = _img0_file_from_param(param)
        if not ref:
            continue
        for candidate in _resolve_img0_candidates(base_dir, param, ref):
            if not candidate.is_file():
                continue
            try:
                resolved = candidate.resolve()
            except OSError:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(candidate)
            break
    return found


def discover_reference_for_phot(phot: Path, base_dir: Path | None = None) -> Path | None:
    """Return the ``img0_file`` stamp for this ``.phot`` run (same DOLPHOT box)."""
    phot = Path(phot)
    param = phot.parent / 'dolphot.param'
    if not param.is_file():
        return None
    ref = _img0_file_from_param(param)
    if not ref:
        return None
    root = Path(base_dir) if base_dir is not None else phot.parent.parent.parent
    for candidate in _resolve_img0_candidates(root, param, ref):
        if candidate.is_file():
            return candidate
    return None


def discover_phot_for_display(
    base_dir: Path,
    *,
    image_id: str | None = None,
    display_path: Path | None = None,
) -> Path | None:
    """Pick the non-empty ``.phot`` whose stamp best matches the displayed mosaic.

    Prefer same instrument/filter, but still fall back to another catalog on the
    target so aligned mosaics (e.g. WFPC2 F300W) can show ACS DOLPHOT positions.
    """
    phot_files = discover_phot_files(base_dir)
    if not phot_files:
        return None

    want_name = Path(display_path).name.lower() if display_path is not None else ''
    want_filt = _filter_from_name(want_name) if want_name else None
    want_inst = _instrument_from_name(want_name) if want_name else None
    if image_id and (want_filt is None or want_inst is None):
        mosaics = discover_mosaic_images(base_dir)
        selected = next((row for row in mosaics if row.get('id') == image_id), None)
        if selected is not None:
            want_filt = want_filt or selected.get('filter')
            want_inst = want_inst or selected.get('instrument')
            want_name = want_name or Path(str(selected.get('path') or '')).name.lower()

    scored: list[tuple[int, Path]] = []
    for phot in phot_files:
        stamp = discover_reference_for_phot(phot, base_dir)
        if stamp is None:
            scored.append((0, phot))
            continue
        name = stamp.name.lower()
        score = 0
        if want_name and Path(name).name == Path(want_name).name:
            score += 100
        stamp_filt = _filter_from_name(name)
        stamp_inst = _instrument_from_name(name)
        if want_filt and stamp_filt == want_filt:
            score += 10
        if want_inst and stamp_inst == want_inst:
            score += 5
        # Same instrument, different filter (multi-band DOLPHOT) still matches.
        if want_inst and stamp_inst == want_inst and want_filt and stamp_filt and stamp_filt != want_filt:
            score += 5
        scored.append((score, phot))
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return scored[0][1]


def discover_reference_image(base_dir: Path) -> Path | None:
    # Prefer the stamp that owns the first non-empty catalog (viewer overlay).
    for phot in discover_phot_files(base_dir):
        stamp = discover_reference_for_phot(phot, base_dir)
        if stamp is not None:
            return stamp
    refs = discover_dolphot_reference_paths(base_dir)
    if refs:
        return refs[0]
    refs = sorted((base_dir / 'reduction' / 'reference').rglob('coadd_*_drc.fits')) if (base_dir / 'reduction' / 'reference').is_dir() else []
    return refs[0] if refs else None


def _filter_from_name(name: str) -> str | None:
    match = _FILTER_IN_NAME.search(name)
    return None if match is None else match.group(1).upper()


def discover_display_image(base_dir: Path) -> Path | None:
    """Full-field mosaic for the viewer, falling back to the DOLPHOT stamp."""
    stamp = discover_reference_image(base_dir)
    prefer = None
    stamp_area = 0
    if stamp is not None:
        header = read_image_header(stamp)
        prefer = header.get('filter') or _filter_from_name(stamp.name)
        stamp_area = int(header.get('nx') or 0) * int(header.get('ny') or 0)
    roots = (
        Path(base_dir) / 'reduction' / 'jhat_hst' / 'l3_ref',
        Path(base_dir) / 'reduction' / 'jhat' / 'l3_ref',
        Path(base_dir) / 'reduction' / 'reference_prelim',
    )
    candidates: list[tuple[Path, dict[str, Any], int]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.glob('coadd_*.fits')):
            name = path.name.lower()
            if name.endswith('.sky.fits') or _BOXED_COADD.match(path.name):
                continue
            header = read_image_header(path)
            area = int(header.get('nx') or 0) * int(header.get('ny') or 0)
            if stamp_area and area < stamp_area * 2:
                continue
            candidates.append((path, header, area))
    if not candidates:
        return stamp

    def _score(item: tuple[Path, dict[str, Any], int]) -> tuple[int, int, int]:
        path, header, area = item
        filt = (header.get('filter') or _filter_from_name(path.name) or '').upper()
        aligned = int('jhat' in path.parts or path.name.lower().endswith('_jhat.fits'))
        same = int(bool(prefer) and filt == str(prefer).upper())
        return (aligned, same, area)

    return max(candidates, key=_score)[0]


def _is_science_coadd(path: Path) -> bool:
    name = path.name.lower()
    if not name.startswith('coadd_') or not name.endswith('.fits'):
        return False
    return not any(token in name for token in _COADD_SKIP_TOKENS)


def _instrument_from_name(name: str) -> str | None:
    match = _INST_IN_NAME.search(name.lower())
    return None if match is None else match.group(1).upper()


def _mosaic_stage(path: Path) -> tuple[str, str]:
    parts = {part.lower() for part in path.parts}
    if 'reference_prelim' in parts:
        return 'align', 'prelim'
    if 'l3_ref' in parts:
        return 'align', 'l3'
    if 'dolphot' in parts:
        return 'dolphot', ''
    if 'reference' in parts:
        group = next((part for part in path.parts if part.startswith('group_')), '')
        ref = next((part for part in path.parts if part.startswith('ref_')), '')
        box = f"{group.replace('group_', 'g')}{ref.replace('ref_', 'r')}"
        tag = '' if box in {'', 'g0r0'} else box
        return 'mosaic', tag
    return 'other', ''


def _mosaic_stage_label(stage: str, tag: str) -> str:
    if stage == 'mosaic':
        return 'mosaic' if not tag else f'mosaic {tag}'
    if tag == 'l3':
        return 'align L3'
    if tag == 'prelim':
        return 'align prelim'
    if stage == 'align':
        return 'align'
    return stage


def _obs_date_label(date_obs: str | None) -> str:
    text = str(date_obs or '').strip()
    return text.split('T', 1)[0] if text else ''


def _mosaic_labels(inst: str | None, filt: str | None, date_obs: str | None, filename: str, *, dolphot: bool) -> tuple[str, str]:
    base = ' '.join(part for part in (inst, filt) if part) or filename
    day = _obs_date_label(date_obs)
    label = f'{base} · {day}' if day else base
    option = f'{label} (DOLPHOT reference)' if dolphot else label
    return label, option


def _disambiguate_mosaic_labels(found: list[dict[str, Any]]) -> None:
    from collections import Counter

    counts = Counter(item['option_label'] for item in found)
    for item in found:
        if counts[item['option_label']] <= 1:
            continue
        stamp = str(item.get('date_obs') or '')
        base = ' '.join(part for part in (item.get('instrument'), item.get('filter')) if part) or item['filename']
        # Prefer the full timestamp when present; otherwise keep stage context.
        if 'T' in stamp:
            item['label'] = f'{base} · {stamp}'
        else:
            stage = str(item.get('stage_label') or '').strip()
            day = _obs_date_label(stamp)
            core = f'{base} · {day}' if day else base
            item['label'] = f'{core} · {stage}' if stage else core
        if item.get('is_dolphot_reference'):
            item['option_label'] = f'{item["label"]} (DOLPHOT reference)'
        else:
            item['option_label'] = item['label']


def _mosaic_id(stage: str, instrument: str, filt: str, tag: str) -> str:
    parts = [stage or 'image', instrument or 'unk', filt or 'unk']
    if tag:
        parts.append(tag)
    return '-'.join(re.sub(r'[^a-z0-9]+', '', part.lower()) or 'x' for part in parts)


def _mosaic_visit_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get('instrument') or '').upper(),
        str(item.get('filter') or '').upper(),
        _obs_date_label(item.get('date_obs')),
    )


def _align_rank(item: dict[str, Any]) -> tuple[int, int]:
    """Prefer JHAT L3 over prelim, then larger area."""
    label = str(item.get('stage_label') or '')
    prefer = 2 if 'L3' in label or label.endswith('l3') else 1 if 'prelim' in label else 0
    return (prefer, int(item.get('area') or 0))


def _dedupe_mosaic_by_visit(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One product per visit/filter unless align is a true larger full field.

    Mosaic / DOLPHOT stamps are always kept. Align (prelim / L3) products for the
    same instrument+filter+night are dropped when they are essentially the same
    coadd (~same area); kept only when area is at least 2× the mosaic stamp.
    """
    from collections import defaultdict

    mosaics = [item for item in found if item.get('stage') == 'mosaic']
    aligns = [item for item in found if item.get('stage') == 'align']
    other = [item for item in found if item.get('stage') not in {'mosaic', 'align'}]

    by_visit: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in mosaics:
        by_visit[_mosaic_visit_key(item)].append(item)

    kept_align: list[dict[str, Any]] = []
    align_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for item in aligns:
        align_groups[_mosaic_visit_key(item)].append(item)

    for key, group in align_groups.items():
        best = max(group, key=_align_rank)
        peers = by_visit.get(key) or []
        if not peers:
            best['is_full_field'] = True
            kept_align.append(best)
            continue
        peer_area = max(int(item.get('area') or 0) for item in peers)
        if peer_area > 0 and int(best.get('area') or 0) >= peer_area * 2:
            best['is_full_field'] = True
            kept_align.append(best)

    # Same-filter mosaic that covers ~the full align footprint is the full field.
    for item in mosaics:
        item['is_full_field'] = False
    for key, peers in by_visit.items():
        align_peer = next((row for row in kept_align if _mosaic_visit_key(row) == key), None)
        if align_peer is not None:
            continue
        # No separate align product: the mosaic itself is what the viewer shows.
        largest = max(peers, key=lambda row: int(row.get('area') or 0))
        largest['is_full_field'] = True

    return mosaics + kept_align + other


def discover_mosaic_images(base_dir: Path) -> list[dict[str, Any]]:
    """Science coadds for the viewer dropdown (full-field + DOLPHOT boxes)."""
    root = Path(base_dir)
    # Only the primary DOLPHOT detection image (first img0_file) gets the
    # "(DOLPHOT reference)" label — other boxes may also have img0 files.
    stamp = discover_reference_image(root)
    stamp_filt = None
    stamp_inst = None
    stamp_name = stamp.name if stamp is not None else None
    try:
        stamp_resolved = stamp.resolve() if stamp is not None else None
    except OSError:
        stamp_resolved = None
    if stamp is not None:
        stamp_header = read_image_header(stamp)
        stamp_filt = (
            _filter_from_name(stamp.name)
            or display_filter(stamp_header.get('filter'))
        )
        stamp_inst = (
            _instrument_from_name(stamp.name)
            or (str(stamp_header.get('instrument') or '').strip().upper() or None)
        )

    search_roots = (
        root / 'reduction' / 'reference',
        root / 'reduction' / 'reference_prelim',
        root / 'reduction' / 'jhat_hst' / 'l3_ref',
        root / 'reduction' / 'jhat' / 'l3_ref',
    )
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    used_ids: set[str] = set()
    for search in search_roots:
        if not search.is_dir():
            continue
        paths = sorted(search.rglob('coadd_*.fits')) if search.name == 'reference' else sorted(search.glob('coadd_*.fits'))
        for path in paths:
            if not _is_science_coadd(path):
                continue
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            header = read_image_header(path)
            inst = (
                _instrument_from_name(path.name)
                or (str(header.get('instrument') or '').strip().upper() or None)
                or display_filter(instrument_name(path))
            )
            filt = (
                _filter_from_name(path.name)
                or display_filter(header.get('filter'))
            )
            stage, tag = _mosaic_stage(path)
            if stage not in {'mosaic', 'align'}:
                continue
            area = int(header.get('nx') or 0) * int(header.get('ny') or 0)
            image_id = _mosaic_id(stage, inst or 'unk', filt or 'unk', tag)
            if image_id in used_ids:
                image_id = _mosaic_id(stage, inst or 'unk', filt or 'unk', tag or path.stem)
            used_ids.add(image_id)
            is_dolphot = bool(
                stamp_resolved is not None and resolved == stamp_resolved
            ) or bool(stamp_name and path.name == stamp_name and stage == 'mosaic')
            date_obs = header.get('date_obs')
            label, option = _mosaic_labels(inst, filt, date_obs, path.name, dolphot=is_dolphot)
            found.append(
                {
                    'id': image_id,
                    'path': str(path),
                    'filename': path.name,
                    'instrument': inst,
                    'filter': filt,
                    'date_obs': date_obs,
                    'stage': stage,
                    'stage_label': _mosaic_stage_label(stage, tag),
                    'label': label,
                    'option_label': option,
                    'is_dolphot_reference': is_dolphot,
                    # Refined after visit dedupe; align-only rows become full field there.
                    'is_full_field': False,
                    'nx': header.get('nx'),
                    'ny': header.get('ny'),
                    'area': area,
                    'heading': reference_heading(header),
                    'selected': False,
                }
            )

    found = _dedupe_mosaic_by_visit(found)

    def _sort_key(item: dict[str, Any]) -> tuple:
        # Full-field first, then boxed mosaics; prefer dolphot filter.
        full = 0 if item.get('is_full_field') else 1
        same_filt = 0 if stamp_filt and item.get('filter') == stamp_filt else 1
        return (
            full,
            same_filt,
            str(item.get('instrument') or ''),
            str(item.get('filter') or ''),
            str(item.get('date_obs') or ''),
            str(item.get('stage_label') or ''),
            item['filename'],
        )

    found.sort(key=_sort_key)
    _disambiguate_mosaic_labels(found)

    # Default: largest full-field mosaic matching the DOLPHOT instrument+filter
    # (so overlays land on the same sky), else same filter, else the DOLPHOT
    # stamp, else any full-field / first entry.
    chosen = None
    full = [item for item in found if item.get('is_full_field')]

    def _best(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
        return max(rows, key=lambda item: int(item.get('area') or 0)) if rows else None

    if stamp_inst and stamp_filt:
        chosen = _best(
            [
                item
                for item in full
                if item.get('instrument') == stamp_inst and item.get('filter') == stamp_filt
            ]
        )
    if chosen is None and stamp_filt:
        chosen = _best([item for item in full if item.get('filter') == stamp_filt])
    if chosen is None:
        chosen = next((item for item in found if item['is_dolphot_reference']), None)
    if chosen is None:
        chosen = _best(full)
    if chosen is None and found:
        for want in ('F814W', 'F625W', 'F606W'):
            chosen = next((item for item in found if item.get('filter') == want), None)
            if chosen is not None:
                break
        chosen = chosen or found[0]
    if chosen is not None:
        chosen['selected'] = True
    return found


def resolve_display_image(base_dir: Path, image_id: str | None = None) -> Path | None:
    mosaics = discover_mosaic_images(base_dir)
    if image_id:
        for item in mosaics:
            if item['id'] == image_id:
                return Path(item['path'])
    for item in mosaics:
        if item.get('selected'):
            return Path(item['path'])
    return discover_display_image(base_dir) or discover_reference_image(base_dir)


def _passes_cuts(parts: list[str], cuts: dict[str, Any]) -> bool:
    if len(parts) < 11:
        return False
    try:
        snr = float(parts[5])
        sharp = float(parts[6])
        crowd = float(parts[9])
        obj_type = int(float(parts[10]))
    except (ValueError, IndexError):
        return False
    if obj_type not in set(cuts['types']):
        return False
    if abs(sharp) > float(cuts['sharp_max']):
        return False
    if crowd > float(cuts['crowd_max']):
        return False
    if cuts.get('snr_min') is not None and snr < float(cuts['snr_min']):
        return False
    return True


def summarize_catalog(phot: Path, cuts: dict[str, Any] | None = None) -> dict[str, Any]:
    cuts = cuts or quality_cuts()
    try:
        mtime = phot.stat().st_mtime
    except OSError:
        mtime = 0.0
    cache_key = (str(phot), mtime, json.dumps(cuts, sort_keys=True, default=str))
    cached = _CATALOG_SUMMARY_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    n_in = 0
    n_out = 0
    rejected = {'type': 0, 'sharp': 0, 'crowd': 0, 'snr': 0, 'short': 0}
    with phot.open() as handle:
        for line in handle:
            parts = line.split()
            if len(parts) < 11:
                rejected['short'] += 1
                continue
            n_in += 1
            try:
                snr = float(parts[5])
                sharp = float(parts[6])
                crowd = float(parts[9])
                obj_type = int(float(parts[10]))
            except (ValueError, IndexError):
                rejected['short'] += 1
                continue
            if obj_type not in set(cuts['types']):
                rejected['type'] += 1
                continue
            if abs(sharp) > float(cuts['sharp_max']):
                rejected['sharp'] += 1
                continue
            if crowd > float(cuts['crowd_max']):
                rejected['crowd'] += 1
                continue
            if cuts.get('snr_min') is not None and snr < float(cuts['snr_min']):
                rejected['snr'] += 1
                continue
            n_out += 1
    summary = {
        'path': str(phot),
        'name': phot.name,
        'stem': phot.stem,
        'hdf5_name': phot.stem + '.h5',
        'n_before': n_in,
        'n_after': n_out,
        'rejected': rejected,
        'cuts': {
            'types': list(cuts['types']),
            'sharp_max': cuts['sharp_max'],
            'crowd_max': cuts['crowd_max'],
            'snr_min': cuts.get('snr_min'),
        },
    }
    _CATALOG_SUMMARY_CACHE[cache_key] = summary
    return dict(summary)


def _mark_reference_mags(mags: list[dict[str, Any]], header: dict[str, Any] | None) -> list[dict[str, Any]]:
    inst = str((header or {}).get('instrument') or '').upper()
    filt = str((header or {}).get('filter') or '').upper()
    for row in mags:
        row['is_reference'] = bool(
            inst and filt and row.get('instrument') == inst and row.get('filter') == filt
        )
    return mags


def catalog_sources(
    phot: Path,
    *,
    cuts: dict[str, Any] | None = None,
    limit: int | None = None,
    reference: Path | None = None,
    wcs: dict[str, Any] | None = None,
    header: dict[str, Any] | None = None,
    base_dir: Path | None = None,
) -> list[dict[str, Any]]:
    cuts = cuts or quality_cuts()
    header = header or (read_image_header(reference) if reference else {})
    wcs = wcs or header.get('wcs')
    columns = Path(str(phot) + '.columns')
    root = Path(base_dir) if base_dir is not None else (phot.parent.parent.parent if phot.parent.parent else phot.parent)
    search_dirs = [
        phot.parent,
        phot.parent.parent,
        root / 'reduction' / 'jhat',
        root / 'reduction' / 'jhat_hst',
        Path(header['path']).parent if header.get('path') else None,
        reference.parent if reference is not None else None,
    ]
    plan = build_filter_plan(
        columns,
        search_dirs=[path for path in search_dirs if path],
        reference_header=header,
    )
    sources: list[dict[str, Any]] = []
    with phot.open() as handle:
        for idx, line in enumerate(handle, start=1):
            parts = line.split()
            if len(parts) < 11:
                continue
            try:
                x = float(parts[2])
                y = float(parts[3])
                snr = float(parts[5])
                sharp = float(parts[6])
                crowd = float(parts[9])
                obj_type = int(float(parts[10]))
            except (ValueError, IndexError):
                continue
            sky = pix_to_world(x, y, wcs)
            try:
                chi = float(parts[4])
            except (ValueError, IndexError):
                chi = None
            try:
                roundness = float(parts[7])
            except (ValueError, IndexError):
                roundness = None
            sources.append(
                {
                    'index': idx,
                    'x': x,
                    'y': y,
                    'ra': None if sky is None else sky[0],
                    'dec': None if sky is None else sky[1],
                    'snr': snr,
                    'sharp': sharp,
                    'crowd': crowd,
                    'chi': chi,
                    'roundness': roundness,
                    'type': obj_type,
                    'passed': _passes_cuts(parts, cuts),
                    'mags': _mark_reference_mags(row_ab_mags(parts, plan), header),
                }
            )
            if limit is not None and len(sources) >= limit:
                break
    return sources


def source_photometry(
    base_dir: Path,
    *,
    source_index: int,
    image_id: str | None = None,
) -> dict[str, Any] | None:
    """Per-epoch and filter-averaged AB photometry for one DOLPHOT source index."""
    from .preview import build_preview

    if source_index < 1:
        return None
    preview = build_preview(base_dir, image_id=image_id)
    display_path = Path(str(preview.get('source') or '')) if preview and preview.get('source') else None
    if display_path is None or not display_path.is_file():
        display_path = resolve_display_image(base_dir, image_id)
    phot = discover_phot_for_display(base_dir, image_id=image_id, display_path=display_path)
    if phot is None or not phot.is_file():
        return None
    stamp = discover_reference_for_phot(phot, base_dir) or discover_reference_image(base_dir)
    stamp_header = read_image_header(stamp) if stamp else {}
    columns = Path(str(phot) + '.columns')
    root = Path(base_dir)
    search_dirs = [
        phot.parent,
        phot.parent.parent,
        root / 'reduction' / 'jhat',
        root / 'reduction' / 'jhat_hst',
        stamp.parent if stamp is not None else None,
    ]
    epoch_plan = build_epoch_plan(columns, search_dirs=[path for path in search_dirs if path])
    line: str | None = None
    with phot.open() as handle:
        for idx, text in enumerate(handle, start=1):
            if idx == source_index:
                line = text
                break
    if line is None:
        return None
    parts = line.split()
    tables = source_photometry_tables(parts, epoch_plan)
    return {
        'index': source_index,
        'image_id': image_id,
        'phot': str(phot),
        'stamp': str(stamp) if stamp else None,
        'instrument': (preview or {}).get('instrument') or stamp_header.get('instrument'),
        'filter': (preview or {}).get('filter') or stamp_header.get('filter'),
        'epochs': tables['epochs'],
        'combined': tables['combined'],
    }


def _artifact_complete(
    base_dir: Path,
    stage_key: str,
    facts: dict[str, Any] | None = None,
) -> bool:
    facts = facts or {}
    if stage_key == 'download':
        if 'has_science' in facts:
            return bool(facts['has_science'])
        return has_science_fits(base_dir / 'download')
    if stage_key == 'align':
        if 'has_jhat' in facts:
            return bool(facts['has_jhat'])
        for rel in ('reduction/jhat', 'reduction/jhat_hst'):
            if _has_named_fits(base_dir / rel, '*_jhat.fits'):
                return True
        return False
    if stage_key == 'mosaic':
        if 'has_mosaic' in facts:
            return bool(facts['has_mosaic'])
        return has_mosaic_coadd(base_dir)
    if stage_key == 'prepare_dolphot':
        if 'has_param' in facts:
            return bool(facts['has_param'])
        for root in (base_dir / 'dolphot', base_dir / 'reduction'):
            if _has_named_fits(root, 'dolphot.param'):
                return True
        return False
    if stage_key == 'run_dolphot':
        if 'has_phot' in facts:
            return bool(facts['has_phot'])
        return has_phot_files(base_dir)
    if stage_key == 'combine_catalogs':
        if 'has_h5' in facts:
            return bool(facts['has_h5'])
        for root in (base_dir / 'dolphot', base_dir / 'reduction'):
            if _has_named_fits(root, '*.h5'):
                return True
        return False
    return False


def infer_stages(
    base_dir: Path,
    stored: dict[str, Any] | None = None,
    *,
    detailed: bool = True,
    facts: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    stored = stored or {}
    stored_stages = stored.get('stages') or {}
    running = stored.get('state') == 'running' and pid_is_running(stored.get('pid'))
    if detailed:
        _ensure_missing_stage_logs(base_dir)
    download_state = (stored_stages.get('download') or {}).get('state')
    stored_empty = any(
        bool((stored_stages.get(spec.key) or {}).get('empty_mast')) for spec in STAGES
    )
    if facts and facts.get('has_science'):
        empty_mast = False
    elif not detailed and download_state in {'completed', 'skipped'} and not stored_empty:
        empty_mast = False
    elif not detailed and download_state not in {None, 'error'} and not stored_empty:
        empty_mast = False
    else:
        empty_mast = is_empty_mast_download(base_dir)
    stored_unusable = any(
        bool((stored_stages.get(spec.key) or {}).get('unusable')) for spec in STAGES
    )
    unusable = stored_unusable or (
        (not empty_mast) and is_unusable_hst_download(base_dir)
    )
    rows = []
    for spec in STAGES:
        record = stored_stages.get(spec.key) or {}
        state = record.get('state')
        trust_stored = (not detailed) and state in {'completed', 'error', 'skipped'}
        artifact_done = False if trust_stored else _artifact_complete(base_dir, spec.key, facts)
        # Treat empty MAST as a finished download even when status was never
        # written (infer without stored) or was left as pending/error.
        if empty_mast and spec.key == 'download' and state in {None, 'error', 'pending'}:
            state = 'completed'
        elif empty_mast and spec.key != 'download' and state in {None, 'error', 'pending'}:
            state = 'skipped'
        elif unusable and spec.key == 'download' and state in {None, 'error', 'pending'}:
            state = 'completed'
        elif unusable and spec.key != 'download' and state in {None, 'error', 'pending'}:
            state = 'skipped'
        if running and state == 'running':
            pass
        elif trust_stored:
            pass
        elif state in {'completed', 'error', 'skipped'}:
            if artifact_done and state != 'error':
                state = 'completed'
        elif artifact_done:
            state = 'completed'
        else:
            state = 'pending'

        start = _parse_stored_time(record.get('started_at'))
        end = _parse_stored_time(record.get('ended_at'))
        log_path = record.get('log')
        seconds = record.get('seconds')
        try:
            seconds = None if seconds is None else float(seconds)
        except (TypeError, ValueError):
            seconds = None
        if detailed and (start is None or seconds is None):
            logs = _latest_logs(base_dir / 'logs', spec.log_prefixes)
            if logs:
                log_path = logs[-1]
                log_start, log_end = _log_times(log_path, detailed=True)
                start = start or log_start
                end = end or log_end
                if seconds is None:
                    seconds = _parse_elapsed_seconds(log_path)
        if seconds is None:
            seconds = _duration_seconds(start, end)

        rows.append(
            {
                'key': spec.key,
                'label': spec.label,
                'cli': spec.cli,
                'description': spec.description,
                'state': state,
                'started_at': _format_timestamp(start),
                'ended_at': _format_timestamp(end),
                'seconds': seconds,
                'duration': _format_duration(seconds),
                'log': str(log_path) if log_path else record.get('log'),
            }
        )
    return rows


def remaining_stages(stage_rows: list[dict[str, Any]]) -> list[str]:
    return [
        row['key']
        for row in stage_rows
        if row['state'] not in {'completed', 'running', 'skipped'}
    ]


def running_jobs() -> list[dict[str, Any]]:
    jobs = []
    for spec in campaign_targets():
        stored = read_status_file(spec.base_dir)
        if stored.get('state') != 'running' or not pid_is_running(stored.get('pid')):
            continue
        jobs.append(
            {
                'name': spec.name,
                'display_name': spec.display_name,
                'pid': stored.get('pid'),
                'message': stored.get('message') or 'running',
                'started_at': stored.get('started_at'),
            }
        )
    return jobs


def dispatch_availability(target=None, jobs=None, max_jobs=None) -> dict[str, Any]:
    live = list(jobs if jobs is not None else running_jobs())
    limit = max_concurrent_jobs() if max_jobs is None else max(1, int(max_jobs))
    target_job = None
    if target is not None:
        want = getattr(target, 'name', None)
        target_job = next((job for job in live if job.get('name') == want), None)
    if target_job:
        label = getattr(target, 'display_name', None) or target_job.get('display_name') or 'this target'
        return {
            'allowed': False,
            'reason': 'target_running',
            'message': f'A job is already running for {label}. Wait for it to finish.',
            'running': len(live),
            'max_jobs': limit,
            'jobs': live,
        }
    if len(live) >= limit:
        if limit == 1 and live:
            other = live[0].get('display_name') or live[0].get('name') or 'another target'
            message = f'A job is already running for {other}. Wait until it finishes.'
        else:
            message = f'{len(live)} of {limit} jobs are already running. Wait until a slot is free.'
        return {
            'allowed': False,
            'reason': 'capacity',
            'message': message,
            'running': len(live),
            'max_jobs': limit,
            'jobs': live,
        }
    if limit == 1:
        message = 'Ready to run. Only one job can run at a time.'
    else:
        message = f'Ready to run. {len(live)} of {limit} job slots in use.'
    return {
        'allowed': True,
        'reason': 'ok',
        'message': message,
        'running': len(live),
        'max_jobs': limit,
        'jobs': live,
    }


def list_campaign_targets(program: str | None = None, *, refresh_distances: bool = False) -> list[dict[str, Any]]:
    from .campaign_index import list_targets_from_db
    from .mast_updates import _updates_cache_key, updates_by_target

    cache_key = (str(program or ''), _updates_cache_key(program), 'orm')
    now = time.monotonic()
    with _LIST_LOCK:
        hit = _LIST_CACHE.get(cache_key)
        if hit and now - hit[0] < _LIST_TTL_SEC:
            return [dict(row) for row in hit[1]]

    orm_rows = list_targets_from_db(program)
    if orm_rows is not None:
        if refresh_distances:
            from .config import find_target

            warm = []
            for row in orm_rows:
                if row.get('distance_display'):
                    continue
                spec = find_target(row.get('name') or '')
                if spec is None:
                    continue
                warm.append(
                    {
                        'host': spec.host,
                        'ra': spec.ra,
                        'dec': spec.dec,
                        'base_dir': spec.base_dir,
                    }
                )
            if warm:
                warm_host_distances(warm)
        with _LIST_LOCK:
            _LIST_CACHE[cache_key] = (time.monotonic(), orm_rows)
        return [dict(row) for row in orm_rows]

    cache_key = (str(program or ''), _updates_cache_key(program), 'disk')
    with _LIST_LOCK:
        hit = _LIST_CACHE.get(cache_key)
        if hit and now - hit[0] < _LIST_TTL_SEC:
            return [dict(row) for row in hit[1]]

    live = {job['name']: job for job in running_jobs()}
    targets = list(campaign_targets(program))
    mast_flags = updates_by_target(program)
    host_sky: dict[str, dict[str, Any]] = {}
    for target in targets:
        key = ''.join(ch for ch in str(target.host or '').upper() if ch.isalnum())
        if not key:
            continue
        role = getattr(target, 'field_role', 'prime') or 'prime'
        current = host_sky.get(key)
        if current is None or role != 'parallel':
            host_sky[key] = {
                'host': target.host,
                'ra': target.ra,
                'dec': target.dec,
                'base_dir': target.base_dir,
                'display_name': getattr(target, 'display_name', None),
            }
    host_distance: dict[str, Any] = {}
    missing: list[dict[str, Any]] = []
    for key, sky in host_sky.items():
        record = lookup_host_distance(
            host=sky['host'],
            ra=sky['ra'],
            dec=sky['dec'],
            base_dir=sky['base_dir'],
            remote=False,
            display_name=sky.get('display_name'),
        )
        host_distance[key] = record
        if record is None or record.get('catalog') != 'NED':
            missing.append(
                {
                    'host': sky['host'],
                    'ra': sky['ra'],
                    'dec': sky['dec'],
                    'base_dir': sky['base_dir'],
                    'display_name': sky.get('display_name'),
                }
            )
    if refresh_distances and missing:
        warm_host_distances(missing)
    rows = []
    for target in targets:
        root = target.base_dir
        stored = read_status_file(root)
        stored_stages = stored.get('stages') or {}
        stored_complete = all(
            (stored_stages.get(spec.key) or {}).get('state') in {'completed', 'skipped', 'error'}
            for spec in STAGES
        )
        if stored and 'n_images' in stored:
            n_images = int(stored.get('n_images') or 0)
        else:
            n_images = count_science_fits(root / 'download')
            _persist_n_images(root, stored, n_images)
        facts = {'has_science': n_images > 0, 'n_images': n_images}
        if stored_complete:
            facts['has_phot'] = (stored_stages.get('run_dolphot') or {}).get('state') == 'completed'
            facts['has_mosaic'] = (stored_stages.get('mosaic') or {}).get('state') == 'completed'
        else:
            facts['has_phot'] = has_phot_files(root)
            facts['has_mosaic'] = has_mosaic_coadd(root)
        stages = infer_stages(root, stored, detailed=False, facts=facts)
        remaining = remaining_stages(stages)
        n_done = sum(1 for row in stages if row['state'] in {'completed', 'skipped'})
        host_key = ''.join(ch for ch in str(target.host or '').upper() if ch.isalnum())
        distance = host_distance.get(host_key)
        job = live.get(target.name)
        flag = mast_flags.get(target.name) or {}
        new_data = bool(flag.get('new_available'))
        n_new_obs = int(flag.get('n_pending') or 0)
        if job:
            job_state = 'running'
        elif new_data:
            job_state = 'new'
        elif not remaining:
            job_state = 'completed'
        else:
            job_state = 'pending'
        from .status_tags import derive_status_tag, status_label_for_row

        status_tag = derive_status_tag(
            job_state=job_state,
            n_images=n_images,
            new_data=new_data,
            remaining=remaining,
            stages=stages,
        )
        status = status_label_for_row(
            status_tag, n_images=n_images, n_new_obs=n_new_obs, remaining=remaining
        )
        rows.append(
            {
                'name': target.name,
                'display_name': target.display_name,
                'program_id': target.program_id,
                'host': target.host,
                'field_role': getattr(target, 'field_role', 'prime') or 'prime',
                'sn_type': getattr(target, 'sn_type', '') or '',
                'ra': target.ra,
                'dec': target.dec,
                'ra_sex': target.ra_sex,
                'dec_sex': target.dec_sex,
                'distance_display': format_distance(distance),
                'n_images': n_images,
                'n_done': n_done,
                'n_stages': len(stages),
                'remaining': remaining,
                'status': status,
                'status_tag': status_tag,
                'job_state': job_state,
                'new_data': new_data,
                'n_new_obs': n_new_obs,
                'has_catalog': bool(facts.get('has_phot')),
                'has_reference': bool(facts.get('has_mosaic')),
            }
        )
    with _LIST_LOCK:
        _LIST_CACHE[cache_key] = (time.monotonic(), rows)
    return [dict(row) for row in rows]


def page_inventory_path(base_dir: Path) -> Path:
    return status_dir(base_dir) / 'page_inventory.json'


def _page_inventory_stamp(base_dir: Path, stored: dict[str, Any] | None = None) -> dict[str, Any]:
    stored = stored if stored is not None else read_status_file(base_dir)
    return {
        'ended_at': stored.get('ended_at'),
        'state': stored.get('state'),
        'n_images': stored.get('n_images'),
        'status_mtime': _file_mtime(status_path(base_dir)),
    }


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        return 0.0


def load_page_inventory(base_dir: Path) -> dict[str, Any] | None:
    path = page_inventory_path(base_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if data.get('stamp') != _page_inventory_stamp(base_dir):
        return None
    return data


def save_page_inventory(base_dir: Path, payload: dict[str, Any], stored: dict[str, Any] | None = None) -> None:
    dest = page_inventory_path(base_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = dict(payload)
    body['stamp'] = _page_inventory_stamp(base_dir, stored)
    tmp = dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(body, default=str))
    tmp.replace(dest)


def clear_target_page_caches(base_dir: Path) -> None:
    root = status_dir(base_dir)
    if not root.is_dir():
        return
    for path in [page_inventory_path(base_dir), *root.glob('sources_*.json')]:
        try:
            path.unlink()
        except OSError:
            continue


def build_page_inventory(base_dir: Path, stored: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(base_dir)
    images = list_images(root)
    phot_files = discover_phot_files(root)
    catalogs = [summarize_catalog(path) for path in phot_files]
    mosaics = discover_mosaic_images(root)
    selected = next((item for item in mosaics if item.get('selected')), None)
    reference = Path(selected['path']) if selected else (discover_display_image(root) or discover_reference_image(root))
    reference_header = read_image_header(reference) if reference else {}
    payload = {
        'images': images,
        'n_images': len(images),
        'catalogs': catalogs,
        'mosaics': mosaics,
        'has_catalog': bool(catalogs),
        'reference_image': str(reference) if reference else None,
        'reference': {
            'id': None if selected is None else selected['id'],
            'path': str(reference) if reference else None,
            'instrument': reference_header.get('instrument'),
            'detector': reference_header.get('detector'),
            'filter': reference_header.get('filter'),
            'date_obs': reference_header.get('date_obs'),
            'heading': reference_heading(reference_header) if reference else 'Reference image',
        },
        'viewer_ready': bool(reference),
    }
    save_page_inventory(root, payload, stored)
    try:
        from .campaign_index import sync_science_products
        from .config import find_target

        spec = find_target(root.name)
        if spec is not None:
            sync_science_products(spec.name, payload)
    except Exception:
        pass
    return payload


def warm_page_inventory(base_dir: Path) -> None:
    if load_page_inventory(base_dir) is not None:
        return

    def _run() -> None:
        try:
            build_page_inventory(base_dir)
        except Exception:
            return

    threading.Thread(target=_run, name='page-inventory', daemon=True).start()


def warm_mosaic_previews(base_dir: Path) -> None:
    """Build JPEG previews + source overlays for every mosaic in the background."""

    def _run() -> None:
        try:
            from .preview import build_preview

            for item in discover_mosaic_images(base_dir):
                image_id = str(item.get('id') or '') or None
                try:
                    meta = build_preview(base_dir, image_id=image_id)
                except Exception:
                    meta = None
                if meta is None:
                    continue
                try:
                    ensure_sources_overlay(base_dir, image_id=image_id, meta=meta)
                except Exception:
                    continue
        except Exception:
            return

    threading.Thread(target=_run, name='mosaic-previews', daemon=True).start()


def rebuild_page_artifacts(base_dir: Path, *, include_preview: bool = True) -> dict[str, Any]:
    """Force-build page inventory (and optionally PNG preview) for a target."""
    clear_target_page_caches(base_dir)
    inventory = build_page_inventory(base_dir)
    if include_preview:
        try:
            from .preview import build_preview

            build_preview(base_dir, force=True)
        except Exception:
            pass
    return inventory


def sources_cache_path(base_dir: Path, image_id: str | None = None) -> Path:
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in str(image_id or 'default'))
    return status_dir(base_dir) / f'sources_{safe[:120]}.json'


def load_sources_overlay(base_dir: Path, image_id: str | None, stamp: dict[str, Any]) -> dict[str, Any] | None:
    path = sources_cache_path(base_dir, image_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if data.get('stamp') != stamp:
        return None
    return data.get('payload')


def save_sources_overlay(
    base_dir: Path,
    image_id: str | None,
    stamp: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    dest = sources_cache_path(base_dir, image_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.json.tmp')
    tmp.write_text(json.dumps({'stamp': stamp, 'payload': payload}, default=str))
    tmp.replace(dest)


_OVERLAY_REJECT_CAP = 8000


def _round_overlay(value: Any, digits: int) -> Any:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return None


def slim_overlay_source(src: dict[str, Any]) -> dict[str, Any]:
    row = {
        'index': src.get('index'),
        'x': _round_overlay(src.get('x'), 2),
        'y': _round_overlay(src.get('y'), 2),
        'ra': _round_overlay(src.get('ra'), 7),
        'dec': _round_overlay(src.get('dec'), 7),
        'snr': _round_overlay(src.get('snr'), 2),
        'sharp': _round_overlay(src.get('sharp'), 3),
        'crowd': _round_overlay(src.get('crowd'), 3),
        'chi': _round_overlay(src.get('chi'), 3),
        'roundness': _round_overlay(src.get('roundness'), 3),
        'type': src.get('type'),
        'passed': bool(src.get('passed')),
    }
    mags = src.get('mags') or []
    if mags:
        row['mags'] = mags
    return row


def viewer_source_overlay(sources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
    n_total = len(sources)
    passed = [src for src in sources if src.get('passed')]
    rejected = [src for src in sources if not src.get('passed')]
    rejected.sort(key=lambda src: float(src.get('snr') or 0.0), reverse=True)
    overlay = [slim_overlay_source(src) for src in passed]
    overlay.extend(slim_overlay_source(src) for src in rejected[:_OVERLAY_REJECT_CAP])
    return overlay, n_total, len(passed)


def sources_overlay_stamp(
    *,
    image_id: str | None,
    meta: dict[str, Any],
    phot: Path | None,
    stamp: Path | None,
) -> dict[str, Any]:
    return {
        'image_id': image_id or '',
        'source': meta.get('source'),
        'source_mtime': meta.get('source_mtime'),
        'preview_version': meta.get('preview_version'),
        'phot': str(phot) if phot else '',
        'phot_mtime': phot.stat().st_mtime if phot is not None else 0.0,
        'stamp': str(stamp) if stamp else '',
        'stamp_mtime': stamp.stat().st_mtime if stamp is not None else 0.0,
        'pairing': 'phot-stamp-v3',
        'overlay': 'slim-v5',
    }


def ensure_sources_overlay(
    base_dir: Path,
    *,
    image_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build or reuse the cached catalog overlay for one mosaic option."""
    from .gaia import format_wcs_quality, load_gaia_overlay
    from .preview import build_preview

    preview = meta or build_preview(base_dir, image_id=image_id)
    if preview is None:
        return None
    display_path = Path(str(preview.get('source') or '')) if preview.get('source') else None
    if display_path is None or not display_path.is_file():
        display_path = resolve_display_image(base_dir, image_id)
    phot = discover_phot_for_display(base_dir, image_id=image_id, display_path=display_path)
    stamp = (
        discover_reference_for_phot(phot, base_dir)
        if phot is not None
        else discover_reference_image(base_dir)
    )
    cache_stamp = sources_overlay_stamp(image_id=image_id, meta=preview, phot=phot, stamp=stamp)
    cached = load_sources_overlay(base_dir, image_id, cache_stamp)
    if cached is not None:
        return cached
    stamp_header = read_image_header(stamp) if stamp else {}
    display_header = read_image_header(display_path) if display_path else {}
    # Prefer the displayed mosaic's instrument/filter for "reference" mag
    # highlighting; photometry itself still comes from the DOLPHOT stamp WCS.
    header = {
        'path': str(stamp) if stamp else preview.get('source'),
        'instrument': preview.get('instrument')
        or display_header.get('instrument')
        or stamp_header.get('instrument'),
        'detector': preview.get('detector')
        or display_header.get('detector')
        or stamp_header.get('detector'),
        'filter': preview.get('filter')
        or display_header.get('filter')
        or stamp_header.get('filter'),
        'photflam': preview.get('photflam')
        or display_header.get('photflam')
        or stamp_header.get('photflam'),
        'photplam': preview.get('photplam')
        or display_header.get('photplam')
        or stamp_header.get('photplam'),
        'wcs': stamp_header.get('wcs'),
    }
    sources: list[dict[str, Any]] = []
    if phot is not None:
        sources = catalog_sources(
            phot,
            reference=stamp,
            wcs=stamp_header.get('wcs'),
            header=header,
            base_dir=base_dir,
        )
    overlay_sources, n_total, n_passed = viewer_source_overlay(sources)
    gaia = load_gaia_overlay(
        base_dir,
        preview.get('wcs') or display_header.get('wcs') or stamp_header.get('wcs'),
    )
    display_inst = str(
        preview.get('instrument') or display_header.get('instrument') or ''
    ).upper()
    display_filt = str(preview.get('filter') or display_header.get('filter') or '').upper()
    stamp_inst = str(stamp_header.get('instrument') or '').upper()
    stamp_filt = str(stamp_header.get('filter') or '').upper()
    catalog_note = None
    if phot is not None and stamp_inst and display_inst:
        catalog_label = ' '.join(p for p in (stamp_inst, stamp_filt) if p)
        display_label = ' '.join(p for p in (display_inst, display_filt) if p)
        if stamp_inst != display_inst:
            # Cross-instrument overlay: positions from another camera's run.
            catalog_note = (
                f'Showing {catalog_label} DOLPHOT positions on {display_label} '
                f'(no {display_inst} catalog yet)'
            )
        elif stamp_filt and display_filt and stamp_filt != display_filt:
            # Same multi-band DOLPHOT run; detection image differs from the
            # mosaic filter (e.g. ACS F606W stamp under an ACS F814W mosaic).
            catalog_note = (
                f'DOLPHOT detections from {catalog_label} reference on '
                f'{display_label} (same multi-band catalog)'
            )
    payload = {
        'reference': preview,
        'sources': overlay_sources,
        'n_sources': n_total,
        'n_passed': n_passed,
        'n_overlay': len(overlay_sources),
        'catalog_note': catalog_note,
        'gaia': gaia,
        'wcs_quality': format_wcs_quality(gaia),
    }
    save_sources_overlay(base_dir, image_id, cache_stamp, payload)
    return payload


def build_campaign_status(
    base_dir: Path | None = None,
    target=None,
    *,
    heavy: bool = True,
) -> dict[str, Any]:
    target = target or target_config()
    root = Path(base_dir) if base_dir is not None else target.base_dir
    stored = read_status_file(root)
    stages = infer_stages(root, stored, detailed=False)
    if heavy:
        inventory = build_page_inventory(root, stored)
    else:
        inventory = load_page_inventory(root) or {}
    images = inventory.get('images') or []
    catalogs = inventory.get('catalogs') or []
    mosaics = inventory.get('mosaics') or []
    reference = inventory.get('reference') or {}
    n_images = inventory.get('n_images')
    if n_images is None:
        n_images = stored.get('n_images')
        if n_images is None:
            n_images = len(images)
    job_state = stored.get('state') or 'idle'
    if job_state == 'running' and not pid_is_running(stored.get('pid')):
        job_state = stored.get('error') and 'error' or 'stale'
    distance = lookup_host_distance(
        host=target.host,
        ra=target.ra,
        dec=target.dec,
        base_dir=root,
        remote=False,
        display_name=getattr(target, 'display_name', None),
    )
    from .mast_updates import updates_by_target

    flag = updates_by_target(target.program_id).get(target.name) or {}
    mosaic_done = ((stored.get('stages') or {}).get('mosaic') or {}).get('state') == 'completed'
    phot_done = ((stored.get('stages') or {}).get('run_dolphot') or {}).get('state') == 'completed'
    viewer_ready = bool(inventory.get('viewer_ready') or reference.get('path') or mosaic_done)
    remaining = remaining_stages(stages)
    new_data = bool(flag.get('new_available'))
    n_new_obs = int(flag.get('n_pending') or 0)
    from .status_tags import derive_status_tag, status_label_for_row

    status_tag = derive_status_tag(
        job_state=job_state,
        n_images=int(n_images or 0),
        new_data=new_data,
        remaining=remaining,
        stages=stages,
    )
    return {
        'target': {
            'name': target.name,
            'display_name': target.display_name,
            'program_id': target.program_id,
            'host': target.host,
            'field_role': getattr(target, 'field_role', 'prime') or 'prime',
            'ra': target.ra,
            'dec': target.dec,
            'ra_sex': target.ra_sex,
            'dec_sex': target.dec_sex,
            'radius_arcmin': target.radius_arcmin,
            'instruments': list(target.instruments),
            'telescope': target.telescope,
            'base_dir': str(root),
            'notes': target.notes,
            'distance_mpc': None if distance is None else distance.get('distance_mpc'),
            'distance_err_mpc': None if distance is None else distance.get('distance_err_mpc'),
            'distance_catalog': None if distance is None else distance.get('catalog'),
            'distance_display': format_distance(distance),
            'redshift': None if distance is None else distance.get('redshift'),
        },
        'job': {
            'state': job_state,
            'pid': stored.get('pid'),
            'started_at': stored.get('started_at'),
            'ended_at': stored.get('ended_at'),
            'message': stored.get('message'),
            'requested_stages': stored.get('requested_stages') or [],
        },
        'stages': stages,
        'remaining': remaining,
        'status_tag': status_tag,
        'status': status_label_for_row(
            status_tag,
            n_images=int(n_images or 0),
            n_new_obs=n_new_obs,
            remaining=remaining,
        ),
        'new_data': new_data,
        'n_new_obs': n_new_obs,
        'images': images,
        'n_images': int(n_images or 0),
        'catalogs': catalogs,
        'has_catalog': bool(catalogs or inventory.get('has_catalog') or phot_done),
        'reference_image': inventory.get('reference_image') or reference.get('path'),
        'reference': {
            'id': reference.get('id'),
            'path': reference.get('path'),
            'instrument': reference.get('instrument'),
            'detector': reference.get('detector'),
            'filter': reference.get('filter'),
            'date_obs': reference.get('date_obs'),
            'heading': reference.get('heading') or 'Reference image',
        },
        'mosaics': mosaics,
        'viewer_ready': viewer_ready,
        'inventory_ready': bool(inventory.get('images') or inventory.get('mosaics') or inventory.get('catalogs')),
        'dispatch': dispatch_availability(target),
    }
