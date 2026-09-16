from typing import Protocol


class TrackingProvider(Protocol):
    def journey(self, number: str) -> dict: ...
