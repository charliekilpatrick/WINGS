"""Project the field Gaia catalog onto the reference image."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterable

from .sky import pix_to_world, world_to_pix


_MATCH_ARCSEC = 0.4


def _haversine_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = (math.radians(v) for v in (ra1, dec1, ra2, dec2))
    arg = (
        math.sin((d2 - d1) / 2.0) ** 2
        + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2
    )
    return 2.0 * math.asin(min(1.0, math.sqrt(max(0.0, arg)))) * 206264.80624709636


def discover_gaia_table(base_dir: Path) -> Path | None:
    gaia_dir = Path(base_dir) / 'reduction' / 'gaia'
    for name in ('gaiadr3.ecsv', 'gaiadr2.ecsv', 'gaia.ecsv'):
        path = gaia_dir / name
        if path.is_file():
            return path
    radec = gaia_dir / 'gaiadr3_radec.txt'
    if radec.is_file():
        return radec
    return None


def discover_alignment_refcat(base_dir: Path) -> Path | None:
    root = Path(base_dir) / 'reduction'
    for rel in ('jhat_hst/l3_ref', 'jhat/l3_ref'):
        l3 = root / rel
        if not l3.is_dir():
            continue
        phot = sorted(l3.glob('*.phot.txt'))
        if phot:
            return phot[0]
    return None


def _read_ra_dec_table(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == '.ecsv':
        from astropy.table import Table

        table = Table.read(path)
        rows = []
        for row in table:
            try:
                ra = float(row['ra'])
                dec = float(row['dec'])
            except (KeyError, TypeError, ValueError):
                continue
            rec: dict[str, Any] = {'ra': ra, 'dec': dec}
            for src, dest in (
                ('source_id', 'source_id'),
                ('phot_g_mean_mag', 'gmag'),
                ('BPmag', 'bpmag'),
                ('RPmag', 'rpmag'),
            ):
                if src in table.colnames:
                    value = row[src]
                    try:
                        if hasattr(value, 'mask') and bool(value.mask):
                            rec[dest] = None
                            continue
                    except Exception:
                        pass
                    try:
                        rec[dest] = float(value) if src != 'source_id' else int(value)
                    except (TypeError, ValueError):
                        rec[dest] = str(value).strip() or None
            rows.append(rec)
        return rows

    rows = []
    for line in path.read_text(errors='replace').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            rows.append({'ra': float(parts[0]), 'dec': float(parts[1])})
        except ValueError:
            continue
    return rows


def _match_residual(
    ra: float,
    dec: float,
    catalog: Iterable[tuple[float, float]],
) -> float | None:
    best = None
    for cra, cdec in catalog:
        sep = _haversine_arcsec(ra, dec, cra, cdec)
        if best is None or sep < best:
            best = sep
    return best


def load_gaia_overlay(
    base_dir: Path,
    wcs: dict[str, Any] | None,
    *,
    match_coords: Iterable[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    """
    Return Gaia stars that land on the reference image.

    Stars that match the L3 / detection catalog within 0.4 arcsec are marked
    as the absolute-alignment calibrators.
    """
    empty = {'stars': [], 'n_on_image': 0, 'n_used': 0, 'catalog': None, 'match_catalog': None}
    if not wcs:
        return empty
    gaia_path = discover_gaia_table(base_dir)
    if gaia_path is None:
        return empty
    try:
        rows = _read_ra_dec_table(gaia_path)
    except Exception:
        return empty

    matches = list(match_coords or [])
    match_path = None
    if not matches:
        match_path = discover_alignment_refcat(base_dir)
        if match_path is not None:
            try:
                matches = [
                    (row['ra'], row['dec'])
                    for row in _read_ra_dec_table(match_path)
                    if 'ra' in row and 'dec' in row
                ]
            except Exception:
                matches = []

    nx = float(wcs.get('nx') or 0)
    ny = float(wcs.get('ny') or 0)
    stars = []
    for row in rows:
        pix = world_to_pix(row['ra'], row['dec'], wcs)
        if pix is None:
            continue
        x, y = pix
        if nx and ny and not (1.0 <= x <= nx and 1.0 <= y <= ny):
            continue
        residual = _match_residual(row['ra'], row['dec'], matches) if matches else None
        used = residual is not None and residual <= _MATCH_ARCSEC
        sky = pix_to_world(x, y, wcs)
        stars.append(
            {
                'ra': row['ra'],
                'dec': row['dec'],
                'x': x,
                'y': y,
                'gmag': row.get('gmag'),
                'source_id': None if row.get('source_id') is None else str(row.get('source_id')),
                'used': used,
                'residual_arcsec': residual,
                'predicted_ra': None if sky is None else sky[0],
                'predicted_dec': None if sky is None else sky[1],
            }
        )
    n_used = sum(1 for star in stars if star['used'])
    return {
        'stars': stars,
        'n_on_image': len(stars),
        'n_used': n_used,
        'rms_mas': _rms_mas(stars),
        'catalog': str(gaia_path),
        'match_catalog': str(match_path) if match_path else None,
    }


def _rms_mas(stars: Iterable[dict[str, Any]]) -> float | None:
    values = [
        float(star['residual_arcsec'])
        for star in stars
        if star.get('used') and star.get('residual_arcsec') is not None
    ]
    if not values:
        return None
    mean_sq = sum(value * value for value in values) / len(values)
    return math.sqrt(mean_sq) * 1000.0


def format_wcs_quality(gaia: dict[str, Any] | None) -> str:
    gaia = gaia or {}
    n_on = int(gaia.get('n_on_image') or 0)
    n_used = int(gaia.get('n_used') or 0)
    if not n_on:
        return 'No Gaia alignment stars on this image'
    text = f'{n_used} / {n_on} Gaia stars used for absolute WCS'
    rms = gaia.get('rms_mas')
    if rms is not None:
        text += f' (RMS = {rms:.0f} mas)' if rms >= 10 else f' (RMS = {rms:.1f} mas)'
    return text
