from apps.core.views import _change_history_events


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *args):
        pass

    def fetchall(self):
        return self.rows


def test_change_history_survives_string_encoded_values():
    row = (
        "2026-10-22T10:00:00Z",
        "computers",
        "k",
        "U",
        ["hostname"],
        '{"hostname": "old"}',
        '"new"',
        "a1",
        "implicit",
        "platform",
        None,
        "sync",
        None,
    )
    events = _change_history_events(_Cursor([row]), [], None, {})
    assert events[0]["changes"] == ["computers changed (hostname) — hostname: old → None"]
