from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    external_id: str
    display_name: str
