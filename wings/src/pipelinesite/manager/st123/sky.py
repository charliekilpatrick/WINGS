"""WCS helpers for the reference-image viewer."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

def _header_get(header, *keys):
    for key in keys:
        if key in header and header[key] not in (None, '', 'N/A'):
            return header[key]
    return None


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


def ab_zeropoint(photflam: float | None, photplam: float | None) -> float | None:
    if not photflam or not photplam or photflam <= 0 or photplam <= 0:
        return None
    return -2.5 * math.log10(float(photflam)) - 5.0 * math.log10(float(photplam)) - 2.408


def read_image_header(path: Path) -> dict[str, Any]:
    """Read WCS and identifying cards from a FITS science image."""
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
    from .st123api import display_filter, filter_name
    meta['filter'] = display_filter(filter_name(path))
    try:
        from astropy.io import fits
        from astropy.wcs import FITSFixedWarning
        import warnings
    except Exception:
        return meta

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', FITSFixedWarning)
            with fits.open(path, memmap=True) as hdul:
                header = hdul[0].header
                wcs_header = None
                data = None
                inst = detector = None
                date_obs = None
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
                    arr = getattr(hdu, 'data', None)
                    if data is None and arr is not None and getattr(arr, 'ndim', 0) >= 2:
                        data = arr
                header = wcs_header or header
    except Exception:
        return meta

    meta['instrument'] = None if inst is None else str(inst).strip()
    meta['detector'] = None if detector is None else str(detector).strip()
    meta['date_obs'] = None if date_obs is None else str(date_obs)
    try:
        meta['exptime'] = None if exptime is None else float(exptime)
    except (TypeError, ValueError):
        meta['exptime'] = None
    if data is not None:
        meta['ny'], meta['nx'] = int(data.shape[-2]), int(data.shape[-1])
    else:
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
    return meta


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
