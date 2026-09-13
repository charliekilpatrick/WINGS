"""Scan an st123 project directory for stage status, images, and catalogs."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .config import (
    STAGES,
    campaign_targets,
    max_concurrent_jobs,
    quality_cuts,
    status_path,
    target_config,
)
from .host_distance import format_distance, lookup_host_distance
from .photometry import build_filter_plan, row_ab_mags
from .sky import pix_to_world, read_image_header, reference_heading
from .st123api import display_filter, filter_names, instrument_name

_SCIENCE_SKIP = ('_pam.fits', '_c1m.fits')
_SCIENCE_SUFFIXES = ('_flc.fits', '_flt.fits', '_c0m.fits', '_cal.fits', '_i2d.fits')
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


def _science_fits(download_root: Path) -> list[Path]:
    if not download_root.is_dir():
        return []
    out: list[Path] = []
    for path in sorted(download_root.rglob('*.fits')):
        name = path.name.lower()
        if any(name.endswith(skip) for skip in _SCIENCE_SKIP):
            continue
        out.append(path)
    return out


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


def _log_times(path: Path) -> tuple[datetime | None, datetime | None]:
    start = None
    match = _LOG_NAME.match(path.name)
    if match:
        start = _parse_log_stamp(match.group('stamp'))
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
    shapes: list[tuple[int, int]] = []
    for hdu in hdul:
        name = str(getattr(hdu, 'name', '') or '').upper()
        if name and not name.startswith('SCI'):
            continue
        data = getattr(hdu, 'data', None)
        if data is None:
            continue
        ndim = getattr(data, 'ndim', 0)
        if ndim == 3:
            for plane in data:
                if getattr(plane, 'ndim', 0) >= 2:
                    shapes.append((int(plane.shape[-2]), int(plane.shape[-1])))
            continue
        if ndim >= 2:
            if name.startswith('SCI') or (name in {'', 'PRIMARY'} and not shapes):
                shapes.append((int(data.shape[-2]), int(data.shape[-1])))
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
        with fits.open(path, memmap=True) as hdul:
            header = hdul[0].header
            for hdu in hdul:
                if hdu.header.get('INSTRUME') or hdu.header.get('EXPTIME') or hdu.header.get('FILTER'):
                    header = hdu.header
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
    meta['exptime'] = _header_value(header, 'EXPTIME', 'TEXPTIME')
    meta['date_obs'] = _header_value(header, 'DATE-OBS', 'DATE_OBS')
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


def list_images(base_dir: Path) -> list[dict[str, Any]]:
    download_root = base_dir / 'download'
    paths = _science_fits(download_root)
    filters = filter_names(paths)
    rows = []
    for path in paths:
        meta = _fits_metadata(path, download_root)
        filt = display_filter(filters.get(str(path)))
        if filt:
            meta['filter'] = filt
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


def discover_reference_image(base_dir: Path) -> Path | None:
    for param in discover_param_files(base_dir):
        ref = None
        for line in param.read_text(errors='replace').splitlines():
            if line.strip().startswith('img0_file'):
                ref = line.split('=', 1)[-1].strip()
                break
        if not ref:
            continue
        for candidate in (
            param.parent / f'{ref}.fits',
            param.parent / ref,
            base_dir / 'reduction' / 'reference' / f'{ref}.fits',
        ):
            if candidate.is_file():
                return candidate
        matches = list((base_dir / 'reduction' / 'reference').rglob(f'{ref}.fits')) if (base_dir / 'reduction' / 'reference').is_dir() else []
        if matches:
            return matches[0]
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


def _mosaic_id(stage: str, instrument: str, filt: str, tag: str) -> str:
    parts = [stage or 'image', instrument or 'unk', filt or 'unk']
    if tag:
        parts.append(tag)
    return '-'.join(re.sub(r'[^a-z0-9]+', '', part.lower()) or 'x' for part in parts)


def discover_mosaic_images(base_dir: Path) -> list[dict[str, Any]]:
    """Science coadds from the mosaic step for the viewer dropdown."""
    root = Path(base_dir)
    stamp = discover_reference_image(root)
    stamp_name = stamp.name if stamp is not None else None
    try:
        stamp_resolved = stamp.resolve() if stamp is not None else None
    except OSError:
        stamp_resolved = None

    search_roots = (root / 'reduction' / 'reference',)
    found: list[dict[str, Any]] = []
    seen: set[Path] = set()
    used_ids: set[str] = set()
    for search in search_roots:
        if not search.is_dir():
            continue
        for path in sorted(search.rglob('coadd_*.fits')):
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
                display_filter(instrument_name(path))
                or (str(header.get('instrument') or '').strip().upper() or None)
                or _instrument_from_name(path.name)
            )
            filt = (
                display_filter(header.get('filter'))
                or _filter_from_name(path.name)
            )
            stage, tag = _mosaic_stage(path)
            if stage != 'mosaic':
                continue
            image_id = _mosaic_id(stage, inst or 'unk', filt or 'unk', tag)
            if image_id in used_ids:
                image_id = _mosaic_id(stage, inst or 'unk', filt or 'unk', tag or path.stem)
            used_ids.add(image_id)
            is_dolphot = bool(
                stamp_resolved is not None and resolved == stamp_resolved
            ) or bool(stamp_name and path.name == stamp_name)
            label = ' '.join(part for part in (inst, filt) if part) or path.name
            option = f'{label} (DOLPHOT reference)' if is_dolphot else label
            found.append(
                {
                    'id': image_id,
                    'path': str(path),
                    'filename': path.name,
                    'instrument': inst,
                    'filter': filt,
                    'stage': stage,
                    'stage_label': _mosaic_stage_label(stage, tag),
                    'label': label,
                    'option_label': option,
                    'is_dolphot_reference': is_dolphot,
                    'nx': header.get('nx'),
                    'ny': header.get('ny'),
                    'heading': reference_heading(header),
                    'selected': False,
                }
            )

    def _sort_key(item: dict[str, Any]) -> tuple:
        stage_rank = 0 if item['stage'] == 'mosaic' else 1
        return (
            stage_rank,
            str(item.get('instrument') or ''),
            str(item.get('filter') or ''),
            str(item.get('stage_label') or ''),
            item['filename'],
        )

    found.sort(key=_sort_key)
    chosen = next((item for item in found if item['is_dolphot_reference']), None)
    if chosen is None:
        mosaics = [item for item in found if item['stage'] == 'mosaic']
        for want in ('F814W', 'F625W', 'F606W'):
            chosen = next((item for item in mosaics if item.get('filter') == want), None)
            if chosen is not None:
                break
        chosen = chosen or (mosaics[0] if mosaics else (found[0] if found else None))
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
    return {
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


def _artifact_complete(base_dir: Path, stage_key: str) -> bool:
    if stage_key == 'download':
        return bool(_science_fits(base_dir / 'download'))
    if stage_key == 'align':
        for rel in ('reduction/jhat', 'reduction/jhat_hst'):
            root = base_dir / rel
            if root.is_dir() and any(root.rglob('*_jhat.fits')):
                return True
        return False
    if stage_key == 'mosaic':
        root = base_dir / 'reduction' / 'reference'
        return root.is_dir() and any(root.rglob('coadd_*.fits'))
    if stage_key == 'prepare_dolphot':
        return bool(discover_param_files(base_dir))
    if stage_key == 'run_dolphot':
        return bool(discover_phot_files(base_dir))
    if stage_key == 'combine_catalogs':
        return bool(discover_hdf5_files(base_dir))
    return False


def infer_stages(base_dir: Path, stored: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    stored = stored or {}
    stored_stages = stored.get('stages') or {}
    running = stored.get('state') == 'running' and pid_is_running(stored.get('pid'))
    _ensure_missing_stage_logs(base_dir)
    rows = []
    for spec in STAGES:
        record = stored_stages.get(spec.key) or {}
        artifact_done = _artifact_complete(base_dir, spec.key)
        state = record.get('state')
        if running and state == 'running':
            pass
        elif state in {'completed', 'error', 'skipped'}:
            if artifact_done and state != 'error':
                state = 'completed'
        elif artifact_done:
            state = 'completed'
        else:
            state = 'pending'

        logs = _latest_logs(base_dir / 'logs', spec.log_prefixes)
        start = end = None
        log_path = None
        seconds = None
        if logs:
            log_path = logs[-1]
            start, end = _log_times(log_path)
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
    return [row['key'] for row in stage_rows if row['state'] not in {'completed', 'running'}]


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


def list_campaign_targets() -> list[dict[str, Any]]:
    live = {job['name']: job for job in running_jobs()}
    rows = []
    for target in campaign_targets():
        root = target.base_dir
        stages = infer_stages(root)
        remaining = remaining_stages(stages)
        n_done = sum(1 for row in stages if row['state'] == 'completed')
        distance = lookup_host_distance(
            host=target.host,
            ra=target.ra,
            dec=target.dec,
            base_dir=root,
        )
        job = live.get(target.name)
        if job:
            status = 'running'
            job_state = 'running'
        elif not remaining:
            status = 'complete'
            job_state = 'completed'
        else:
            status = f'{remaining[0]} pending'
            job_state = 'pending'
        rows.append(
            {
                'name': target.name,
                'display_name': target.display_name,
                'host': target.host,
                'ra': target.ra,
                'dec': target.dec,
                'ra_sex': target.ra_sex,
                'dec_sex': target.dec_sex,
                'distance_display': format_distance(distance),
                'n_images': len(_science_fits(root / 'download')),
                'n_done': n_done,
                'n_stages': len(stages),
                'remaining': remaining,
                'status': status,
                'job_state': job_state,
                'has_catalog': bool(discover_phot_files(root)),
                'has_reference': bool(resolve_display_image(root)),
            }
        )
    return rows


def build_campaign_status(base_dir: Path | None = None, target=None) -> dict[str, Any]:
    target = target or target_config()
    root = Path(base_dir) if base_dir is not None else target.base_dir
    stored = read_status_file(root)
    stages = infer_stages(root, stored)
    images = list_images(root)
    phot_files = discover_phot_files(root)
    catalogs = [summarize_catalog(path) for path in phot_files]
    mosaics = discover_mosaic_images(root)
    selected = next((item for item in mosaics if item.get('selected')), None)
    reference = Path(selected['path']) if selected else resolve_display_image(root)
    reference_header = read_image_header(reference) if reference else {}
    job_state = stored.get('state') or 'idle'
    if job_state == 'running' and not pid_is_running(stored.get('pid')):
        job_state = stored.get('error') and 'error' or 'stale'
    distance = lookup_host_distance(
        host=target.host,
        ra=target.ra,
        dec=target.dec,
        base_dir=root,
    )
    return {
        'target': {
            'name': target.name,
            'display_name': target.display_name,
            'host': target.host,
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
        'remaining': remaining_stages(stages),
        'images': images,
        'n_images': len(images),
        'catalogs': catalogs,
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
        'mosaics': mosaics,
        'viewer_ready': bool(reference),
        'dispatch': dispatch_availability(target),
    }
