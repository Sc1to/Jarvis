"""Start a series on freshly loaded models when the last model call was for a different series.

Found on a real run: a model that stayed loaded between two series answered one series' request with the other
series' characters, from a clean prompt, with the other series idle. The same prompt on a freshly unloaded model was
right. The name of the series that last used the models is kept in `<data dir>/.last-series`, a file, so the service
and the command line share it and a restart does not forget it.
"""

import logging
from pathlib import Path

from . import model_admin
from .config import load_config

log = logging.getLogger("platform_bookforge.series_switch")

MARKER = ".last-series"


def flush_if_series_changed(series_root: Path) -> list[str]:
    """Unload the Ollama models this series uses if the last series to use them was another one.

    Returns the models unloaded (empty when nothing was needed). Never raises: a failed flush must not stop a run.
    With no marker file (first use) the models are unloaded too, since what they hold is unknown.
    """
    series_root = Path(series_root)
    marker = series_root.parent / MARKER
    name = series_root.name
    try:
        last = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    except OSError:
        last = None
    if last == name:
        return []
    unloaded: list[str] = []
    try:
        unloaded = model_admin.unload_all(load_config(series_root))
    except Exception:
        log.warning("could not unload models before starting series %s", name, exc_info=True)
    try:
        marker.write_text(name + "\n", encoding="utf-8")
    except OSError as e:
        log.warning("could not record the last series in %s: %s", marker, e)
    log.info("series %s follows %s: unloaded %s", name, last or "(unknown)", ", ".join(unloaded) or "no models")
    return unloaded
