import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
for _path in (_ROOT / 'wings/src/pipelinesite', _ROOT / 'wings/src', _ROOT):
    _text = str(_path)
    if _text not in sys.path:
        sys.path.insert(0, _text)
