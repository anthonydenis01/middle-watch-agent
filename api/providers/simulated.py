import hashlib
import random
from datetime import datetime, timezone
from data.generate import generate_record
from api.services.validation import check_digit

SNAPSHOT = datetime(2026, 8, 3, 6, tzinfo=timezone.utc)
SAMPLE_NUMBERS = [f'MWSU{i:06d}{check_digit(f"MWSU{i:06d}")}' for i in range(1, 26)]


class SimulatedProvider:
    """Same number, same synthetic journey. Never performs network I/O."""
    def journey(self, number):
        rng = random.Random(int.from_bytes(hashlib.sha256(number.encode('ascii')).digest(), 'big'))
        account = {'account_id': 'SYNTHETIC', 'account_name': 'Synthetic account',
                   'account_tier': 'standard', 'service_contract': 'SYNTHETIC'}
        raw, _ = generate_record(rng, [account], SNAPSHOT, {
            'routing_change': .08, 'vessel_swap': .08, 'dwell': .12,
            'eta_drift': .12, 'transit_time': .06}, False)
        raw['container_id'] = number
        return raw
