from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def parse_ran_at_kst(ran_at: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(ran_at[:19], fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None
