"""WCS helpers for the reference-image viewer."""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

def _header_get(header, *keys):
    for key in keys:
        if key in header and header[key] not in (None, '', 'N/A'):
            return header[key]
    return None


def separation_arcmin(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    """Great-circle distance in arcminutes between two ICRS positions."""
    r1, d1, r2, d2 = (math.radians(float(v)) for v in (ra1, dec1, ra2, dec2))
    hav = math.sin((d2 - d1) / 2.0) ** 2 + math.cos(d1) * math.cos(d2) * math.sin(
        (r2 - r1) / 2.0
    ) ** 2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(hav)))) * 60.0


def format_obs_datetime(date_obs: Any, time_obs: Any = None) -> str | None:
    """Format FITS DATE-OBS / TIME-OBS as ``YYYY-MM-DDTHH:MM:SS``."""
    date = str(date_obs or '').strip()
    time = str(time_obs or '').strip()
    if not date or date.upper() in {'N/A', 'NONE', 'UNKNOWN'}:
        return None
    if time.upper() in {'N/A', 'NONE', 'UNKNOWN'}:
        time = ''
    raw = date.replace(' ', 'T')
    if 'T' not in raw and time:
        raw = f'{date}T{time}'
    raw = raw.replace('Z', '')
    if '.' in raw:
        raw = raw.split('.', 1)[0]
    for fmt in (
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M',
        '%Y-%m-%d',
        '%Y/%m/%dT%H:%M:%S',
        '%Y/%m/%d',
    ):
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        if 'T' in raw or time:
            return parsed.strftime('%Y-%m-%dT%H:%M:%S')
        return parsed.strftime('%Y-%m-%d')
    return raw or None


def _cd_matrix(header) -> list[list[float]] | None:
    try:
        if 'CD1_1' in header:
            return [
                [float(header['CD1_1']), float(header.get('CD1_2', 0.0))],
                [float(header.get('CD2_1', 0.0)), float(header['CD2_2'])],
            ]
        cdelt1 = float(header['CDELT1'])
        cdelt2 = float(header['CDELT2'])
        crota = math.radians(float(header.get('CROTA2', header.get('CROTA1', 0.0)) or 0.0))
        cosr, sinr = math.cos(crota), math.sin(crota)
        return [
            [cdelt1 * cosr, -cdelt2 * sinr],
            [cdelt1 * sinr, cdelt2 * cosr],
        ]
    except (KeyError, TypeError, ValueError):
        return None


def tan_pix_to_world(
    x: float,
    y: float,
    crpix: list[float],
    crval: list[float],
    cd: list[list[float]],
) -> tuple[float, float]:
    """TAN projection from 1-indexed FITS pixels to ICRS degrees."""
    dx = float(x) - float(crpix[0])
    dy = float(y) - float(crpix[1])
    xi = math.radians(cd[0][0] * dx + cd[0][1] * dy)
    eta = math.radians(cd[1][0] * dx + cd[1][1] * dy)
    ra0 = math.radians(crval[0])
    dec0 = math.radians(crval[1])
    rho = math.hypot(xi, eta)
    if rho < 1e-15:
        return float(crval[0]), float(crval[1])
    cone = math.atan(rho)
    sinc, cosc = math.sin(cone), math.cos(cone)
    sin_dec = max(-1.0, min(1.0, cosc * math.sin(dec0) + eta * sinc * math.cos(dec0) / rho))
    dec = math.asin(sin_dec)
    ra = ra0 + math.atan2(xi * sinc, rho * math.cos(dec0) * cosc - eta * math.sin(dec0) * sinc)
    ra_deg = (math.degrees(ra) % 360.0 + 360.0) % 360.0
    return ra_deg, math.degrees(dec)


def pix_to_world(x: float, y: float, wcs: dict[str, Any] | None) -> tuple[float, float] | None:
    if not wcs:
        return None
    crpix = wcs.get('crpix')
    crval = wcs.get('crval')
    cd = wcs.get('cd')
    if not crpix or not crval or not cd:
        return None
    try:
        return tan_pix_to_world(x, y, crpix, crval, cd)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def tan_world_to_pix(
    ra: float,
    dec: float,
    crpix: list[float],
    crval: list[float],
    cd: list[list[float]],
) -> tuple[float, float]:
    """Inverse TAN: ICRS degrees to 1-indexed FITS pixels."""
    ra0 = math.radians(float(crval[0]))
    dec0 = math.radians(float(crval[1]))
    ra_r = math.radians(float(ra))
    dec_r = math.radians(float(dec))
    cosc = math.sin(dec0) * math.sin(dec_r) + math.cos(dec0) * math.cos(dec_r) * math.cos(ra_r - ra0)
    if cosc <= 0:
        raise ValueError('Coordinate is on the opposite hemisphere')
    xi = math.degrees(math.cos(dec_r) * math.sin(ra_r - ra0) / cosc)
    eta = math.degrees(
        (math.cos(dec0) * math.sin(dec_r) - math.sin(dec0) * math.cos(dec_r) * math.cos(ra_r - ra0))
        / cosc
    )
    det = cd[0][0] * cd[1][1] - cd[0][1] * cd[1][0]
    if abs(det) < 1e-30:
        raise ValueError('Singular CD matrix')
    dx = (cd[1][1] * xi - cd[0][1] * eta) / det
    dy = (-cd[1][0] * xi + cd[0][0] * eta) / det
    return float(crpix[0]) + dx, float(crpix[1]) + dy


def world_to_pix(ra: float, dec: float, wcs: dict[str, Any] | None) -> tuple[float, float] | None:
    if not wcs:
        return None
    crpix = wcs.get('crpix')
    crval = wcs.get('crval')
    cd = wcs.get('cd')
    if not crpix or not crval or not cd:
        return None
    try:
        return tan_world_to_pix(ra, dec, crpix, crval, cd)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def format_ra(ra: float) -> str:
    hours = (float(ra) / 15.0) % 24.0
    hh = int(hours)
    minutes = (hours - hh) * 60.0
    mm = int(minutes)
    ss = (minutes - mm) * 60.0
    return f'{hh:02d}:{mm:02d}:{ss:06.3f}'


def format_dec(dec: float) -> str:
    sign = '+' if float(dec) >= 0 else '-'
    adec = abs(float(dec))
    dd = int(adec)
    minutes = (adec - dd) * 60.0
    mm = int(minutes)
    ss = (minutes - mm) * 60.0
    return f'{sign}{dd:02d}:{mm:02d}:{ss:05.2f}'


def format_sky(ra: float | None, dec: float | None) -> str | None:
    if ra is None or dec is None:
        return None
    return f'{format_ra(ra)} {format_dec(dec)}'


_EQ_VALUE = re.compile(
    r'(?P<rah>\d+)\s+(?P<ram>\d+)\s+(?P<ras>[\d.]+)\s+'
    r'(?P<dsign>[+-])\s*(?P<ded>\d+)\s+(?P<dem>\d+)\s+(?P<des>[\d.]+)'
)


def parse_sky_pair(ra_text: str | None, dec_text: str | None) -> tuple[float, float] | None:
    """Parse decimal degrees or sexagesimal RA/Dec into ICRS degrees."""
    ra_raw = str(ra_text or '').strip()
    dec_raw = str(dec_text or '').strip()
    if not ra_raw or not dec_raw:
        return None
    try:
        return float(ra_raw), float(dec_raw)
    except ValueError:
        pass
    match = _EQ_VALUE.search(f'{ra_raw} {dec_raw}'.replace(':', ' '))
    if not match:
        return None
    ra = (
        float(match.group('rah'))
        + float(match.group('ram')) / 60.0
        + float(match.group('ras')) / 3600.0
    ) * 15.0
    dec = (
        float(match.group('ded'))
        + float(match.group('dem')) / 60.0
        + float(match.group('des')) / 3600.0
    )
    if match.group('dsign') == '-':
        dec = -dec
    return ra, dec


def ab_zeropoint(photflam: float | None, photplam: float | None) -> float | None:
    if not photflam or not photplam or photflam <= 0 or photplam <= 0:
        return None
    return -2.5 * math.log10(float(photflam)) - 5.0 * math.log10(float(photplam)) - 2.408


_HEADER_CACHE: dict[tuple[str, float], dict[str, Any]] = {}
_HEADER_CACHE_MAX = 256


def read_image_header(path: Path) -> dict[str, Any]:
    """Read WCS and identifying cards from a FITS science image."""
    try:
        mtime = Path(path).stat().st_mtime
    except OSError:
        mtime = 0.0
    cache_key = (str(path), mtime)
    cached = _HEADER_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    def _store(result: dict[str, Any]) -> dict[str, Any]:
        if len(_HEADER_CACHE) >= _HEADER_CACHE_MAX:
            _HEADER_CACHE.clear()
        _HEADER_CACHE[cache_key] = result
        return dict(result)

    meta: dict[str, Any] = {
        'path': str(path),
        'instrument': None,
        'detector': None,
        'filter': None,
        'date_obs': None,
        'exptime': None,
        'photflam': None,
        'photplam': None,
        'nx': None,
        'ny': None,
        'wcs': None,
    }
    from .st123api import display_filter

    name = Path(path).name
    match = re.search(r'_(f\d{3,4}[a-z0-9]+)_', name, re.IGNORECASE)
    if match:
        meta['filter'] = display_filter(match.group(1))
    try:
        from astropy.io import fits
        from astropy.wcs import FITSFixedWarning
        import warnings
    except Exception:
        return _store(meta)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FITSFixedWarning)
            with fits.open(path, memmap=True) as hdul:
                header = hdul[0].header
                wcs_header = None
                inst = detector = None
                date_obs = None
                time_obs = None
                exptime = None
                for hdu in hdul:
                    cards = getattr(hdu, 'header', None)
                    if cards is None:
                        continue
                    if wcs_header is None and 'CRVAL1' in cards and 'CRPIX1' in cards:
                        wcs_header = cards
                    if inst is None and cards.get('INSTRUME'):
                        inst = cards['INSTRUME']
                    if detector is None and cards.get('DETECTOR'):
                        detector = cards['DETECTOR']
                    if date_obs is None:
                        date_obs = _header_get(cards, 'DATE-OBS', 'DATE_OBS')
                    if time_obs is None:
                        time_obs = _header_get(cards, 'TIME-OBS', 'TIME_OBS')
                    if exptime is None:
                        exptime = _header_get(cards, 'TEXPTIME', 'EXPTIME')
                    if meta['photflam'] is None and 'PHOTFLAM' in cards:
                        try:
                            meta['photflam'] = float(cards['PHOTFLAM'])
                        except (TypeError, ValueError):
                            pass
                    if meta['photplam'] is None and 'PHOTPLAM' in cards:
                        try:
                            meta['photplam'] = float(cards['PHOTPLAM'])
                        except (TypeError, ValueError):
                            pass
                header = wcs_header or header
    except Exception:
        return _store(meta)

    meta['instrument'] = None if inst is None else str(inst).strip()
    meta['detector'] = None if detector is None else str(detector).strip()
    if not meta.get('filter'):
        filt = _header_get(header, 'FILTER', 'FILTNAM1', 'FILTER1')
        if filt:
            meta['filter'] = display_filter(str(filt))
    meta['date_obs'] = format_obs_datetime(date_obs, time_obs)
    try:
        meta['exptime'] = None if exptime is None else float(exptime)
    except (TypeError, ValueError):
        meta['exptime'] = None
    try:
        meta['nx'] = int(header['NAXIS1'])
        meta['ny'] = int(header['NAXIS2'])
    except (KeyError, TypeError, ValueError):
        pass

    cd = _cd_matrix(header)
    try:
        crpix = [float(header['CRPIX1']), float(header['CRPIX2'])]
        crval = [float(header['CRVAL1']), float(header['CRVAL2'])]
    except (KeyError, TypeError, ValueError):
        crpix = crval = None
    if cd and crpix and crval:
        meta['wcs'] = {
            'crpix': crpix,
            'crval': crval,
            'cd': cd,
            'ctype': [
                str(header.get('CTYPE1') or 'RA---TAN'),
                str(header.get('CTYPE2') or 'DEC--TAN'),
            ],
            'nx': meta['nx'],
            'ny': meta['ny'],
        }
    return _store(meta)


def reference_heading(meta: dict[str, Any] | None) -> str:
    if not meta:
        return 'Reference image'
    parts = ['Reference image']
    inst = meta.get('instrument') or ''
    detector = meta.get('detector') or ''
    if detector.isdigit():
        detector = ''
    filt = meta.get('filter') or ''
    date_obs = meta.get('date_obs') or ''
    inst_bit = '/'.join(p for p in (inst, detector) if p)
    detail = ' '.join(p for p in (inst_bit, filt) if p)
    extra = ' · '.join(p for p in (detail, date_obs) if p)
    if extra:
        parts.append(extra)
    return ' — '.join(parts)


def _rotation_matrix_ccw(angle_deg: float):
    import numpy as np

    th = math.radians(float(angle_deg))
    c, s = math.cos(th), math.sin(th)
    return np.array([[c, -s], [s, c]], dtype=float)


def north_up_east_left_params(cd: list[list[float]] | None) -> tuple[float, bool]:
    """Return ``(ccw_deg, flip_x)`` to put North at +y and East at -x (East left)."""
    import numpy as np

    if not cd:
        return 0.0, False
    matrix = np.asarray(cd, dtype=float)
    if matrix.shape != (2, 2):
        return 0.0, False
    try:
        inv = np.linalg.inv(matrix)
    except np.linalg.LinAlgError:
        return 0.0, False
    north = inv @ np.array([0.0, 1.0], dtype=float)
    north_ang = math.degrees(math.atan2(float(north[1]), float(north[0])))
    delta = 90.0 - north_ang
    east = _rotation_matrix_ccw(delta) @ (inv @ np.array([1.0, 0.0], dtype=float))
    return float(delta), bool(float(east[0]) > 0.0)


def apply_north_up_east_left(
    data,
    wcs: dict[str, Any] | None,
) -> tuple[Any, dict[str, Any] | None]:
    """Rotate/flip a FITS-ordered image so North is up and East is left.

    ``data`` is indexed ``[y, x]`` with ``y=0`` at the FITS bottom. The returned
    WCS is updated for the same pixel convention so browser overlays stay aligned.
    """
    import numpy as np
    from PIL import Image

    if wcs is None or not wcs.get('cd') or not wcs.get('crpix'):
        return data, wcs
    arr = np.asarray(data)
    if arr.ndim != 2:
        return data, wcs
    delta, flip_x = north_up_east_left_params(wcs.get('cd'))
    do_rotate = abs(delta) > 0.05
    if not do_rotate and not flip_x:
        out = dict(wcs)
        out['orientation'] = 'north_up_east_left'
        return arr, out

    old_ny, old_nx = int(arr.shape[0]), int(arr.shape[1])
    # PIL y increases downward; flip into a y-up canvas, rotate in FITS CCW
    # (negate angle for PIL), optional East-left mirror, then flip back.
    img = Image.fromarray(arr)
    img = img.transpose(getattr(Image, 'FLIP_TOP_BOTTOM', 1))
    if do_rotate:
        img = img.rotate(
            -delta,
            expand=True,
            resample=getattr(Image, 'BILINEAR', 2),
            fillcolor=0,
        )
    if flip_x:
        img = img.transpose(getattr(Image, 'FLIP_LEFT_RIGHT', 0))
    img = img.transpose(getattr(Image, 'FLIP_TOP_BOTTOM', 1))
    out_arr = np.asarray(img)
    new_ny, new_nx = int(out_arr.shape[0]), int(out_arr.shape[1])

    cd = np.asarray(wcs['cd'], dtype=float)
    crpix = np.asarray(wcs['crpix'], dtype=float)
    old_center = np.array([(old_nx + 1.0) / 2.0, (old_ny + 1.0) / 2.0], dtype=float)
    new_center = np.array([(new_nx + 1.0) / 2.0, (new_ny + 1.0) / 2.0], dtype=float)
    # offset_new = M @ offset_old for the FITS (x-right, y-up) content transform.
    M = _rotation_matrix_ccw(delta) if do_rotate else np.eye(2)
    if flip_x:
        M = np.array([[-1.0, 0.0], [0.0, 1.0]], dtype=float) @ M
    # world = CD @ (p_old - crpix) and p_new - c_new = M @ (p_old - c_old)
    # => CD_new = CD @ inv(M)
    try:
        cd_new = cd @ np.linalg.inv(M)
    except np.linalg.LinAlgError:
        return data, wcs
    crpix_new = new_center + M @ (crpix - old_center)
    out_wcs = dict(wcs)
    out_wcs['cd'] = cd_new.tolist()
    out_wcs['crpix'] = [float(crpix_new[0]), float(crpix_new[1])]
    out_wcs['nx'] = new_nx
    out_wcs['ny'] = new_ny
    out_wcs['orientation'] = 'north_up_east_left'
    out_wcs['rotation_deg'] = float(delta)
    out_wcs['flip_x'] = bool(flip_x)
    return out_arr, out_wcs
