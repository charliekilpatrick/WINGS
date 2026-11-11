"""Resolve supernova host galaxies from multiple sources.

TNS host names are useful when present, but they are incomplete. Fall back to
literature overrides, NED near-position cone searches, and GLADE+ when TNS is
blank or rates-limited. Example: SN 2017hta is hostless on TNS but Purdue
Bright Supernovae and a NED cone both identify UGCA 81.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_USER_AGENT = 'WINGS-pipelinesite/1.0 (+https://github.com/charliekilpatrick/WINGS)'
_TNS_SEARCH = 'https://www.wis-tns.org/search'
_NED_NEAR = (
    'https://ned.ipac.caltech.edu/cgi-bin/objsearch'
    '?search_type=Near+Position+Search'
    '&in_csys=Equatorial&in_equinox=J2000.0'
    '&lon={ra}d&lat={dec}d&radius={radius}'
    '&hconst=73&omegam=0.27&omegav=0.73&corr_z=1'
    '&z_constraint=Unconstrained&ot_include=Any&nmp_op=any'
    '&out_csys=Equatorial&out_equinox=J2000.0'
    '&obj_sort=Distance+to+search+center&of=pre_text'
    '&zv_breaker=30000.0&list_limit={limit}&img_stamp=NO'
)
_DEFAULT_CONE_ARCMIN = 5.0

# Manual / literature hosts when surveys leave the field blank.
# Keys are name_key() forms of the SN designation (e.g. SN2017HTA).
LITERATURE_HOSTS: dict[str, dict[str, str]] = {
    'SN2017HTA': {
        'host': 'UGCA 81',
        'source': 'purdue-bright-sne',
        'reference': 'https://www.physics.purdue.edu/brightsupernovae//sn2017/index.html#2017hta',
    },
}

_GALAXY_NAME = re.compile(
    r'\b('
    r'UGCA|UGC|NGC|IC|ESO|PGC|Messier|KDG|DDO|Holmberg|WLM|GR'
    r')\s*[-.]?\s*([0-9]+[A-Za-z]?|[IVX]+)\b',
    re.IGNORECASE,
)
_SN_NAME = re.compile(r'^(?:SN|AT)\s*[0-9]{4}[A-Za-z]+$', re.IGNORECASE)
_TAG = re.compile(r'<[^>]+>')


def name_key(value: str | None) -> str:
    text = ''.join(ch for ch in str(value or '').upper() if ch.isalnum())
    return re.sub(r'([A-Z]+)0+(\d+)', r'\1\2', text)


def sn_query_token(raw: str | None) -> str:
    """Strip SN/AT prefixes for TNS queries (2017hta)."""
    text = str(raw or '').strip()
    text = re.sub(r'^(?:SN|AT)\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', '', text)
    return text.lower()


def pretty_galaxy_name(raw: str | None) -> str:
    text = str(raw or '').strip()
    if not text:
        return ''
    match = _GALAXY_NAME.search(text.replace('_', ' '))
    if not match:
        return re.sub(r'\s+', ' ', text)
    catalog = match.group(1).upper()
    if catalog == 'MESSIER':
        catalog = 'M'
    number = match.group(2)
    if number.isdigit():
        number = str(int(number))
    elif re.fullmatch(r'\d+[A-Za-z]', number):
        number = str(int(number[:-1])) + number[-1].upper()
    else:
        number = number.upper()
    if catalog == 'ESO' and '-' not in number and len(number) >= 4:
        # Keep packed ESO forms readable when already spaced in source text.
        pass
    return f'{catalog} {number}'


def is_galaxy_name(raw: str | None) -> bool:
    text = str(raw or '').strip()
    if not text or _SN_NAME.match(text.replace(' ', '')):
        return False
    lowered = text.lower()
    if any(token in lowered for token in ('anonymous', 'hostless', 'unknown', 'none')):
        return False
    return bool(_GALAXY_NAME.search(text.replace('_', ' '))) or bool(
        re.match(r'^[A-Za-z][A-Za-z0-9 .+\-]+$', text)
    )


def literature_host(raw: str | None) -> dict[str, str] | None:
    key = name_key(raw)
    if not key:
        return None
    # Accept sn2017hta / 2017hta / SN 2017HTA.
    for candidate in (key, name_key(f'SN{sn_query_token(raw)}')):
        hit = LITERATURE_HOSTS.get(candidate)
        if hit:
            return dict(hit)
    return None


class _TnsHostParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.host = ''
        self._capture = False
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        cls = dict(attrs).get('class') or ''
        if tag == 'td' and 'cell-hostname' in cls.split():
            self._capture = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == 'td' and self._capture:
            text = re.sub(r'\s+', ' ', ''.join(self._buf)).strip()
            if text and not self.host:
                self.host = text
            self._capture = False

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buf.append(data)


def query_tns_host(
    sn_name: str | None,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: float = 30.0,
) -> str:
    token = sn_query_token(sn_name)
    if not token:
        return ''
    fetch = opener or urlopen
    url = f'{_TNS_SEARCH}?{urlencode({"name": token})}'
    request = Request(url, headers={'User-Agent': _USER_AGENT, 'Accept': 'text/html'})
    try:
        with fetch(request, timeout=timeout) as resp:
            html = resp.read().decode('utf-8', 'replace')
    except (HTTPError, URLError, TimeoutError, OSError):
        return ''
    parser = _TnsHostParser()
    parser.feed(html)
    host = pretty_galaxy_name(parser.host) if parser.host else ''
    return host if is_galaxy_name(host) else ''


def _strip_html(text: str) -> str:
    return _TAG.sub(' ', text)


def _catalog_rank(host: str) -> int:
    prefix = str(host or '').split()[0].upper()
    return {'NGC': 0, 'IC': 1, 'M': 2, 'UGCA': 3, 'UGC': 4, 'ESO': 5, 'PGC': 6}.get(prefix, 9)


def _sort_galaxy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple:
        host = str(row['host'])
        return (
            float(row['separation_arcmin']) if row.get('separation_arcmin') is not None else 1e9,
            _catalog_rank(host),
            host,
        )

    ranked = sorted(rows, key=sort_key)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in ranked:
        key = name_key(row['host'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)
    return unique


def parse_ned_cone_galaxies(html: str) -> list[dict[str, Any]]:
    """Extract named galaxies and separations (arcmin) from a NED near-position page."""
    rows: list[dict[str, Any]] = []
    for raw_line in _strip_html(html).splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line:
            continue
        type_match = re.search(r'\b(?P<type>G(?:Group|Pair|Clstr)?)\b', line)
        if not type_match or type_match.group('type') != 'G':
            continue
        match = _GALAXY_NAME.search(line)
        if not match:
            continue
        name = pretty_galaxy_name(match.group(0))
        if not is_galaxy_name(name):
            continue
        # After type G: Velocity, Redshift, Mag, Separation(arcmin), ...
        floats = [float(tok) for tok in re.findall(r'\d+\.\d+', line[type_match.end() :])]
        sep = None
        for val in floats:
            if val < 0.05:
                continue
            if val <= 180.0:
                # Keep the last plausible angular separation (z, mag, then sep).
                sep = val
        rows.append({'host': name, 'separation_arcmin': sep, 'source': 'ned-cone'})
    return _sort_galaxy_rows(rows)


def query_ned_cone_host(
    ra: float | None,
    dec: float | None,
    *,
    radius_arcmin: float = _DEFAULT_CONE_ARCMIN,
    opener: Callable[..., Any] | None = None,
    timeout: float = 45.0,
) -> dict[str, Any] | None:
    if ra is None or dec is None:
        return None
    # Prefer structured NED API (clean Separation column) unless a custom opener is set.
    if opener is None:
        try:
            from astropy.coordinates import SkyCoord
            import astropy.units as u
            from astroquery.ipac.ned import Ned

            table = Ned.query_region(
                SkyCoord(ra=float(ra) * u.deg, dec=float(dec) * u.deg),
                radius=float(radius_arcmin) * u.arcmin,
            )
            rows: list[dict[str, Any]] = []
            for rec in table:
                if str(rec['Type']).strip() != 'G':
                    continue
                name = pretty_galaxy_name(str(rec['Object Name']))
                if not is_galaxy_name(name):
                    continue
                try:
                    sep = float(rec['Separation'])
                except Exception:
                    sep = None
                rows.append({'host': name, 'separation_arcmin': sep, 'source': 'ned-cone'})
            ranked = _sort_galaxy_rows(rows)
            if ranked:
                return ranked[0]
        except Exception:
            pass

    fetch = opener or urlopen
    url = _NED_NEAR.format(ra=float(ra), dec=float(dec), radius=float(radius_arcmin), limit=15)
    request = Request(url, headers={'User-Agent': _USER_AGENT})
    try:
        with fetch(request, timeout=timeout) as resp:
            html = resp.read().decode('utf-8', 'replace')
    except (HTTPError, URLError, TimeoutError, OSError):
        return None
    rows = parse_ned_cone_galaxies(html)
    return rows[0] if rows else None


def query_glade_cone_host(
    ra: float | None,
    dec: float | None,
    *,
    radius_arcmin: float = _DEFAULT_CONE_ARCMIN,
) -> dict[str, Any] | None:
    if ra is None or dec is None:
        return None
    try:
        from .host_distance import _from_glade, _query_vizier_glade
    except Exception:
        return None
    try:
        table = _query_vizier_glade(float(ra), float(dec))
    except Exception:
        return None
    if table is None or len(table) == 0:
        return None
    # Vizier GLADE cone is already sorted by distance in host_distance helpers
    # when using a positional query; take the first named galaxy.
    for row in table:
        record = _from_glade(row)
        name = pretty_galaxy_name(record.get('resolved_name') or '')
        if not name and record.get('pgc'):
            name = f"PGC {int(record['pgc'])}"
        if is_galaxy_name(name):
            return {'host': name, 'source': 'glade-cone', 'separation_arcmin': None}
    return None


def resolve_sn_host(
    sn_name: str | None,
    *,
    ra: float | None = None,
    dec: float | None = None,
    radius_arcmin: float = _DEFAULT_CONE_ARCMIN,
    query_tns: Callable[[str | None], str] | None = None,
    query_ned: Callable[..., dict[str, Any] | None] | None = None,
    query_glade: Callable[..., dict[str, Any] | None] | None = None,
    use_tns: bool = True,
    use_ned: bool = True,
    use_glade: bool = True,
) -> dict[str, Any] | None:
    """Return ``{host, source, ...}`` or None if no galaxy host is found."""
    lit = literature_host(sn_name)
    if lit:
        return {
            'host': pretty_galaxy_name(lit['host']),
            'source': lit.get('source') or 'literature',
            'reference': lit.get('reference'),
        }

    if use_tns:
        fetcher = query_tns or query_tns_host
        try:
            host = fetcher(sn_name)
        except Exception:
            host = ''
        if is_galaxy_name(host):
            return {'host': pretty_galaxy_name(host), 'source': 'wis-tns'}

    if use_ned:
        ned = query_ned or query_ned_cone_host
        try:
            hit = ned(ra, dec, radius_arcmin=radius_arcmin)
        except TypeError:
            hit = ned(ra, dec)
        except Exception:
            hit = None
        if hit and is_galaxy_name(hit.get('host')):
            return {
                'host': pretty_galaxy_name(hit['host']),
                'source': hit.get('source') or 'ned-cone',
                'separation_arcmin': hit.get('separation_arcmin'),
            }

    if use_glade:
        glade = query_glade or query_glade_cone_host
        try:
            hit = glade(ra, dec, radius_arcmin=radius_arcmin)
        except TypeError:
            hit = glade(ra, dec)
        except Exception:
            hit = None
        if hit and is_galaxy_name(hit.get('host')):
            return {
                'host': pretty_galaxy_name(hit['host']),
                'source': hit.get('source') or 'glade-cone',
                'separation_arcmin': hit.get('separation_arcmin'),
            }
    return None


def apply_hosts_to_targets(
    targets: list[dict[str, Any]],
    *,
    only_missing: bool = True,
    resolver: Callable[..., dict[str, Any] | None] | None = None,
) -> dict[str, str]:
    """Fill ``host`` on SN-named targets. Returns slug→host map of updates."""
    resolve = resolver or resolve_sn_host
    updates: dict[str, str] = {}
    for row in targets:
        slug = str(row.get('name') or '')
        current = str(row.get('host') or '').strip()
        if only_missing and is_galaxy_name(current):
            continue
        label = str(row.get('display_name') or slug)
        if not re.search(r'\b(?:SN|AT)\b', label, re.IGNORECASE) and not re.match(
            r'^(?:sn|at)\d{4}', slug, re.IGNORECASE
        ):
            continue
        hit = resolve(
            label or slug,
            ra=row.get('ra'),
            dec=row.get('dec'),
        )
        if not hit:
            continue
        host = pretty_galaxy_name(hit['host'])
        row['host'] = host
        updates[slug] = host
    return updates
