"""Individual security checks. Each returns data plus a list of Findings."""

from dataclasses import asdict, dataclass

# Points subtracted from the 100-point safety score per severity.
PENALTY = {"critical": 100, "high": 25, "medium": 10, "low": 4, "info": 0, "good": 0}

DEAD_ADDRESSES = {
    "0x0000000000000000000000000000000000000000",
    "0x000000000000000000000000000000000000dead",
}


@dataclass
class Finding:
    severity: str  # critical | high | medium | low | info | good
    code: str
    message: str  # Turkish, shown to the user

    @property
    def penalty(self) -> int:
        return PENALTY[self.severity]

    def to_dict(self) -> dict:
        return asdict(self)
