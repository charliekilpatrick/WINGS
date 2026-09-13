"""Look up a host-galaxy distance from the local GLADE+ cache, then VizieR."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import gladeplus_dir, status_dir

_GLADE_PLUS = 'VII/291'
_SEARCH_RADIUS_ARCMIN = 2.0
_GLADE_COLUMNS = (
    'PGC',
    'GWGC',
    'HyperLEDA',
    'RAJ2000',
    'DEJ2000',
    'dL',
    'e_dL',
    'zhelio',
)


def distance_cache_path(base_dir: Path) -> Path:
    return status_dir(base_dir) / 'host_distance.json'


def _norm_name(name: str | None) -> str:
    return ''.join(ch for ch in str(name or '').upper() if ch.isalnum())


def format_distance(record: dict[str, Any] | None) -> str | None:
    if not record or record.get('distance_mpc') is None:
        return None
    dist = float(record['distance_mpc'])
    err = record.get('distance_err_mpc')
    if err not in (None, ''):
        return f'{dist:.1f} ± {float(err):.1f} Mpc (GLADE+)'
    return f'{dist:.1f} Mpc (GLADE+)'


def _masked_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if hasattr(value, 'mask') and bool(value.mask):
            return None
    except Exception:
        pass
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _row_name(row: Any) -> str:
    for key in ('GWGC', 'HyperLEDA', 'Name', 'name'):
        if hasattr(row, 'colnames') and key in row.colnames:
            text = str(row[key]).strip()
        elif isinstance(row, dict) and key in row:
            text = str(row[key] or '').strip()
        else:
            continue
        if text and text not in {'-', '--', 'None', 'nan'}:
            return text
    return ''


def _from_glade(row: Any) -> dict[str, Any]:
    get = row.__getitem__ if not isinstance(row, dict) else row.get
    colnames = getattr(row, 'colnames', None) or (row.keys() if isinstance(row, dict) else [])
    return {
        'catalog': 'GLADE+',
        'resolved_name': _row_name(row) or None,
        'distance_mpc': _masked_float(get('dL')) if 'dL' in colnames else None,
        'distance_err_mpc': _masked_float(get('e_dL')) if 'e_dL' in colnames else None,
        'redshift': _masked_float(get('zhelio')) if 'zhelio' in colnames else None,
        'pgc': int(get('PGC')) if 'PGC' in colnames and _masked_float(get('PGC')) is not None else None,
    }


def discover_gladeplus_table(root: Path | None = None) -> Path | None:
    directory = Path(root) if root is not None else gladeplus_dir()
    if not directory.is_dir():
        return None
    for name in (
        'gladeplus.fits',
        'gladeplus_lite.fits',
        'gladep.fits',
        'gladeplus.ecsv',
        'gladep.dat',
    ):
        path = directory / name
        if path.is_file() and path.stat().st_size > 0:
            return path
    fits = sorted(directory.glob('*.fits'))
    return fits[0] if fits else None


def _load_glade_table(path: Path):
    from astropy.table import Table

    if path.suffix.lower() == '.dat':
        return Table.read(
            path,
            format='ascii.fixed_width_no_header',
            names=('GLADE+', 'PGC', 'GWGC', 'HyperLEDA', 'RAJ2000', 'DEJ2000', 'dL', 'e_dL', 'zhelio'),
        )
    return Table.read(path)


def _lookup_local(host: str | None, ra: float, dec: float) -> dict[str, Any] | None:
    path = discover_gladeplus_table()
    if path is None:
        return None
    try:
        table = _load_glade_table(path)
    except Exception:
        return None
    ra_col = next((c for c in ('RAJ2000', 'RAdeg', 'ra', '_RAJ2000') if c in table.colnames), None)
    dec_col = next((c for c in ('DEJ2000', 'DEdeg', 'dec', '_DEJ2000') if c in table.colnames), None)
    if ra_col is None or dec_col is None:
        return None
    import numpy as np

    ras = np.asarray(table[ra_col], dtype=float)
    decs = np.asarray(table[dec_col], dtype=float)
    dra = (ras - float(ra)) * np.cos(np.radians(float(dec)))
    ddec = decs - float(dec)
    sep2 = dra * dra + ddec * ddec
    radius_deg = _SEARCH_RADIUS_ARCMIN / 60.0
    nearby = np.where(sep2 <= radius_deg * radius_deg)[0]
    if nearby.size == 0:
        return None
    want = _norm_name(host)
    if want:
        for idx in nearby:
            if _norm_name(_row_name(table[int(idx)])) == want:
                return _from_glade(table[int(idx)])
    best = int(nearby[np.argmin(sep2[nearby])])
    return _from_glade(table[best])


def _query_vizier_glade(ra: float, dec: float):
    from astroquery.vizier import Vizier
    from astropy.coordinates import SkyCoord
    import astropy.units as u

    vizier = Vizier(columns=['**'], row_limit=20)
    vizier.TIMEOUT = 20
    tables = vizier.query_region(
        SkyCoord(ra=ra, dec=dec, unit='deg'),
        radius=_SEARCH_RADIUS_ARCMIN * u.arcmin,
        catalog=_GLADE_PLUS,
    )
    if not tables:
        return None
    return tables[0]


def _pick_row(table, host: str | None):
    if table is None or len(table) == 0:
        return None
    want = _norm_name(host)
    if want:
        for row in table:
            if _norm_name(_row_name(row)) == want:
                return row
    if '_r' in table.colnames:
        return min(table, key=lambda row: float(row['_r']))
    return table[0]


def _lookup_remote(host: str | None, ra: float, dec: float) -> dict[str, Any] | None:
    try:
        glade = _pick_row(_query_vizier_glade(ra, dec), host)
        if glade is None:
            return None
        record = _from_glade(glade)
        if record.get('distance_mpc'):
            return record
    except Exception:
        return None
    return None


def cache_gladeplus_catalog(*, max_dl_mpc: float = 300.0, force: bool = False) -> Path | None:
    """
    Cache a nearby-galaxy GLADE+ table under ``/data/ckilpatrick/catalogs/GLADE+``.

    The CDS ascii dump is 13 GB. This keeps the columns the site needs for
    galaxies with a luminosity distance, which is what the campaign pages use.
    """
    out_dir = gladeplus_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / 'gladeplus_lite.fits'
    if dest.is_file() and dest.stat().st_size > 0 and not force:
        return dest
    try:
        from astroquery.vizier import Vizier
    except Exception:
        return dest if dest.is_file() else None

    vizier = Vizier(
        columns=list(_GLADE_COLUMNS),
        column_filters={'dL': f'<{max_dl_mpc}'},
        row_limit=-1,
    )
    vizier.TIMEOUT = 300
    try:
        tables = vizier.get_catalogs(_GLADE_PLUS)
    except Exception:
        return dest if dest.is_file() else None
    if not tables:
        return dest if dest.is_file() else None
    table = tables[0]
    table.write(dest, overwrite=True)
    meta = {
        'source': _GLADE_PLUS,
        'n': int(len(table)),
        'max_dl_mpc': max_dl_mpc,
        'path': str(dest),
    }
    (out_dir / 'gladeplus_lite.json').write_text(json.dumps(meta, indent=2))
    return dest


def lookup_host_distance(
    *,
    host: str | None,
    ra: float,
    dec: float,
    base_dir: Path,
    force: bool = False,
) -> dict[str, Any] | None:
    """
    Return a cached or freshly queried GLADE+ luminosity distance.

    Preference: local GLADE+ table, then VizieR ``VII/291``. Results are also
    stored per target under ``.pipelinesite``.
    """
    cache_path = distance_cache_path(base_dir)
    key = {
        'host': host or '',
        'ra': round(float(ra), 5),
        'dec': round(float(dec), 5),
    }
    cached = _read_cache(cache_path) if cache_path.is_file() else None
    if cached and not force and cached.get('key') == key and cached.get('distance_mpc') is not None:
        return cached

    record = _lookup_local(host, float(ra), float(dec))
    if record is None or record.get('distance_mpc') is None:
        record = _lookup_remote(host, float(ra), float(dec))
    if record is None or record.get('distance_mpc') is None:
        return cached if cached and cached.get('distance_mpc') is not None else None

    payload = dict(record)
    payload['key'] = key
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2))
    return payload


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
