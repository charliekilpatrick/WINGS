"""Write a compact HDF5 sidecar from a DOLPHOT ``.phot`` catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import status_dir


def existing_hdf5_for_phot(phot: Path, base_dir: Path | None = None) -> Path | None:
    sibling = phot.with_suffix('.h5')
    if sibling.is_file() and sibling.stat().st_size > 0:
        return sibling
    if base_dir is not None:
        from .inventory import discover_hdf5_files

        stem = phot.stem
        for path in discover_hdf5_files(base_dir):
            if path.stem == stem or path.name.startswith(stem):
                return path
    return None


def catalog_hdf5_path(phot: Path, base_dir: Path | None = None) -> Path:
    found = existing_hdf5_for_phot(phot, base_dir)
    if found is not None:
        return found
    root = Path(base_dir) if base_dir is not None else phot.parent
    return status_dir(root) / f'{phot.stem}.h5'


def ensure_catalog_hdf5(
    phot: Path,
    *,
    base_dir: Path | None = None,
    reference: Path | None = None,
    wcs: dict[str, Any] | None = None,
    header: dict[str, Any] | None = None,
) -> Path:
    dest = catalog_hdf5_path(phot, base_dir)
    existing = existing_hdf5_for_phot(phot, base_dir)
    if existing is not None:
        return existing
    dest.parent.mkdir(parents=True, exist_ok=True)
    from .inventory import catalog_sources

    sources = catalog_sources(
        phot,
        reference=reference,
        wcs=wcs,
        header=header,
        base_dir=base_dir,
    )
    _write_sources_hdf5(dest, phot, sources)
    return dest


def _write_sources_hdf5(dest: Path, phot: Path, sources: list[dict[str, Any]]) -> None:
    import numpy as np
    import h5py

    names = []
    for src in sources:
        for row in src.get('mags') or []:
            name = row.get('name')
            if name and name not in names:
                names.append(name)

    def col(key, dtype=float, default=np.nan):
        out = []
        for src in sources:
            value = src.get(key)
            out.append(default if value is None else value)
        return np.asarray(out, dtype=dtype)

    with h5py.File(dest, 'w') as handle:
        handle.attrs['source'] = str(phot)
        handle.attrs['n'] = len(sources)
        grp = handle.create_group('sources')
        grp.create_dataset('index', data=col('index', int, 0), compression='gzip')
        grp.create_dataset('x', data=col('x'), compression='gzip')
        grp.create_dataset('y', data=col('y'), compression='gzip')
        grp.create_dataset('ra', data=col('ra'), compression='gzip')
        grp.create_dataset('dec', data=col('dec'), compression='gzip')
        grp.create_dataset('snr', data=col('snr'), compression='gzip')
        grp.create_dataset('sharp', data=col('sharp'), compression='gzip')
        grp.create_dataset('crowd', data=col('crowd'), compression='gzip')
        grp.create_dataset('chi', data=col('chi'), compression='gzip')
        grp.create_dataset('roundness', data=col('roundness'), compression='gzip')
        grp.create_dataset('type', data=col('type', int, 0), compression='gzip')
        grp.create_dataset(
            'passed',
            data=np.asarray([1 if src.get('passed') else 0 for src in sources], dtype=np.uint8),
            compression='gzip',
        )
        for name in names:
            mag = []
            magerr = []
            for src in sources:
                match = next((row for row in (src.get('mags') or []) if row.get('name') == name), None)
                mag.append(np.nan if match is None or match.get('mag') is None else match['mag'])
                magerr.append(
                    np.nan if match is None or match.get('magerr') is None else match['magerr']
                )
            safe = ''.join(ch if ch.isalnum() else '_' for ch in name)
            grp.create_dataset(f'mag_{safe}', data=np.asarray(mag, dtype=float), compression='gzip')
            grp.create_dataset(
                f'magerr_{safe}',
                data=np.asarray(magerr, dtype=float),
                compression='gzip',
            )
