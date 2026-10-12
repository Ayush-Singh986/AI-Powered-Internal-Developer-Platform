import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services"))


_loaded = {}


def load(service: str):
    """Load services/<service>/app/main.py once, under a unique module name."""
    if service in _loaded:
        return _loaded[service]
    path = ROOT / "services" / service / "app" / "main.py"
    spec = importlib.util.spec_from_file_location(service.replace("-", "_"), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _loaded[service] = mod
    return mod
