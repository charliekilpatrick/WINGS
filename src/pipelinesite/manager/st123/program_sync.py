"""Poll STScI visit status and MAST, then update the campaign target registry."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import URLError
from urllib.request import Request, urlopen

from .config import TargetSpec, campaign_registry_path, data_root, program_id
from .sky import format_dec, format_ra

VISIT_STATUS_URL = 'https://www.stsci.edu/hst-program-info/visits/?program={program}'
_SKIP_TARGET_TOKENS = {'ANY', 'OR', 'AND', 'NONE'}
_OBSERVED_STATUSES = ('archived', 'executed', 'completed')
_NOT_OBSERVED = (
    'implementation',
    'scheduling',
    'scheduled',
    'withdrawn',
    'failed',
    'skipped',
    'held',
)
_INST_MAP = (
    ('WFPC2', 'WFPC2'),
    ('WFC3', 'WFC3'),
    ('ACS', 'ACS'),
)
_USER_AGENT = 'NGP-pipelinesite/1.0 (+https://github.com/)'


def name_key(value: str | None) -> str:
    text = ''.join(ch for ch in str(value or '').upper() if ch.isalnum())
    return re.sub(r'([A-Z]+)0+(\d+)', r'\1\2', text)


def target_slug(value: str | None) -> str:
    return name_key(value).lower()


def pretty_target_name(raw: str) -> str:
    text = re.sub(r'\bANY\b', ' ', str(raw or ''), flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'([A-Za-z]+)0*([0-9]+)', r'\1 \2', text)
    return text or str(raw or '').strip()


def parse_instruments(raw: str | Iterable[str] | None) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, str):
        parts = re.split(r'[\s,/]+', raw.upper())
    else:
        parts = [str(part).upper() for part in raw]
    found: list[str] = []
    blob = ' '.join(parts)
    for token, name in _INST_MAP:
        if token in blob and name not in found:
            found.append(name)
    return tuple(found)


def visit_is_observed(status: str | None) -> bool:
    text = str(status or '').strip().lower()
    if not text:
        return False
    if any(token in text for token in _NOT_OBSERVED):
        return False
    return any(token in text for token in _OBSERVED_STATUSES)


class _VisitTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_table = False
        self._in_body = False
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = dict(attrs)
        if tag == 'table' and attrs_d.get('id') in {'visits2', 'visits'}:
            self._in_table = True
        elif self._in_table and tag == 'tr':
            self._row = []
        elif self._row is not None and tag == 'td':
            self._cell = []
        elif self._cell is not None and tag == 'br':
            self._cell.append('\n')

    def handle_endtag(self, tag: str) -> None:
        if tag == 'table' and self._in_table:
            self._in_table = False
        elif tag == 'td' and self._cell is not None and self._row is not None:
            self._row.append(re.sub(r'[ \t]+', ' ', ''.join(self._cell)).strip())
            self._cell = None
        elif tag == 'tr' and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_visit_table(html: str) -> list[dict[str, Any]]:
    parser = _VisitTableParser()
    parser.feed(html)
    visits: list[dict[str, Any]] = []
    for cells in parser.rows:
        if len(cells) < 3:
            continue
        visit_id = cells[0].strip()
        status = re.sub(r'\s+', ' ', cells[1]).strip()
        raw_targets = [part.strip() for part in re.split(r'[\n,;]+', cells[2]) if part.strip()]
        targets = [
            pretty_target_name(part)
            for part in raw_targets
            if name_key(part) and name_key(part) not in _SKIP_TARGET_TOKENS
        ]
        configs = cells[3] if len(cells) > 3 else ''
        if not visit_id or not targets:
            continue
        visits.append(
            {
                'visit': visit_id,
                'status': status,
                'targets': targets,
                'instruments': parse_instruments(configs),
                'observed': visit_is_observed(status),
            }
        )
    return visits


def fetch_visit_html(program: str, url: str | None = None, timeout: float = 60.0) -> str:
    href = url or VISIT_STATUS_URL.format(program=program)
    request = Request(href, headers={'User-Agent': _USER_AGENT})
    with urlopen(request, timeout=timeout) as resp:
        return resp.read().decode('utf-8', errors='replace')


def query_mast_observations(program: str) -> list[dict[str, Any]]:
    from astroquery.mast import Observations

    table = Observations.query_criteria(
        proposal_id=str(program),
        obs_collection='HST',
        dataproduct_type='image',
    )
    if table is None or len(table) == 0:
        return []
    rows: list[dict[str, Any]] = []
    for rec in table:
        target = str(rec.get('target_name') or '').strip()
        inst = str(rec.get('instrument_name') or '')
        rights = str(rec.get('dataRights') or rec.get('data_rights') or '').upper()
        intent = str(rec.get('intentType') or rec.get('intent_type') or 'SCIENCE').upper()
        if intent and intent != 'SCIENCE':
            continue
        try:
            ra = float(rec['s_ra'])
            dec = float(rec['s_dec'])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append(
            {
                'target_name': target,
                'key': name_key(target),
                'ra': ra,
                'dec': dec,
                'instruments': parse_instruments(inst),
                'obs_id': str(rec.get('obs_id') or ''),
                'public': rights in {'', 'PUBLIC', 'PUBLIC/UNRESTRICTED'},
            }
        )
    return rows


def _mean_sky(rows: list[dict[str, Any]]) -> tuple[float, float] | None:
    if not rows:
        return None
    return (
        sum(float(row['ra']) for row in rows) / len(rows),
        sum(float(row['dec']) for row in rows) / len(rows),
    )


def group_visits(visits: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for visit in visits:
        for target in visit['targets']:
            slug = target_slug(target)
            if not slug:
                continue
            rec = grouped.setdefault(
                slug,
                {
                    'name': slug,
                    'display_name': pretty_target_name(target),
                    'host': pretty_target_name(target),
                    'visits': [],
                    'statuses': [],
                    'instruments': [],
                    'observed': False,
                },
            )
            rec['visits'].append(visit['visit'])
            rec['statuses'].append(visit['status'])
            for inst in visit.get('instruments') or ():
                if inst not in rec['instruments']:
                    rec['instruments'].append(inst)
            rec['observed'] = rec['observed'] or bool(visit['observed'])
    return grouped


def match_mast(target: dict[str, Any], mast_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = {
        name_key(target.get('display_name')),
        name_key(target.get('host')),
        name_key(target.get('name')),
    }
    keys.discard('')
    return [row for row in mast_rows if row.get('key') in keys]


def build_registry_record(
    target: dict[str, Any],
    mast_hits: list[dict[str, Any]],
    *,
    root: Path,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sky = _mean_sky(mast_hits)
    instruments = list(target.get('instruments') or [])
    for row in mast_hits:
        for inst in row.get('instruments') or ():
            if inst not in instruments:
                instruments.append(inst)
    if not instruments:
        instruments = ['ACS', 'WFC3', 'WFPC2']
    ready = bool(target.get('observed') and mast_hits)
    if previous and previous.get('ready'):
        ready = True
        if sky is None:
            try:
                sky = (float(previous['ra']), float(previous['dec']))
            except (KeyError, TypeError, ValueError):
                sky = None
        if previous.get('instruments'):
            for inst in previous['instruments']:
                if inst not in instruments:
                    instruments.append(inst)
    ra, dec = sky if sky is not None else (None, None)
    base = previous.get('base_dir') if previous else None
    record = {
        'name': target['name'],
        'display_name': target['display_name'],
        'host': target['host'],
        'sn_type': '',
        'ra': ra,
        'dec': dec,
        'ra_sex': format_ra(ra) if ra is not None else '',
        'dec_sex': format_dec(dec) if dec is not None else '',
        'radius_arcmin': 5.0,
        'instruments': instruments,
        'telescope': 'hst',
        'base_dir': base or str(root / target['name']),
        'notes': f"GO visits {', '.join(target.get('visits') or [])}",
        'visits': list(target.get('visits') or []),
        'stsci_status': ', '.join(sorted(set(target.get('statuses') or []))),
        'observed': bool(target.get('observed')),
        'mast_products': len(mast_hits),
        'ready': ready,
    }
    return record


def spec_from_record(row: dict[str, Any]) -> TargetSpec | None:
    try:
        ra = float(row['ra'])
        dec = float(row['dec'])
    except (KeyError, TypeError, ValueError):
        return None
    instruments = tuple(row.get('instruments') or ('ACS', 'WFC3', 'WFPC2'))
    return TargetSpec(
        name=str(row['name']),
        display_name=str(row.get('display_name') or row['name']),
        host=str(row.get('host') or row.get('display_name') or row['name']),
        sn_type=str(row.get('sn_type') or ''),
        ra=ra,
        dec=dec,
        ra_sex=str(row.get('ra_sex') or format_ra(ra)),
        dec_sex=str(row.get('dec_sex') or format_dec(dec)),
        radius_arcmin=float(row.get('radius_arcmin') or 5.0),
        instruments=instruments,
        telescope=str(row.get('telescope') or 'hst'),
        base_dir=Path(row.get('base_dir') or (data_root() / row['name'])),
        notes=str(row.get('notes') or ''),
    )


def load_registry(path: Path | None = None) -> dict[str, Any]:
    registry = Path(path) if path is not None else campaign_registry_path()
    if not registry.is_file():
        return {'program_id': program_id(), 'targets': []}
    try:
        data = json.loads(registry.read_text())
    except (OSError, json.JSONDecodeError):
        return {'program_id': program_id(), 'targets': []}
    if not isinstance(data, dict):
        return {'program_id': program_id(), 'targets': []}
    data.setdefault('targets', [])
    return data


def write_registry(payload: dict[str, Any], path: Path | None = None) -> Path:
    registry = Path(path) if path is not None else campaign_registry_path()
    registry.parent.mkdir(parents=True, exist_ok=True)
    tmp = registry.with_suffix(registry.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=False) + '\n')
    tmp.replace(registry)
    return registry


def load_registry_specs(path: Path | None = None) -> list[TargetSpec]:
    data = load_registry(path)
    specs: list[TargetSpec] = []
    for row in data.get('targets') or []:
        if not row.get('ready'):
            continue
        spec = spec_from_record(row)
        if spec is not None:
            specs.append(spec)
    return specs


def sync_program_targets(
    *,
    program: str | None = None,
    registry_path: Path | None = None,
    root: Path | None = None,
    visit_html: str | None = None,
    mast_rows: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
    create_dirs: bool = True,
) -> dict[str, Any]:
    pid = str(program or program_id())
    dest = Path(registry_path) if registry_path is not None else campaign_registry_path()
    hst_root = Path(root) if root is not None else data_root()
    html = visit_html if visit_html is not None else fetch_visit_html(pid)
    visits = parse_visit_table(html)
    grouped = group_visits(visits)
    mast = mast_rows if mast_rows is not None else query_mast_observations(pid)
    previous = {row.get('name'): row for row in load_registry(dest).get('targets') or []}
    records = []
    added = []
    for slug, target in sorted(grouped.items()):
        hits = match_mast(target, mast)
        record = build_registry_record(
            target,
            hits,
            root=hst_root,
            previous=previous.get(slug),
        )
        was_ready = bool((previous.get(slug) or {}).get('ready'))
        if record['ready'] and not was_ready:
            added.append(record['name'])
        records.append(record)
        if record['ready'] and create_dirs and not dry_run:
            Path(record['base_dir']).mkdir(parents=True, exist_ok=True)

    payload = {
        'program_id': pid,
        'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'n_visits': len(visits),
        'n_observed': sum(1 for visit in visits if visit['observed']),
        'n_mast': len(mast),
        'n_ready': sum(1 for row in records if row['ready']),
        'added': added,
        'targets': records,
    }
    if not dry_run:
        write_registry(payload, dest)
        payload['registry'] = str(dest)
    return payload
