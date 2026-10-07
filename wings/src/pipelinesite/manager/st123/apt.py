"""Parse HST Phase II APT files into campaign target records."""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

from .program_sync import lookup_host_name, pretty_target_name
from .sky import format_dec, format_ra

APT_PUBLIC_URL = 'https://www.stsci.edu/hst/phase2-public/{program}.apt'
_ARCHIVAL_INSTRUMENTS = ('ACS', 'WFC3', 'WFPC2')
_EQ_VALUE = re.compile(
    r'(?P<rah>\d+)\s+(?P<ram>\d+)\s+(?P<ras>[\d.]+)\s+'
    r'(?P<dsign>[+-])\s*(?P<ded>\d+)\s+(?P<dem>\d+)\s+(?P<des>[\d.]+)'
)
# HST SIAF: WFC3/UVIS-CENTER (IUVISCTR) and ACS/WFC center (JWFCENTER), arcsec.
_UVIS_CENTER = (0.4314, -3.784)
_ACS_WFC_CENTER = (261.5333, 252.3019)


def output_slug(name: str | None, *, parallel: bool = False) -> str:
    """Directory / target id: keep APT zero-padding; append ``par`` for parallels."""
    slug = ''.join(ch if ch.isalnum() or ch == '-' else '' for ch in str(name or '').lower())
    slug = slug.strip('-')
    if parallel and slug and not slug.endswith('par'):
        slug += 'par'
    return slug


def parse_equatorial(value: str | None) -> tuple[float, float] | None:
    text = str(value or '').strip()
    if not text:
        return None
    match = _EQ_VALUE.search(text)
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


def _local_tag(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


def _first_text(el) -> str:
    if el is None:
        return ''
    if el.text and el.text.strip():
        return el.text.strip()
    return ''


def _equatorial_from_target(ft) -> tuple[float, float] | None:
    for child in ft:
        if _local_tag(child.tag) != 'EquatorialPosition':
            continue
        parsed = parse_equatorial(child.get('Value') or child.get('RA') or '')
        if parsed is not None:
            return parsed
        ra = child.get('RA')
        dec = child.get('Dec')
        if ra and dec:
            signed = f'{ra} {dec if str(dec).strip()[:1] in "+-" else "+"+str(dec)}'
            parsed = parse_equatorial(signed)
            if parsed is not None:
                return parsed
    provisional = ft.get('ProvisionalCoordinates')
    return parse_equatorial(provisional)


def parallel_sky(ra: float, dec: float, orient_deg: float = 0.0) -> tuple[float, float]:
    """Sky position of ACS/WFC when WFC3/UVIS-CENTER is at ``(ra, dec)``.

    APT ``AladinOrientationAngle`` is treated as ORIENT (U3 PA). PA_V3 = ORIENT + 180.
    """
    try:
        import pysiaf
        from pysiaf.utils import rotations

        siaf = pysiaf.Siaf('HST')
        uvis = siaf['IUVISCTR']
        acs = siaf['JWFCENTER']
        pa_v3 = float(orient_deg) + 180.0
        att = rotations.attitude_matrix(uvis.V2Ref, uvis.V3Ref, float(ra), float(dec), pa_v3)
        acs.set_attitude_matrix(att)
        sky = acs.tel_to_sky(acs.V2Ref, acs.V3Ref)
        return float(sky[0]), float(sky[1])
    except Exception:
        return _parallel_sky_approx(ra, dec, orient_deg)


def _parallel_sky_approx(ra: float, dec: float, orient_deg: float) -> tuple[float, float]:
    dv2 = _ACS_WFC_CENTER[0] - _UVIS_CENTER[0]
    dv3 = _ACS_WFC_CENTER[1] - _UVIS_CENTER[1]
    pa = math.radians(float(orient_deg) + 180.0)
    east = (-dv2 * math.cos(pa) + dv3 * math.sin(pa)) / 3600.0
    north = (dv2 * math.sin(pa) + dv3 * math.cos(pa)) / 3600.0
    dec_r = math.radians(float(dec))
    return (
        (float(ra) + east / max(math.cos(dec_r), 1e-6)) % 360.0,
        max(-90.0, min(90.0, float(dec) + north)),
    )


def _orient_value(text: str | None) -> float:
    try:
        return float(str(text or '0').strip())
    except ValueError:
        return 0.0


def parse_apt_targets(path: Path | str, *, program_id: str) -> list[dict[str, Any]]:
    tree = ElementTree.parse(str(path))
    root = tree.getroot()
    fixed: dict[str, dict[str, Any]] = {}
    for ft in root.iter():
        if _local_tag(ft.tag) != 'FixedTarget':
            continue
        name = (ft.get('Name') or '').strip()
        sky = _equatorial_from_target(ft)
        if not name or sky is None:
            continue
        fixed[name] = {'name': name, 'ra': sky[0], 'dec': sky[1]}

    visits_by_target: dict[str, list[str]] = {}
    for visit in root.iter():
        if _local_tag(visit.tag) != 'Visit':
            continue
        number = (visit.get('Number') or '').strip()
        if not number:
            continue
        names = set()
        for el in visit.iter():
            target = (el.get('TargetName') or '').strip()
            if target and target.upper() not in {'ANY', 'OR', 'AND', 'NONE'}:
                names.add(target)
        for name in names:
            if name in fixed:
                rec = visits_by_target.setdefault(name, [])
                if number not in rec:
                    rec.append(number)

    observations: dict[str, dict[str, Any]] = {}
    for obs in root.iter():
        if _local_tag(obs.tag) != 'Observation':
            continue
        target = (obs.get('TargetName') or '').strip()
        if not target or target not in fixed:
            continue
        rec = observations.setdefault(
            target,
            {'has_prime': False, 'has_parallel': False, 'orient': 0.0},
        )
        instrument = (obs.get('Instrument') or '').upper()
        parallel = str(obs.get('CoordinatedParallel') or '').lower() == 'true'
        aladin = None
        for child in obs:
            if _local_tag(child.tag) == 'AladinPhase1Requirements':
                aladin = child
                break
        orient = _orient_value(aladin.get('AladinOrientationAngle') if aladin is not None else None)
        if parallel or instrument == 'ACS':
            rec['has_parallel'] = True
        else:
            rec['has_prime'] = True
            rec['orient'] = orient

    rows: list[dict[str, Any]] = []
    for name, target in sorted(fixed.items(), key=lambda item: item[0]):
        obs = observations.get(name) or {'has_prime': True, 'has_parallel': False, 'orient': 0.0}
        visits = visits_by_target.get(name) or []
        host = lookup_host_name(name) or pretty_target_name(name)
        display = pretty_target_name(name)
        prime_ra, prime_dec = float(target['ra']), float(target['dec'])
        rows.append(
            _record(
                program_id=program_id,
                name=output_slug(name),
                display_name=display,
                host=host,
                field_role='prime',
                ra=prime_ra,
                dec=prime_dec,
                visits=visits,
                notes=_notes('prime', visits, program_id),
            )
        )
        if obs.get('has_parallel'):
            par_ra, par_dec = parallel_sky(prime_ra, prime_dec, obs.get('orient') or 0.0)
            rows.append(
                _record(
                    program_id=program_id,
                    name=output_slug(name, parallel=True),
                    display_name=f'{display} parallel',
                    host=host,
                    field_role='parallel',
                    ra=par_ra,
                    dec=par_dec,
                    visits=visits,
                    notes=_notes('parallel', visits, program_id),
                    orient=obs.get('orient') or 0.0,
                )
            )
    return rows


def _notes(role: str, visits: Iterable[str], program_id: str) -> str:
    visit_text = ', '.join(visits) if visits else 'APT'
    if str(program_id) == '18338' and role == 'parallel':
        return f'ACS parallel field. APT visits {visit_text}.'
    if str(program_id) == '18338':
        return f'WFC3 prime field. APT visits {visit_text}.'
    return f'APT visits {visit_text}.'


def _record(
    *,
    program_id: str,
    name: str,
    display_name: str,
    host: str,
    field_role: str,
    ra: float,
    dec: float,
    visits: list[str],
    notes: str,
    orient: float | None = None,
) -> dict[str, Any]:
    from .program_sync import UV_PREIMAGE_FILTERS

    filters = list(UV_PREIMAGE_FILTERS) if str(program_id) == '18440' else []
    record = {
        'name': name,
        'display_name': display_name,
        'host': host,
        'sn_type': '',
        'field_role': field_role,
        'ra': ra,
        'dec': dec,
        'ra_sex': format_ra(ra),
        'dec_sex': format_dec(dec),
        'radius_arcmin': 5.0,
        'instruments': list(_ARCHIVAL_INSTRUMENTS),
        'telescope': 'hst',
        'notes': notes,
        'visits': list(visits),
        'ready': True,
        'observed': False,
        'filters': filters,
        'program_id': str(program_id),
    }
    if orient is not None and field_role == 'parallel':
        record['orient'] = float(orient)
    return record


def build_catalog(path: Path | str, *, program_id: str) -> dict[str, Any]:
    targets = parse_apt_targets(path, program_id=program_id)
    apt = Path(path)
    return {
        'program_id': str(program_id),
        'source': 'phase2-apt',
        'apt_path': str(apt),
        'updated_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        'n_targets': len(targets),
        'n_prime': sum(1 for row in targets if row.get('field_role') == 'prime'),
        'n_parallel': sum(1 for row in targets if row.get('field_role') == 'parallel'),
        'targets': targets,
    }


def packaged_catalog_path(program_id: str) -> Path:
    return Path(__file__).resolve().parent / 'data' / f'go{program_id}_targets.json'


def write_catalog(payload: dict[str, Any], path: Path) -> Path:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(payload, indent=2) + '\n')
    tmp.replace(path)
    return path
