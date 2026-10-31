import json
from pathlib import Path
from urllib.request import urlopen


BASE_URL = "http://127.0.0.1:18865"
FEED = Path(__file__).parent / (
    "web_overrides/web/json/announcement/announcement.json"
)
REQUIRED_FIELDS = {
    "announcementType",
    "createdAt",
    "displayOs",
    "endAt",
    "hiddenUnderMaintenance",
    "id",
    "important",
    "sortKey",
    "startAt",
    "status",
    "subject",
    "text",
}


def main():
    rows = json.loads(FEED.read_text(encoding="utf-8"))
    assert isinstance(rows, list)
    assert len(rows) >= 2600
    assert REQUIRED_FIELDS.issubset(rows[0])
    assert max(row["startAt"] for row in rows) >= "2026-12-01"

    with urlopen(
        BASE_URL + "/web/json/announcement/announcement.json",
        timeout=10,
    ) as response:
        assert response.status == 200
        served = json.loads(response.read().decode("utf-8"))
    assert served == rows

    print(
        "Announcement feed: local file and HTTP route contain "
        f"{len(rows)} structured entries: PASS"
    )


if __name__ == "__main__":
    main()
