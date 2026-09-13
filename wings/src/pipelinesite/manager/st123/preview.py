"""Build a cached PNG preview of the DOLPHOT reference image."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import preview_meta_path, preview_path, status_dir
from .inventory import discover_phot_files, resolve_display_image
from .sky import read_image_header, reference_heading


def _asinh_stretch(data):
    import numpy as np

    finite = np.isfinite(data)
    work = np.where(finite, data, 0.0)
    sample = work[finite & (work != 0)]
    if sample.size == 0:
        return np.zeros_like(work, dtype='uint8')
    sky = float(np.median(sample))
    mad = float(np.median(np.abs(sample - sky)))
    sigma = 1.4826 * mad if mad > 0 else float(np.std(sample) or 1.0)
    lo = sky - 0.5 * sigma
    hi = sky + 20.0 * sigma
    if hi <= lo:
        hi = lo + 1.0
    scaled = np.clip((work - lo) / (hi - lo), 0.0, 1.0)
    stretched = np.arcsinh(scaled * 8.0) / np.arcsinh(8.0)
    stretched = np.where(finite, stretched, 0.0)
    # Invert so bright pixels are dark on a light background.
    return (255.0 * (1.0 - stretched)).astype('uint8')


def build_preview(
    base_dir: Path,
    *,
    image_id: str | None = None,
    max_dim: int = 1400,
    force: bool = False,
) -> dict[str, Any] | None:
    reference = resolve_display_image(base_dir, image_id)
    if reference is None:
        return None
    cache_id = image_id or 'default'
    out = preview_path(base_dir, cache_id)
    meta_file = preview_meta_path(base_dir, cache_id)
    preview_version = 6
    if out.is_file() and out.stat().st_size > 0 and meta_file.is_file() and not force:
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}
        if (
            meta.get('source') == str(reference)
            and meta.get('source_mtime') == reference.stat().st_mtime
            and meta.get('preview_version') == preview_version
        ):
            return meta

    from astropy.io import fits
    from PIL import Image
    import numpy as np

    with fits.open(reference, memmap=True) as hdul:
        data = None
        for hdu in hdul:
            arr = getattr(hdu, 'data', None)
            if arr is not None and getattr(arr, 'ndim', 0) >= 2:
                data = np.asarray(arr, dtype=float)
                break
    if data is None:
        return None
    if data.ndim > 2:
        data = data[0]
    ny, nx = data.shape[-2:]
    scale = min(1.0, float(max_dim) / float(max(nx, ny)))
    out_w = max(1, int(round(nx * scale)))
    out_h = max(1, int(round(ny * scale)))
    stretched = _asinh_stretch(data)
    image = Image.fromarray(stretched, mode='L')
    if (out_w, out_h) != (nx, ny):
        image = image.resize((out_w, out_h), getattr(Image, 'BILINEAR', 2))
    # FITS origin is lower-left; flip so the PNG matches sky-up overlay math.
    image = image.transpose(getattr(Image, 'FLIP_TOP_BOTTOM', 1))
    status_dir(base_dir).mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + '.tmp')
    image.save(tmp, format='PNG')
    tmp.replace(out)
    phot = discover_phot_files(base_dir)
    header = read_image_header(reference)
    wcs = header.get('wcs') or {}
    if wcs:
        wcs = dict(wcs)
        wcs['nx'] = int(nx)
        wcs['ny'] = int(ny)
    meta = {
        'image_id': image_id,
        'source': str(reference),
        'source_mtime': reference.stat().st_mtime,
        'png': str(out),
        'nx': int(nx),
        'ny': int(ny),
        'width': out_w,
        'height': out_h,
        'scale': scale,
        'phot': str(phot[0]) if phot else None,
        'preview_version': preview_version,
        'instrument': header.get('instrument'),
        'detector': header.get('detector'),
        'filter': header.get('filter'),
        'date_obs': header.get('date_obs'),
        'exptime': header.get('exptime'),
        'photflam': header.get('photflam'),
        'photplam': header.get('photplam'),
        'heading': reference_heading(header),
        'wcs': wcs or None,
    }
    meta_file.write_text(json.dumps(meta, indent=2))
    return meta
