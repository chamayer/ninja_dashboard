"""Companion data renders with Django's raw-cursor JSONB representation."""

import json
import uuid
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock

from apps.core.source_record_views import companion_details


class CompanionDetailsTests(TestCase):
    def test_json_text_and_decoded_objects_produce_the_same_display_fields(self):
        data = {
            "platform": "Ninja",
            "entity_type": "device.health",
            "health_status": "Healthy",
            "alert_count": 0,
            "reboot_required": False,
            "last_error": None,
            "nested": {"private": "detail"},
            "items": [1, 2],
        }
        for stored in (json.dumps(data), data, None):
            with self.subTest(representation=type(stored).__name__):
                cursor = Mock()
                cursor.fetchone.return_value = (True,)
                cursor.description = [
                    SimpleNamespace(name="external_namespace"),
                    SimpleNamespace(name="canonical_data"),
                ]
                cursor.fetchall.return_value = [("device-health", stored)]

                companions = companion_details(cursor, uuid.uuid4())

                expected_fields = (
                    [
                        ("Alert count", 0),
                        ("Health status", "Healthy"),
                        ("Last error", None),
                        ("Reboot required", False),
                    ]
                    if stored is not None
                    else []
                )
                self.assertEqual(
                    companions,
                    [{"external_namespace": "device-health", "fields": expected_fields}],
                )
