from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo


class FileNameInputError(ValueError):
    pass


def normalize_file_name_base(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.strip())
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", ascii_name).strip("-_")
    if not slug:
        raise FileNameInputError(
            "Der Dateiname muss mindestens einen Buchstaben oder eine Zahl enthalten."
        )
    return slug[:128]


def recording_file_name(
    file_name_base: str,
    extension: str,
    timezone: str,
    *,
    now: datetime | None = None,
    token: str | None = None,
) -> str:
    normalized_base = normalize_file_name_base(file_name_base)
    timestamp = (now or datetime.now(ZoneInfo(timezone))).strftime("%Y-%m-%d_%H-%M-%S")
    unique_token = token or secrets.token_hex(3)
    return f"{timestamp}_{normalized_base}_{unique_token}{extension}"
