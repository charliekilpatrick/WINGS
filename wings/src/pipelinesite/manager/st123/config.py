"""Example-target and stage definitions for the st123 campaign site."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StageSpec:
    key: str
    label: str
    cli: str
    description: str
    log_prefixes: tuple[str, ...]
    artifacts: tuple[str, ...]


@dataclass(frozen=True)
class TargetSpec:
    name: str
    display_name: str
    host: str
    sn_type: str
    ra: float
    dec: float
    ra_sex: str
    dec_sex: str
    radius_arcmin: float
    instruments: tuple[str, ...]
    telescope: str
    base_dir: Path
    notes: str
    program_id: str = '18338'
    filters: tuple[str, ...] = ()
    field_role: str = 'prime'


STAGES: tuple[StageSpec, ...] = (
    StageSpec(
        key='download',
        label='Download',
        cli='download',
        description='Query MAST and pull imaging products into download/.',
        log_prefixes=('download',),
        artifacts=('download',),
    ),
    StageSpec(
        key='align',
        label='Align',
        cli='align',
        description='Visit-level JHAT alignment of frames to a common WCS.',
        log_prefixes=('align',),
        artifacts=('reduction/jhat', 'reduction/jhat_hst'),
    ),
    StageSpec(
        key='mosaic',
        label='Mosaic',
        cli='mosaic',
        description='Build shared-stamp coadds and dolphot_frames.txt manifests.',
        log_prefixes=('mosaic',),
        artifacts=('reduction/reference',),
    ),
    StageSpec(
        key='prepare_dolphot',
        label='Prepare DOLPHOT',
        cli='dolphot-prep',
        description='Stage masks, calcsky, and dolphot.param for each mosaic box.',
        log_prefixes=('dolphot-prep',),
        artifacts=('dolphot.param',),
    ),
    StageSpec(
        key='run_dolphot',
        label='Run DOLPHOT',
        cli='run-dolphot',
        description='Run DOLPHOT photometry in each prepared working directory.',
        log_prefixes=('run-dolphot',),
        artifacts=('*.phot',),
    ),
    StageSpec(
        key='combine_catalogs',
        label='Combine catalogs',
        cli='dolphot-hdf5',
        description='Write compressed HDF5 sidecars (and a merge when several runs exist).',
        log_prefixes=('dolphot-hdf5',),
        artifacts=('*.h5',),
    ),
)

EXAMPLE_TARGET = TargetSpec(
    name='2026dix',
    display_name='SN 2026dix',
    host='NGC 3913',
    sn_type='IIb',
    ra=177.65595,
    dec=55.353589,
    ra_sex='11:50:37.428',
    dec_sex='+55:21:12.92',
    radius_arcmin=5.0,
    instruments=('ACS', 'WFC3', 'WFPC2'),
    telescope='hst',
    base_dir=Path('/data/ckilpatrick/HST/2026dix'),
    notes='',
)

NGC1494_TARGET = TargetSpec(
    name='ngc1494',
    display_name='NGC 1494',
    host='NGC 1494',
    sn_type='',
    ra=59.427364,
    dec=-48.911362,
    ra_sex='03:57:42.567',
    dec_sex='-48:54:40.90',
    radius_arcmin=5.0,
    instruments=('ACS', 'WFC3', 'WFPC2'),
    telescope='hst',
    base_dir=Path('/data/ckilpatrick/HST/ngc1494'),
    notes='',
)

NGC784_TARGET = TargetSpec(
    name='ngc784',
    display_name='NGC 784',
    host='NGC 784',
    sn_type='',
    ra=30.32042,
    dec=28.83722,
    ra_sex='02:01:16.901',
    dec_sex='+28:50:13.99',
    radius_arcmin=5.0,
    instruments=('ACS', 'WFC3', 'WFPC2'),
    telescope='hst',
    base_dir=Path('/data/ckilpatrick/HST/ngc784'),
    notes='',
)

NGC4157_TARGET = TargetSpec(
    name='ngc4157',
    display_name='NGC 4157',
    host='NGC 4157',
    sn_type='',
    ra=182.7681875,
    dec=50.48468056,
    ra_sex='12:11:04.365',
    dec_sex='+50:29:04.85',
    radius_arcmin=5.0,
    instruments=('ACS',),
    telescope='hst',
    base_dir=Path('/data/ckilpatrick/HST/ngc4157'),
    notes='Candidate. Archival ACS/WFC F555W+F814W from GO 17070 (SN 2003J).',
)

_FIXED_TARGETS = (NGC1494_TARGET, NGC784_TARGET, NGC4157_TARGET,)

DEFAULT_QUALITY_CUTS = {
    'types': (1,),
    'sharp_max': 0.3,
    'crowd_max': 0.5,
    'snr_min': None,
}


def _django_settings() -> Any | None:
    try:
        from django.conf import settings
    except Exception:
        return None
    if not getattr(settings, 'configured', False):
        return None
    return settings


def _norm_label(value: str | None) -> str:
    return ''.join(ch for ch in str(value or '').lower() if ch.isalnum())


def campaign_targets(program: str | None = None) -> list[TargetSpec]:
    """Targets shown on a campaign table, optionally limited to one program."""
    from .program_sync import load_registry_specs
    from .programs import find_program, list_program_specs

    wanted = find_program(program) if program else None
    programs = (wanted,) if wanted is not None else list_program_specs()
    rows: list[TargetSpec] = []
    seen: set[str] = set()

    def _add(spec: TargetSpec) -> None:
        key = _norm_label(spec.name)
        if key in seen:
            return
        rows.append(spec)
        seen.add(key)

    for prog in programs:
        if prog is None:
            continue
        if prog.include_example:
            example = target_config()
            if _norm_label(example.program_id) == _norm_label(prog.program_id):
                _add(example)
        if prog.include_fixed:
            for spec in _FIXED_TARGETS:
                if _norm_label(spec.program_id) == _norm_label(prog.program_id):
                    _add(spec)
        override = _registry_override()
        if (
            override is not None
            and override.is_file()
            and _norm_label(prog.program_id) == _norm_label(program_id())
        ):
            for spec in load_registry_specs(override, program_id=prog.program_id):
                _add(spec)
            continue
        packaged = packaged_catalog_path(prog.program_id)
        if packaged.is_file():
            for spec in load_registry_specs(packaged, program_id=prog.program_id):
                _add(spec)
        registry = campaign_registry_path(prog.program_id)
        if registry.is_file() and (not packaged.is_file() or registry.resolve() != packaged.resolve()):
            from .program_sync import load_registry, spec_from_record

            for row in load_registry(registry).get('targets') or []:
                if row.get('source') != 'manual' or not row.get('ready'):
                    continue
                spec = spec_from_record(row, program_id=prog.program_id)
                if spec is None:
                    continue
                key = _norm_label(spec.name)
                rows[:] = [item for item in rows if _norm_label(item.name) != key]
                seen.discard(key)
                _add(spec)
    return rows


def _registry_override() -> Path | None:
    settings = _django_settings()
    if settings is None:
        return None
    configured = getattr(settings, 'ST123_CAMPAIGN_REGISTRY', None)
    if configured:
        return Path(configured)
    return None


def find_target(name: str) -> TargetSpec | None:
    want = _norm_label(name)
    if not want:
        return None
    specs = campaign_targets()
    for spec in specs:
        if _norm_label(spec.name) == want:
            return spec
    example = target_config()
    if want in {
        _norm_label(example.name),
        _norm_label(example.display_name),
        _norm_label(example.host),
    }:
        return example
    for spec in specs:
        if want in {
            _norm_label(spec.display_name),
            _norm_label(spec.host),
        }:
            return spec
    return None


def target_config() -> TargetSpec:
    settings = _django_settings()
    if settings is None:
        return EXAMPLE_TARGET
    base = getattr(settings, 'ST123_BASE_DIR', None) or EXAMPLE_TARGET.base_dir
    return TargetSpec(
        name=getattr(settings, 'ST123_TARGET_NAME', EXAMPLE_TARGET.name),
        display_name=getattr(settings, 'ST123_TARGET_DISPLAY', EXAMPLE_TARGET.display_name),
        host=getattr(settings, 'ST123_TARGET_HOST', EXAMPLE_TARGET.host),
        sn_type=getattr(settings, 'ST123_TARGET_TYPE', EXAMPLE_TARGET.sn_type),
        ra=float(getattr(settings, 'ST123_TARGET_RA', EXAMPLE_TARGET.ra)),
        dec=float(getattr(settings, 'ST123_TARGET_DEC', EXAMPLE_TARGET.dec)),
        ra_sex=getattr(settings, 'ST123_TARGET_RA_SEX', EXAMPLE_TARGET.ra_sex),
        dec_sex=getattr(settings, 'ST123_TARGET_DEC_SEX', EXAMPLE_TARGET.dec_sex),
        radius_arcmin=float(getattr(settings, 'ST123_RADIUS_ARCMIN', EXAMPLE_TARGET.radius_arcmin)),
        instruments=tuple(getattr(settings, 'ST123_INSTRUMENTS', EXAMPLE_TARGET.instruments)),
        telescope=getattr(settings, 'ST123_TELESCOPE', EXAMPLE_TARGET.telescope),
        base_dir=Path(base),
        notes=getattr(settings, 'ST123_TARGET_NOTES', EXAMPLE_TARGET.notes),
        program_id='18338',
        field_role='prime',
    )


def quality_cuts() -> dict[str, Any]:
    settings = _django_settings()
    cuts = dict(DEFAULT_QUALITY_CUTS)
    if settings is None:
        return cuts
    cuts['sharp_max'] = float(getattr(settings, 'ST123_CUT_SHARP_MAX', cuts['sharp_max']))
    cuts['crowd_max'] = float(getattr(settings, 'ST123_CUT_CROWD_MAX', cuts['crowd_max']))
    snr = getattr(settings, 'ST123_CUT_SNR_MIN', cuts['snr_min'])
    cuts['snr_min'] = None if snr in (None, '', False) else float(snr)
    return cuts


def st123_root() -> Path:
    settings = _django_settings()
    if settings is not None:
        return Path(getattr(settings, 'ST123_ROOT', '/data/ckilpatrick/st123'))
    return Path('/data/ckilpatrick/st123')


def st123_bin_dir() -> Path:
    settings = _django_settings()
    if settings is not None:
        return Path(getattr(settings, 'ST123_BIN', '/home/ckilpatrick/anaconda3/envs/st123/bin'))
    return Path('/home/ckilpatrick/anaconda3/envs/st123/bin')


def dolphot_bin_dir() -> Path:
    settings = _django_settings()
    if settings is not None:
        return Path(getattr(settings, 'ST123_DOLPHOT_BIN', '/data/software/dolphot/bin'))
    return Path('/data/software/dolphot/bin')


def ncores() -> int:
    settings = _django_settings()
    if settings is not None:
        return int(getattr(settings, 'ST123_NCORES', 4))
    return 4


def max_concurrent_jobs() -> int:
    settings = _django_settings()
    if settings is not None:
        return max(1, int(getattr(settings, 'ST123_MAX_CONCURRENT_JOBS', 1)))
    return 1


def dispatch_lock_path() -> Path:
    settings = _django_settings()
    default = Path('/data/ckilpatrick/HST/.pipelinesite/dispatch.lock')
    if settings is None:
        return default
    return Path(getattr(settings, 'ST123_DISPATCH_LOCK', default) or default)


def status_dir(base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir is not None else target_config().base_dir
    return root / '.pipelinesite'


def status_path(base_dir: Path | None = None) -> Path:
    return status_dir(base_dir) / 'status.json'


def _preview_stem(image_id: str | None = None) -> str:
    if not image_id:
        return 'reference_preview'
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in str(image_id))
    return f'preview_{safe[:120]}'


def preview_path(base_dir: Path | None = None, image_id: str | None = None) -> Path:
    return status_dir(base_dir) / f'{_preview_stem(image_id)}.png'


def preview_meta_path(base_dir: Path | None = None, image_id: str | None = None) -> Path:
    return status_dir(base_dir) / f'{_preview_stem(image_id)}.json'


def gladeplus_dir() -> Path:
    settings = _django_settings()
    if settings is not None:
        return Path(getattr(settings, 'GLADEPLUS_DIR', '/data/ckilpatrick/catalogs/GLADE+'))
    return Path('/data/ckilpatrick/catalogs/GLADE+')


def program_id() -> str:
    settings = _django_settings()
    if settings is not None:
        return str(getattr(settings, 'HST_PROGRAM_ID', '18338'))
    return '18338'


def data_root() -> Path:
    settings = _django_settings()
    default = Path('/data/ckilpatrick/HST')
    if settings is None:
        return default
    return Path(getattr(settings, 'ST123_DATA_ROOT', default) or default)


def output_root() -> Path:
    settings = _django_settings()
    default = Path('/data/ckilpatrick')
    if settings is None:
        return default
    return Path(getattr(settings, 'ST123_OUTPUT_ROOT', default) or default)


def program_data_root(program: str | None = None) -> Path:
    from .programs import find_program

    prog = find_program(program or program_id())
    slug = prog.output_name if prog else f'go{program or program_id()}'
    return output_root() / slug


def packaged_catalog_path(program: str | None = None) -> Path:
    from .apt import packaged_catalog_path as _packaged
    from .programs import find_program

    prog = find_program(program or program_id())
    pid = prog.program_id if prog else str(program or program_id())
    return _packaged(pid)


def campaign_registry_path(program: str | None = None) -> Path:
    from .programs import find_program

    prog = find_program(program or program_id())
    filename = prog.registry_filename if prog and prog.registry_filename else 'campaign_targets.json'
    default = program_data_root(prog.program_id if prog else program) / '.pipelinesite' / filename
    settings = _django_settings()
    if settings is None:
        return default
    configured = getattr(settings, 'ST123_CAMPAIGN_REGISTRY', None)
    if configured and (prog is None or prog.program_id == program_id()):
        return Path(configured)
    return default
