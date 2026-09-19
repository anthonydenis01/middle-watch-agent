from middlewatch.config import load_config
from middlewatch.engine import analyze
from middlewatch.loader import Container
from middlewatch.triage import annotate_all


def detect(records):
    """Wrap the original engine; thresholds, grouping and severity stay unchanged."""
    result = analyze('simulated', load_config(), keep_containers=False,
                     containers=(Container(record) for record in records))
    annotate_all(result.incidents)
    return result
