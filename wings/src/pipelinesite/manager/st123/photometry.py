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
                elif field == 'Instrumental VEGAMAG magnitude' and phot.vega_idx is None:
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
            if field == 'Normalized count rate' and phot.vega_idx is None:
                phot.rate_idxs.append(idx)
            elif field == 'Normalized count rate uncertainty' and phot.vega_idx is None:
                phot.rateerr_idxs.append(idx)
            if phot.zp_ab is None:
                phot.zp_ab = ab_zeropoint(meta.get('photflam'), meta.get('photplam'))
            continue

        # Combined stack: "Instrumental VEGAMAG magnitude, WFPC2_F450W"
        for prefix, attr, is_ab in (
            ('Instrumental ABMAG magnitude, ', 'vega_idx', True),
            ('Instrumental VEGAMAG magnitude, ', 'vega_idx', False),
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


def row_ab_mags(parts: list[str], plan: list[FilterPhot]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for phot in plan:
        mag = None
        magerr = None
        source = None
        vega = _safe_float(parts, phot.vega_idx)
        verr = _safe_float(parts, phot.magerr_idx)
        if vega is not None and abs(vega) < _SENTINEL_MAG:
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
        if mag is None and phot.vega_idx is None and phot.zp_ab is not None and phot.rate_idxs:
            combined = _combine_rates(parts, phot)
            if combined is not None:
                rate, rate_err = combined
                mag = phot.zp_ab - 2.5 * math.log10(rate)
                magerr = (2.5 / math.log(10)) * (rate_err / rate)
                source = 'count_rate'
        if mag is None or mag > 40:
            continue
        snr = flux_snr(magerr)
        is_limit = snr is None or snr < _DETECT_SNR
        limit = three_sigma_limit(float(mag), magerr) if is_limit else None
        out.append(
            {
                'name': phot.name,
                'instrument': phot.instrument,
                'filter': phot.filt,
                'mag': float(mag),
                'magerr': None if magerr is None else float(magerr),
                'snr': None if snr is None else float(snr),
                'is_limit': bool(is_limit and limit is not None),
                'limit_mag': None if limit is None else float(limit),
                'system': 'AB',
                'source': source,
            }
        )
    return out
