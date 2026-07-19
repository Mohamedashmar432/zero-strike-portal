from datetime import datetime, timezone


def as_utc(dt: datetime | None) -> datetime | None:
    """Motor/pymongo returns naive datetimes by default (the client isn't configured with
    tz_aware=True), even though Mongo stores them as UTC. Without this, FastAPI serializes them
    with no offset/`Z` suffix and a JS `Date` misparses the string as local time. Tag any
    Mongo-read datetime with UTC before it goes into a response. Idempotent for aware datetimes.
    """
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)
