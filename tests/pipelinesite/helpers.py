from pathlib import Path


def write_phot(path: Path, rows):
    lines = []
    for x, y, snr, sharp, crowd, obj_type in rows:
        cols = ['0'] * 11
        cols[2] = str(x)
        cols[3] = str(y)
        cols[5] = str(snr)
        cols[6] = str(sharp)
        cols[9] = str(crowd)
        cols[10] = str(obj_type)
        lines.append(' '.join(cols))
    path.write_text('\n'.join(lines) + '\n')
