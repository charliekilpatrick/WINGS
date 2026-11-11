"""Build cached WebP/AVIF/JPEG previews of campaign mosaics."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from .config import (
    mosaic_preview_publish_dir,
    mosaic_preview_static_base_url,
    preview_meta_path,
    preview_path,
    status_dir,
)
from .inventory import discover_phot_files, resolve_display_image
from .sky import apply_north_up_east_left, read_image_header, reference_heading

# Sharp enough for a full-width viewer; modern codecs keep bytes down.
DEFAULT_MAX_DIM = 2800
PREVIEW_VERSION = 13
WEBP_QUALITY = 82
AVIF_QUALITY = 80
JPEG_QUALITY = 90


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


def _bin_for_preview(data, wcs: dict[str, Any] | None, max_dim: int):
    """Integer-bin oversized mosaics before stretch/rotate to cut cold-build time."""
    import numpy as np

    arr = np.asarray(data)
    if arr.ndim != 2:
        return arr, wcs, 1
    ny, nx = int(arr.shape[0]), int(arr.shape[1])
    factor = max(1, int(max(nx, ny) / max(float(max_dim) * 1.5, 1.0)))
    if factor <= 1:
        return arr, wcs, 1
    usable_y = (ny // factor) * factor
    usable_x = (nx // factor) * factor
    if usable_y < factor or usable_x < factor:
        return arr, wcs, 1
    block = arr[:usable_y, :usable_x].reshape(
        usable_y // factor, factor, usable_x // factor, factor
    )
    binned = np.nanmean(block, axis=(1, 3))
    if not wcs:
        return binned, wcs, factor
    out = dict(wcs)
    crpix = list(out.get('crpix') or [1.0, 1.0])
    out['crpix'] = [(float(crpix[0]) - 0.5) / factor + 0.5, (float(crpix[1]) - 0.5) / factor + 0.5]
    cd = out.get('cd')
    if cd:
        out['cd'] = [
            [float(cd[0][0]) * factor, float(cd[0][1]) * factor],
            [float(cd[1][0]) * factor, float(cd[1][1]) * factor],
        ]
    out['nx'] = int(binned.shape[1])
    out['ny'] = int(binned.shape[0])
    return binned, out, factor


def _link_or_copy(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        try:
            dest.unlink()
        except OSError:
            pass
    try:
        os.link(src, dest)
    except OSError:
        shutil.copy2(src, dest)


def _save_formats(image, base_dir: Path, image_id: str | None) -> dict[str, Path]:
    """Write webp + jpeg always; avif when Pillow supports it."""
    paths: dict[str, Path] = {}
    webp = preview_path(base_dir, image_id, ext='webp')
    tmp = webp.with_suffix(webp.suffix + '.tmp')
    image.save(tmp, format='WEBP', quality=WEBP_QUALITY, method=4)
    tmp.replace(webp)
    paths['webp'] = webp

    jpg = preview_path(base_dir, image_id, ext='jpg')
    tmp = jpg.with_suffix(jpg.suffix + '.tmp')
    image.save(tmp, format='JPEG', quality=JPEG_QUALITY, optimize=True)
    tmp.replace(jpg)
    paths['jpeg'] = jpg

    try:
        avif = preview_path(base_dir, image_id, ext='avif')
        tmp = avif.with_suffix(avif.suffix + '.tmp')
        # AVIF encoders often prefer RGB.
        image.convert('RGB').save(tmp, format='AVIF', quality=AVIF_QUALITY)
        tmp.replace(avif)
        paths['avif'] = avif
    except Exception:
        pass
    return paths


def _publish_static(paths: dict[str, Path], base_dir: Path, image_id: str | None) -> dict[str, str]:
    """Hardlink/copy into STATIC_ROOT so nginx /static/ can serve without Django."""
    pub_dir = mosaic_preview_publish_dir(base_dir)
    stem = image_id or 'default'
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in str(stem))[:120]
    base_url = mosaic_preview_static_base_url(base_dir)
    urls: dict[str, str] = {}
    ext_map = {'webp': 'webp', 'avif': 'avif', 'jpeg': 'jpg'}
    for kind, src in paths.items():
        ext = ext_map[kind]
        dest = pub_dir / f'{safe}.{ext}'
        _link_or_copy(src, dest)
        # Version query busts nginx's long-lived / immutable Cache-Control on
        # /static/mosaic-previews/ after PREVIEW_VERSION changes.
        urls[kind] = f'{base_url}{safe}.{ext}?v={PREVIEW_VERSION}'
    return urls


def build_preview(
    base_dir: Path,
    *,
    image_id: str | None = None,
    max_dim: int = DEFAULT_MAX_DIM,
    force: bool = False,
) -> dict[str, Any] | None:
    cache_id = image_id or 'default'
    meta_file = preview_meta_path(base_dir, cache_id)
    webp_file = preview_path(base_dir, cache_id, ext='webp')
    preview_version = PREVIEW_VERSION
    reference = resolve_display_image(base_dir, image_id)
    if reference is None:
        return None
    if webp_file.is_file() and webp_file.stat().st_size > 0 and meta_file.is_file() and not force:
        try:
            meta = json.loads(meta_file.read_text())
        except (OSError, json.JSONDecodeError):
            meta = {}
        try:
            source_ok = (
                meta.get('source') == str(reference)
                and meta.get('source_mtime') == reference.stat().st_mtime
            )
        except OSError:
            source_ok = False
        if (
            source_ok
            and meta.get('preview_version') == preview_version
            and meta.get('format') == 'webp'
            and int(meta.get('max_dim') or 0) == int(max_dim)
            and (meta.get('wcs') or {}).get('orientation') == 'north_up_east_left'
            and (image_id is None or meta.get('image_id') in {None, image_id})
            and meta.get('static_urls')
        ):
            return meta

    from astropy.io import fits
    from PIL import Image
    import numpy as np

    with fits.open(reference, memmap=True) as hdul:
        data = None
        weight = None
        for hdu in hdul:
            arr = getattr(hdu, 'data', None)
            if arr is None or getattr(arr, 'ndim', 0) < 2:
                continue
            name = str(getattr(hdu, 'name', '') or '').upper()
            if name in {'WHT', 'WEIGHT', 'WGT'}:
                weight = np.asarray(arr, dtype=float)
                continue
            if data is None and name in {'', 'PRIMARY', 'SCI'}:
                data = np.asarray(arr, dtype=float)
        if data is None:
            for hdu in hdul:
                arr = getattr(hdu, 'data', None)
                if arr is not None and getattr(arr, 'ndim', 0) >= 2:
                    name = str(getattr(hdu, 'name', '') or '').upper()
                    if name in {'WHT', 'WEIGHT', 'WGT', 'CTX', 'DQ', 'ERR'}:
                        continue
                    data = np.asarray(arr, dtype=float)
                    break
    if data is None:
        return None
    if data.ndim > 2:
        data = data[0]
    if weight is not None and weight.ndim > 2:
        weight = weight[0]
    # Mask drizzle pads so empty FoV stays blank instead of stretched noise.
    if weight is not None and weight.shape == data.shape:
        data = np.where(np.asarray(weight) > 0, data, np.nan)

    header = read_image_header(reference)
    wcs = dict(header.get('wcs') or {}) if header.get('wcs') else None
    data, wcs, _bin = _bin_for_preview(data, wcs, max_dim)
    stretched = _asinh_stretch(data)
    oriented, wcs = apply_north_up_east_left(stretched, wcs)
    ny, nx = int(oriented.shape[0]), int(oriented.shape[1])
    scale = min(1.0, float(max_dim) / float(max(nx, ny)))
    out_w = max(1, int(round(nx * scale)))
    out_h = max(1, int(round(ny * scale)))
    image = Image.fromarray(np.asarray(oriented), mode='L')
    if (out_w, out_h) != (nx, ny):
        resample = getattr(Image, 'Resampling', Image).LANCZOS if hasattr(Image, 'Resampling') else getattr(Image, 'LANCZOS', 1)
        image = image.resize((out_w, out_h), resample)
    image = image.transpose(getattr(Image, 'FLIP_TOP_BOTTOM', 1))
    status_dir(base_dir).mkdir(parents=True, exist_ok=True)
    paths = _save_formats(image, base_dir, image_id)
    static_urls = _publish_static(paths, base_dir, image_id)
    phot = discover_phot_files(base_dir)
    if wcs:
        wcs = dict(wcs)
        wcs['nx'] = int(nx)
        wcs['ny'] = int(ny)
    primary = paths.get('webp') or paths.get('jpeg')
    meta = {
        'image_id': image_id,
        'source': str(reference),
        'source_mtime': reference.stat().st_mtime,
        'png': str(primary),
        'image': str(primary),
        'files': {kind: str(path) for kind, path in paths.items()},
        'static_urls': static_urls,
        'format': 'webp',
        'max_dim': int(max_dim),
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


def choose_preview_file(meta: dict[str, Any], accept: str = '') -> tuple[Path | None, str, str | None]:
    """Pick best on-disk preview and optional static URL from an Accept header."""
    accept = (accept or '').lower()
    files = meta.get('files') or {}
    static = meta.get('static_urls') or {}
    order = []
    if 'image/avif' in accept and files.get('avif'):
        order.append('avif')
    if 'image/webp' in accept and files.get('webp'):
        order.append('webp')
    order.extend(['webp', 'avif', 'jpeg'])
    seen: set[str] = set()
    for kind in order:
        if kind in seen:
            continue
        seen.add(kind)
        raw = files.get(kind)
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_file():
            continue
        ctype = {'webp': 'image/webp', 'avif': 'image/avif', 'jpeg': 'image/jpeg'}[kind]
        return path, ctype, static.get(kind)
    # Legacy single-path meta.
    legacy = Path(str(meta.get('image') or meta.get('png') or ''))
    if legacy.is_file():
        ctype = 'image/jpeg' if legacy.suffix.lower() in {'.jpg', '.jpeg'} else 'image/png'
        if legacy.suffix.lower() == '.webp':
            ctype = 'image/webp'
        if legacy.suffix.lower() == '.avif':
            ctype = 'image/avif'
        return legacy, ctype, None
    return None, '', None
