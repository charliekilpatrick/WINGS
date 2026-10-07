"""Look up a host-galaxy distance from NED, then GLADE+ as fallback."""

from __future__ import annotations

import fcntl
import json
import math
import os
import statistics
import tempfile
import threading
import warnings
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import Request, urlopen

from .config import gladeplus_dir, output_root, status_dir

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
_NED_DISTANCE_URL = (
    'https://ned.ipac.caltech.edu/NED::API/DistancesOfObject?TARGET={target}&MAXREC=5000'
)
_NED_USER_AGENT = 'WINGS-pipelinesite/1.0'
_METHOD_LADDER = (
    ('Cepheids', ('cepheids', 'cepheid')),
    ('TRGB', ('trgb', 'tipoftheredgiant')),
    ('SN Ia', ('snia', 'sneia')),
    ('Tully-Fisher', ('tullyfisher', 'tullyest', 'tully')),
)


def distance_cache_path(base_dir: Path) -> Path:
    return status_dir(base_dir) / 'host_distance.json'


def shared_distance_cache_path() -> Path:
    return output_root() / '.pipelinesite' / 'host_distances.json'


_SHARED_LOCK = threading.Lock()
_WARMER_LOCK = threading.Lock()
_WARMER_KEYS: set[str] = set()


def _norm_name(name: str | None) -> str:
    return ''.join(ch for ch in str(name or '').upper() if ch.isalnum())


def _compact(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())


def format_distance(record: dict[str, Any] | None) -> str | None:
    if not record or record.get('distance_mpc') is None:
        return None
    dist = float(record['distance_mpc'])
    err = record.get('distance_err_mpc')
    catalog = str(record.get('catalog') or '').strip()
    method = str(record.get('method') or '').strip()
    if catalog == 'NED' and method:
        label = f'NED {method}'
    else:
        label = catalog or 'NED'
    if err not in (None, '') and round(float(err), 1) >= 0.1:
        return f'{dist:.1f} ± {float(err):.1f} Mpc ({label})'
    return f'{dist:.1f} Mpc ({label})'


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


def _mpc_from_modulus(dist_mod: float, dist_mod_err: float | None) -> tuple[float, float | None]:
    distance = 10 ** ((float(dist_mod) - 25.0) / 5.0)
    error = None
    if dist_mod_err is not None:
        error = distance * math.log(10) / 5.0 * abs(float(dist_mod_err))
    return distance, error


def classify_ned_method(method: str | None) -> tuple[int, str]:
    compact = _compact(method)
    for rank, (label, tokens) in enumerate(_METHOD_LADDER):
        if any(token in compact for token in tokens):
            return rank, label
    return len(_METHOD_LADDER), (str(method or '').strip() or 'other')


def select_ned_distance(rows: list[dict[str, Any]], *, host: str | None = None) -> dict[str, Any] | None:
    ranked: dict[int, list[dict[str, Any]]] = {}
    for raw in rows:
        distance = _masked_float(raw.get('distance_mpc'))
        dist_mod = _masked_float(raw.get('dist_mod'))
        if distance is None and dist_mod is not None:
            distance, error = _mpc_from_modulus(dist_mod, _masked_float(raw.get('dist_mod_err')))
        else:
            error = _masked_float(raw.get('distance_err_mpc'))
            if error is None and distance is not None and dist_mod is not None:
                _, error = _mpc_from_modulus(dist_mod, _masked_float(raw.get('dist_mod_err')))
        if distance is None or distance <= 0:
            continue
        rank, label = classify_ned_method(raw.get('method'))
        ranked.setdefault(rank, []).append(
            {
                'distance_mpc': distance,
                'distance_err_mpc': error,
                'method': label,
                'raw_method': raw.get('method'),
                'refcode': raw.get('refcode'),
                'notes': raw.get('notes'),
            }
        )
    if not ranked:
        return None
    chosen = ranked[min(ranked)]
    distances = [row['distance_mpc'] for row in chosen]
    median = statistics.median(distances)
    formal = [row['distance_err_mpc'] for row in chosen if row.get('distance_err_mpc')]
    if len(distances) >= 2:
        mad = statistics.median([abs(value - median) for value in distances])
        scatter = 1.4826 * mad
        if scatter > 0:
            error = scatter / math.sqrt(len(distances))
        elif formal:
            error = statistics.median(formal)
        else:
            error = None
    else:
        error = chosen[0].get('distance_err_mpc')
    closest = min(chosen, key=lambda row: abs(row['distance_mpc'] - median))
    return {
        'catalog': 'NED',
        'method': chosen[0]['method'],
        'resolved_name': host,
        'distance_mpc': float(median),
        'distance_err_mpc': None if error is None else float(error),
        'n_measurements': len(chosen),
        'refcode': closest.get('refcode'),
        'notes': closest.get('notes'),
    }


def query_ned_distances(host: str | None, *, timeout: float = 45.0) -> list[dict[str, Any]]:
    name = str(host or '').strip()
    if not name:
        return []
    url = _NED_DISTANCE_URL.format(target=quote(name))
    request = Request(
        url,
        headers={
            'User-Agent': _NED_USER_AGENT,
            'Accept': 'application/x-votable+xml, application/xml, text/xml',
        },
    )
    with urlopen(request, timeout=timeout) as resp:
        raw = resp.read()
    from astropy.io.votable import parse
    from io import BytesIO

    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        table = parse(BytesIO(raw), verify='warn').get_first_table().to_table()
    rows = []
    for rec in table:
        rows.append(
            {
                'method': str(rec.get('method') or '').strip(),
                'distance_mpc': _masked_float(rec.get('distance')),
                'dist_mod': _masked_float(rec.get('dist_mod')),
                'dist_mod_err': _masked_float(rec.get('dist_mod_err')),
                'distance_err_mpc': None,
                'refcode': str(rec.get('refcode') or '').strip() or None,
                'notes': str(rec.get('notes') or '').strip() or None,
            }
        )
    return rows


def _lookup_ned(
    host: str | None,
    query_ned: Callable[[str | None], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    fetcher = query_ned or query_ned_distances
    try:
        rows = fetcher(host)
    except Exception:
        return None
    return select_ned_distance(rows, host=host)


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


def _cache_is_ned(cached: dict[str, Any] | None, host: str | None = None) -> bool:
    if not cached or cached.get('catalog') != 'NED' or cached.get('distance_mpc') is None:
        return False
    if host and cached.get('key', {}).get('host'):
        return _norm_name(cached['key']['host']) == _norm_name(host)
    return True


def _usable_distance(cached: dict[str, Any] | None) -> bool:
    return bool(cached and cached.get('distance_mpc') is not None)


def _load_shared_cache() -> dict[str, Any]:
    path = shared_distance_cache_path()
    data = _read_cache(path) if path.is_file() else None
    if isinstance(data, dict) and isinstance(data.get('hosts'), dict):
        return data['hosts']
    if isinstance(data, dict):
        return {key: value for key, value in data.items() if isinstance(value, dict)}
    return {}


def _write_shared_cache(hosts: dict[str, Any]) -> None:
    path = shared_distance_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix='host_distances.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps({'hosts': hosts}, indent=2) + '\n')
        Path(tmp_name).replace(path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def _shared_file_lock():
    path = shared_distance_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + '.lock')
    handle = lock_path.open('a+')
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def remember_host_distance(host: str | None, record: dict[str, Any] | None) -> None:
    key = _norm_name(host)
    if not key or not _usable_distance(record):
        return
    lock = _shared_file_lock()
    try:
        with _SHARED_LOCK:
            hosts = _load_shared_cache()
            current = hosts.get(key)
            if _cache_is_ned(current, host) and not _cache_is_ned(record, host):
                return
            hosts[key] = dict(record)
            _write_shared_cache(hosts)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()


def shared_host_distance(host: str | None) -> dict[str, Any] | None:
    key = _norm_name(host)
    if not key:
        return None
    lock = _shared_file_lock()
    try:
        with _SHARED_LOCK:
            record = _load_shared_cache().get(key)
    finally:
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        lock.close()
    return record if isinstance(record, dict) else None


def lookup_host_distance(
    *,
    host: str | None,
    ra: float,
    dec: float,
    base_dir: Path,
    force: bool = False,
    query_ned: Callable[[str | None], list[dict[str, Any]]] | None = None,
    remote: bool = True,
) -> dict[str, Any] | None:
    """
    Return a NED redshift-independent distance, preferring Cepheids, then TRGB,
    SN Ia, Tully-Fisher, and any other NED method. GLADE+ is used only if NED
    has no usable distance. Results are cached by host name so prime and
    parallel fields of the same galaxy share one distance.
    """
    cache_path = distance_cache_path(base_dir)
    key = {
        'host': host or '',
        'ra': round(float(ra), 5),
        'dec': round(float(dec), 5),
    }
    cached = _read_cache(cache_path) if cache_path.is_file() else None
    shared = shared_host_distance(host)
    if not force and _cache_is_ned(cached, host):
        remember_host_distance(host, cached)
        return cached
    if not force and _cache_is_ned(shared, host):
        return shared
    if not remote:
        if _usable_distance(shared):
            return shared
        if _usable_distance(cached):
            return cached
        return None

    record = _lookup_ned(host, query_ned=query_ned)
    if record is None or record.get('distance_mpc') is None:
        record = _lookup_local(host, float(ra), float(dec))
        if record is None or record.get('distance_mpc') is None:
            record = _lookup_remote(host, float(ra), float(dec))
    if record is None or record.get('distance_mpc') is None:
        if _usable_distance(shared):
            return shared
        if _usable_distance(cached):
            return cached
        return None

    payload = dict(record)
    payload['key'] = key
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2))
    remember_host_distance(host, payload)
    return payload


def warm_host_distances(rows: list[dict[str, Any]]) -> None:
    """Fetch missing host distances in the background. Safe to call on every page load."""
    pending: list[dict[str, Any]] = []
    with _WARMER_LOCK:
        for row in rows:
            host = str(row.get('host') or '').strip()
            key = _norm_name(host)
            if not key or key in _WARMER_KEYS:
                continue
            if _cache_is_ned(shared_host_distance(host), host):
                continue
            _WARMER_KEYS.add(key)
            pending.append(row)
    if not pending:
        return

    def _run() -> None:
        try:
            for row in pending:
                try:
                    lookup_host_distance(
                        host=row.get('host'),
                        ra=float(row['ra']),
                        dec=float(row['dec']),
                        base_dir=Path(row['base_dir']),
                        remote=True,
                    )
                except Exception:
                    continue
        finally:
            with _WARMER_LOCK:
                for row in pending:
                    _WARMER_KEYS.discard(_norm_name(row.get('host')))

    threading.Thread(target=_run, name='host-distance-warm', daemon=True).start()


def _read_cache(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
