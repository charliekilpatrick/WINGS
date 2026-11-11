"""Parse DOLPHOT ``*.columns`` photometry into AB magnitudes for the viewer."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .sky import ab_zeropoint, read_image_header

# AB = Vega + offset. Values follow the usual HST handbook / synphot offsets.
_VEGA_TO_AB = {
    ('ACS', 'F435W'): 0.101,
    ('ACS', 'F475W'): 0.098,
    ('ACS', 'F555W'): 0.009,
    ('ACS', 'F606W'): 0.081,
    ('ACS', 'F625W'): 0.155,
    ('ACS', 'F775W'): 0.401,
    ('ACS', 'F814W'): 0.424,
    ('ACS', 'F850LP'): 0.539,
    ('WFC3', 'F225W'): 1.659,
    ('WFC3', 'F275W'): 1.501,
    ('WFC3', 'F336W'): 1.188,
    ('WFC3', 'F390W'): 0.508,
    ('WFC3', 'F438W'): 0.220,
    ('WFC3', 'F475W'): 0.157,
    ('WFC3', 'F555W'): 0.035,
    ('WFC3', 'F606W'): 0.103,
    ('WFC3', 'F625W'): 0.169,
    ('WFC3', 'F775W'): 0.401,
    ('WFC3', 'F814W'): 0.418,
    ('WFC3', 'F850LP'): 0.521,
    ('WFPC2', 'F300W'): 1.077,
    ('WFPC2', 'F336W'): 1.187,
    ('WFPC2', 'F439W'): 0.088,
    ('WFPC2', 'F450W'): 0.053,
    ('WFPC2', 'F555W'): 0.030,
    ('WFPC2', 'F606W'): 0.100,
    ('WFPC2', 'F675W'): 0.200,
    ('WFPC2', 'F702W'): 0.246,
    ('WFPC2', 'F814W'): 0.429,
}

_COL = re.compile(r'^\s*(\d+)\.\s+(.*)$')
_COMBINED_TAG = re.compile(
    r'^(ACS|WFC3|WFPC2|NIRCAM|NIRISS|MIRI)_([A-Za-z0-9]+)$',
    re.IGNORECASE,
)
_PER_IMAGE = re.compile(
    r'^(?P<field>.+),\s+(?P<image>\S+?)(?:\s+\((?P<extra>[^)]*)\))?$'
)
_SENTINEL_MAG = 90.0
_SENTINEL_ERR = 9.0
_MAG_SNR = 2.5 / math.log(10)
_DETECT_SNR = 3.0


@dataclass
class FilterPhot:
    instrument: str
    filt: str
    vega_idx: int | None = None
    magerr_idx: int | None = None
    is_ab: bool = False
    rate_idxs: list[int] = field(default_factory=list)
    rateerr_idxs: list[int] = field(default_factory=list)
    zp_ab: float | None = None

    @property
    def name(self) -> str:
        return f'{self.instrument} {self.filt}'.strip()


def vega_to_ab_offset(instrument: str, filt: str) -> float | None:
    return _VEGA_TO_AB.get((str(instrument).upper(), str(filt).upper()))


def parse_columns_file(path: Path) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(errors='replace').splitlines():
        match = _COL.match(line)
        if not match:
            continue
        rows.append((int(match.group(1)) - 1, match.group(2).strip()))
    return rows


def _split_tag(tag: str) -> tuple[str, str] | None:
    match = _COMBINED_TAG.match(tag.strip())
    if not match:
        return None
    return match.group(1).upper(), match.group(2).upper()


def _frame_stem(image: str) -> str:
    name = image.strip()
    name = re.sub(r'\.chip\d+$', '', name, flags=re.IGNORECASE)
    if name.lower().endswith('.fits'):
        name = name[:-5]
    return name


def _lookup_frame(image: str, search_dirs: Iterable[Path]) -> Path | None:
    stem = _frame_stem(image)
    names = [f'{stem}.fits', f'{stem}_jhat.fits']
    if not stem.endswith('_jhat'):
        names.append(f'{stem}_jhat.fits')
    for directory in search_dirs:
        if not directory or not directory.is_dir():
            continue
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
        matches = list(directory.glob(f'{stem}*.fits'))
        matches = [p for p in matches if 'sky' not in p.name.lower()]
        if matches:
            return sorted(matches)[0]
    return None


def _ensure_filter(plan: dict[tuple[str, str], FilterPhot], instrument: str, filt: str) -> FilterPhot:
    key = (instrument, filt)
    if key not in plan:
        plan[key] = FilterPhot(instrument=instrument, filt=filt)
    return plan[key]


def build_filter_plan(
    columns: Path,
    *,
    search_dirs: Iterable[Path] | None = None,
    reference_header: dict[str, Any] | None = None,
) -> list[FilterPhot]:
    """Map combined and per-image DOLPHOT columns onto AB filter measurements."""
    plan: dict[tuple[str, str], FilterPhot] = {}
    frame_cache: dict[str, dict[str, Any]] = {}
    dirs = [Path(p) for p in (search_dirs or []) if p]

    def frame_meta(image: str) -> dict[str, Any]:
        if image not in frame_cache:
            path = _lookup_frame(image, dirs)
            frame_cache[image] = read_image_header(path) if path else {}
        return frame_cache[image]

    for idx, desc in parse_columns_file(columns):
        parsed = _PER_IMAGE.match(desc)
        if parsed:
            field = parsed.group('field').strip()
            image = parsed.group('image').strip()
            extra = parsed.group('extra') or ''
            tag = _split_tag(image)
            extra_tag = None
            for token in extra.replace(',', ' ').split():
                extra_tag = _split_tag(token) or extra_tag
            if tag:
                instrument, filt = tag
                phot = _ensure_filter(plan, instrument, filt)
                if field == 'Instrumental ABMAG magnitude':
                    phot.vega_idx = idx
                    phot.is_ab = True
                elif field in {
                    'Instrumental VEGAMAG magnitude',
                    'Instrumental magnitude',
                } and phot.vega_idx is None:
                    phot.vega_idx = idx
                elif field == 'Magnitude uncertainty' and phot.magerr_idx is None:
                    phot.magerr_idx = idx
                continue
            meta = frame_meta(image)
            instrument = (
                (extra_tag[0] if extra_tag else '')
                or (meta.get('instrument') or '')
            ).upper()
            filt = (
                (extra_tag[1] if extra_tag else '')
                or (meta.get('filter') or '')
            ).upper()
            if not instrument or not filt:
                continue
            phot = _ensure_filter(plan, instrument, filt)
            # Always collect rates for multi-chip/frame AB; a single per-chip
            # "Instrumental magnitude" is a poor substitute for the stack.
            if field == 'Normalized count rate':
                phot.rate_idxs.append(idx)
            elif field == 'Normalized count rate uncertainty':
                phot.rateerr_idxs.append(idx)
            elif field == 'Instrumental ABMAG magnitude':
                phot.vega_idx = idx
                phot.is_ab = True
            elif field in {
                'Instrumental VEGAMAG magnitude',
                'Instrumental magnitude',
            } and phot.vega_idx is None:
                phot.vega_idx = idx
            elif field == 'Magnitude uncertainty' and phot.magerr_idx is None:
                phot.magerr_idx = idx
            if phot.zp_ab is None:
                phot.zp_ab = ab_zeropoint(meta.get('photflam'), meta.get('photplam'))
            continue

        # Combined stack: "Instrumental VEGAMAG magnitude, WFPC2_F450W"
        for prefix, attr, is_ab in (
            ('Instrumental ABMAG magnitude, ', 'vega_idx', True),
            ('Instrumental VEGAMAG magnitude, ', 'vega_idx', False),
            ('Instrumental magnitude, ', 'vega_idx', False),
            ('Magnitude uncertainty, ', 'magerr_idx', False),
        ):
            if desc.startswith(prefix):
                tag = _split_tag(desc[len(prefix):])
                if not tag:
                    continue
                phot = _ensure_filter(plan, tag[0], tag[1])
                if attr == 'vega_idx' and phot.vega_idx is None:
                    phot.vega_idx = idx
                    phot.is_ab = is_ab or phot.is_ab
                elif attr == 'magerr_idx' and phot.magerr_idx is None:
                    phot.magerr_idx = idx
                break

    if reference_header:
        inst = (reference_header.get('instrument') or '').upper()
        filt = (reference_header.get('filter') or '').upper()
        zp = ab_zeropoint(reference_header.get('photflam'), reference_header.get('photplam'))
        if inst and filt:
            phot = _ensure_filter(plan, inst, filt)
            if phot.zp_ab is None:
                phot.zp_ab = zp

    ordered = sorted(plan.values(), key=lambda row: (row.instrument, row.filt))
    return [row for row in ordered if row.vega_idx is not None or row.rate_idxs]


def _safe_float(parts: list[str], idx: int | None) -> float | None:
    if idx is None or idx < 0 or idx >= len(parts):
        return None
    try:
        value = float(parts[idx])
    except (TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return value


def _combine_rates(parts: list[str], phot: FilterPhot) -> tuple[float, float] | None:
    nums: list[tuple[float, float]] = []
    for rate_idx, err_idx in zip(phot.rate_idxs, phot.rateerr_idxs or [None] * len(phot.rate_idxs)):
        rate = _safe_float(parts, rate_idx)
        err = _safe_float(parts, err_idx)
        if rate is None or rate <= 0:
            continue
        if err is None or err <= 0 or err >= 100:
            err = None
        weight = 1.0 if err is None else 1.0 / (err * err)
        nums.append((rate, weight))
    if not nums:
        return None
    weight_sum = sum(weight for _rate, weight in nums)
    rate = sum(rate * weight for rate, weight in nums) / weight_sum
    err = math.sqrt(1.0 / weight_sum)
    return rate, err


def flux_snr(magerr: float | None) -> float | None:
    if magerr is None or magerr <= 0:
        return None
    return _MAG_SNR / magerr


def three_sigma_limit(mag: float, magerr: float | None) -> float | None:
    snr = flux_snr(magerr)
    if snr is None or snr <= 0:
        return None
    return mag - 2.5 * math.log10(_DETECT_SNR / snr)


def _mag_row(
    *,
    instrument: str,
    filt: str,
    mag: float,
    magerr: float | None,
    source: str | None,
    mjd: float | None = None,
    exposure: str | None = None,
    n_epochs: int | None = None,
) -> dict[str, Any]:
    snr = flux_snr(magerr)
    is_limit = snr is None or snr < _DETECT_SNR
    limit = three_sigma_limit(float(mag), magerr) if is_limit else None
    row: dict[str, Any] = {
        'name': f'{instrument} {filt}'.strip(),
        'instrument': instrument,
        'filter': filt,
        'mag': float(mag),
        'magerr': None if magerr is None else float(magerr),
        'snr': None if snr is None else float(snr),
        'is_limit': bool(is_limit and limit is not None),
        'limit_mag': None if limit is None else float(limit),
        'system': 'AB',
        'source': source,
        'mjd': None if mjd is None else float(mjd),
    }
    if exposure is not None:
        row['exposure'] = exposure
    if n_epochs is not None:
        row['n_epochs'] = int(n_epochs)
    return row


def row_ab_mags(parts: list[str], plan: list[FilterPhot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for phot in plan:
        mag = None
        magerr = None
        source = None
        # Prefer stacked count rates when available (multi-chip DOLPHOT runs).
        if phot.zp_ab is not None and phot.rate_idxs:
            combined = _combine_rates(parts, phot)
            if combined is not None:
                rate, rate_err = combined
                mag = phot.zp_ab - 2.5 * math.log10(rate)
                magerr = (2.5 / math.log(10)) * (rate_err / rate)
                source = 'count_rate'
        vega = _safe_float(parts, phot.vega_idx)
        verr = _safe_float(parts, phot.magerr_idx)
        if mag is None and vega is not None and abs(vega) < _SENTINEL_MAG:
            if phot.is_ab:
                mag = vega
                source = 'dolphot_ab'
            else:
                offset = vega_to_ab_offset(phot.instrument, phot.filt)
                if offset is not None:
                    mag = vega + offset
                    source = 'vega_to_ab'
            if verr is not None and 0 <= verr < _SENTINEL_ERR:
                magerr = verr
        elif mag is not None and magerr is None and verr is not None and 0 <= verr < _SENTINEL_ERR:
            magerr = verr
        if mag is None or mag > 40:
            continue
        out.append(
            _mag_row(
                instrument=phot.instrument,
                filt=phot.filt,
                mag=float(mag),
                magerr=None if magerr is None else float(magerr),
                source=source,
            )
        )
    return out


@dataclass
class EpochPhot:
    exposure: str
    instrument: str
    filt: str
    mjd: float | None = None
    zp_ab: float | None = None
    is_ab: bool = False
    rate_idxs: list[int] = field(default_factory=list)
    rateerr_idxs: list[int] = field(default_factory=list)
    vega_idx: int | None = None
    magerr_idx: int | None = None


def build_epoch_plan(
    columns: Path,
    *,
    search_dirs: Iterable[Path] | None = None,
) -> list[EpochPhot]:
    """One photometry group per exposure × filter (chips combined)."""
    plan: dict[tuple[str, str, str], EpochPhot] = {}
    frame_cache: dict[str, dict[str, Any]] = {}
    dirs = [Path(p) for p in (search_dirs or []) if p]

    def frame_meta(image: str) -> dict[str, Any]:
        stem = _frame_stem(image)
        if stem not in frame_cache:
            path = _lookup_frame(image, dirs)
            frame_cache[stem] = read_image_header(path) if path else {}
        return frame_cache[stem]

    for idx, desc in parse_columns_file(columns):
        parsed = _PER_IMAGE.match(desc)
        if not parsed:
            continue
        field = parsed.group('field').strip()
        image = parsed.group('image').strip()
        extra = parsed.group('extra') or ''
        tag = _split_tag(image)
        extra_tag = None
        for token in extra.replace(',', ' ').split():
            extra_tag = _split_tag(token) or extra_tag
        meta = {} if tag else frame_meta(image)
        instrument = (
            (tag[0] if tag else '')
            or (extra_tag[0] if extra_tag else '')
            or (meta.get('instrument') or '')
        ).upper()
        filt = (
            (tag[1] if tag else '')
            or (extra_tag[1] if extra_tag else '')
            or (meta.get('filter') or '')
        ).upper()
        if not instrument or not filt:
            continue
        exposure = _frame_stem(image)
        key = (exposure, instrument, filt)
        phot = plan.get(key)
        if phot is None:
            phot = EpochPhot(
                exposure=exposure,
                instrument=instrument,
                filt=filt,
                mjd=None if tag else meta.get('mjd'),
                zp_ab=None if tag else ab_zeropoint(meta.get('photflam'), meta.get('photplam')),
            )
            plan[key] = phot
        elif phot.mjd is None and not tag:
            phot.mjd = meta.get('mjd')
        if phot.zp_ab is None and not tag:
            phot.zp_ab = ab_zeropoint(meta.get('photflam'), meta.get('photplam'))
        if field == 'Normalized count rate':
            phot.rate_idxs.append(idx)
        elif field == 'Normalized count rate uncertainty':
            phot.rateerr_idxs.append(idx)
        elif field == 'Instrumental ABMAG magnitude':
            phot.vega_idx = idx
            phot.is_ab = True
        elif field in {'Instrumental VEGAMAG magnitude', 'Instrumental magnitude'} and phot.vega_idx is None:
            phot.vega_idx = idx
        elif field == 'Magnitude uncertainty' and phot.magerr_idx is None:
            phot.magerr_idx = idx

    ordered = sorted(plan.values(), key=lambda row: (row.mjd is None, row.mjd or 0.0, row.instrument, row.filt, row.exposure))
    return [row for row in ordered if row.rate_idxs or row.vega_idx is not None]


def _epoch_mag(parts: list[str], phot: EpochPhot) -> dict[str, Any] | None:
    mag = None
    magerr = None
    source = None
    if phot.zp_ab is not None and phot.rate_idxs:
        combined = _combine_rates(
            parts,
            FilterPhot(
                instrument=phot.instrument,
                filt=phot.filt,
                rate_idxs=phot.rate_idxs,
                rateerr_idxs=phot.rateerr_idxs,
                zp_ab=phot.zp_ab,
            ),
        )
        if combined is not None:
            rate, rate_err = combined
            mag = phot.zp_ab - 2.5 * math.log10(rate)
            magerr = (2.5 / math.log(10)) * (rate_err / rate)
            source = 'count_rate'
    vega = _safe_float(parts, phot.vega_idx)
    verr = _safe_float(parts, phot.magerr_idx)
    if mag is None and vega is not None and abs(vega) < _SENTINEL_MAG:
        if phot.is_ab:
            mag = vega
            source = 'dolphot_ab'
        else:
            offset = vega_to_ab_offset(phot.instrument, phot.filt)
            if offset is not None:
                mag = vega + offset
                source = 'vega_to_ab'
        if verr is not None and 0 <= verr < _SENTINEL_ERR:
            magerr = verr
    elif mag is not None and magerr is None and verr is not None and 0 <= verr < _SENTINEL_ERR:
        magerr = verr
    if mag is None or mag > 40:
        return None
    return _mag_row(
        instrument=phot.instrument,
        filt=phot.filt,
        mag=float(mag),
        magerr=None if magerr is None else float(magerr),
        source=source,
        mjd=phot.mjd,
        exposure=phot.exposure,
    )


# Exposures closer than this are treated as one visit / observation.
_VISIT_GAP_DAYS = 1.0


def _combine_mag_rows(
    rows: list[dict[str, Any]],
    *,
    source: str,
    exposure: str | None = None,
) -> dict[str, Any] | None:
    """Inverse-variance flux average of magnitude rows (same instrument/filter)."""
    if not rows:
        return None
    if len(rows) == 1 and source != 'visit_average':
        # Keep singleton exposure rows as-is unless we are labeling a visit.
        out = dict(rows[0])
        out['n_epochs'] = 1
        return out
    fluxes: list[tuple[float, float, float | None]] = []
    exposures: list[str] = []
    instrument = str(rows[0].get('instrument') or '')
    filt = str(rows[0].get('filter') or '')
    for row in rows:
        mag = row.get('mag')
        if mag is None:
            continue
        flux = 10.0 ** (-0.4 * float(mag))
        magerr = row.get('magerr')
        if magerr is not None and magerr > 0:
            # σ_f / f ≈ 0.4 ln(10) σ_m
            rel = 0.4 * math.log(10) * float(magerr)
            weight = 1.0 / (flux * rel) ** 2 if rel > 0 else 1.0
        else:
            weight = 1.0
        fluxes.append((flux, weight, row.get('mjd')))
        exp = row.get('exposure')
        if exp:
            exposures.append(str(exp))
    if not fluxes:
        return None
    weight_sum = sum(weight for _flux, weight, _mjd in fluxes)
    mean_flux = sum(flux * weight for flux, weight, _mjd in fluxes) / weight_sum
    if mean_flux <= 0:
        return None
    mag = -2.5 * math.log10(mean_flux)
    flux_err = math.sqrt(1.0 / weight_sum)
    magerr = (2.5 / math.log(10)) * (flux_err / mean_flux)
    mjds = [mjd for _flux, _weight, mjd in fluxes if mjd is not None]
    mean_mjd = sum(mjds) / len(mjds) if mjds else None
    return _mag_row(
        instrument=instrument,
        filt=filt,
        mag=mag,
        magerr=magerr,
        source=source,
        mjd=mean_mjd,
        exposure=exposure if exposure is not None else '+'.join(dict.fromkeys(exposures)),
        n_epochs=len(fluxes),
    )


def collapse_visit_epochs(
    epochs: list[dict[str, Any]],
    *,
    max_gap_days: float = _VISIT_GAP_DAYS,
) -> list[dict[str, Any]]:
    """Combine same-filter exposures separated by less than ``max_gap_days``."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in epochs:
        key = (str(row.get('instrument') or ''), str(row.get('filter') or ''))
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        dated = [row for row in rows if row.get('mjd') is not None]
        undated = [row for row in rows if row.get('mjd') is None]
        dated.sort(key=lambda row: float(row['mjd']))
        cluster: list[dict[str, Any]] = []
        prev_mjd: float | None = None

        def flush() -> None:
            nonlocal cluster
            if not cluster:
                return
            combined = _combine_mag_rows(cluster, source='visit_average')
            if combined is not None:
                out.append(combined)
            cluster = []

        for row in dated:
            mjd = float(row['mjd'])
            if cluster and prev_mjd is not None and (mjd - prev_mjd) > max_gap_days:
                flush()
            cluster.append(row)
            prev_mjd = mjd
        flush()
        for row in undated:
            singleton = _combine_mag_rows([row], source=str(row.get('source') or 'exposure'))
            if singleton is not None:
                out.append(singleton)
    out.sort(key=lambda row: (row.get('mjd') is None, row.get('mjd') or 0.0, row.get('instrument') or '', row.get('filter') or ''))
    return out


def _average_filter_rows(epochs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inverse-variance flux average of epoch/visit rows, grouped by instrument+filter."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in epochs:
        key = (str(row.get('instrument') or ''), str(row.get('filter') or ''))
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for (instrument, filt), rows in sorted(groups.items()):
        combined = _combine_mag_rows(rows, source='epoch_average')
        if combined is not None:
            # n_epochs here means contributing visit/epoch rows.
            out.append(combined)
    return out


def source_photometry_tables(
    parts: list[str],
    epoch_plan: list[EpochPhot],
) -> dict[str, list[dict[str, Any]]]:
    """Return visit-combined and filter-averaged AB photometry for one DOLPHOT row."""
    exposures: list[dict[str, Any]] = []
    for phot in epoch_plan:
        row = _epoch_mag(parts, phot)
        if row is not None:
            exposures.append(row)
    epochs = collapse_visit_epochs(exposures)
    return {
        'epochs': epochs,
        'combined': _average_filter_rows(epochs),
    }
