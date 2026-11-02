"""Issue review explains decisions using safe current records and recorded evidence."""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from django.http import HttpResponse
from django.template.loader import get_template
from django.test import RequestFactory, SimpleTestCase

from apps.core import finding_review as review_module
from apps.core import views

CURRENT = str(uuid.UUID(int=1))
PROPOSED = str(uuid.UUID(int=2))
SUBJECT = uuid.UUID(int=3)


def finding(name="source_record_identity_review", **overrides):
    values = {
        "id": uuid.UUID(int=4),
        "subject_id": SUBJECT,
        "subject_type": "source_record",
        "client": None,
        "status": "open",
        "finding_type": SimpleNamespace(
            name=name, display_name="Review source identity", description=""
        ),
        "finding_details": {
            "evidence": {"device_id": CURRENT, "proposed_device_id": PROPOSED, "matcher": "serial"}
        },
        "first_seen_at": datetime(2026, 11, 1, tzinfo=UTC),
        "last_detected_at": datetime(2026, 11, 2, tzinfo=UTC),
        "get_subject_type_display": lambda: "Source record",
        "get_severity_display": lambda: "Critical",
        "get_status_display": lambda: "Open",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def user(permitted=False):
    return SimpleNamespace(
        is_authenticated=True, is_superuser=permitted, has_perm=lambda _p: permitted
    )


def subject(**overrides):
    values = {
        "reported_name": "Example workstation",
        "restricted": False,
        "device_id": CURRENT,
        "platform": "Example source",
        "entity_type": "agent.rmm",
        "canonical_serial": "EXAMPLE-123",
        "vm_uuid": None,
        "presence": "present",
    }
    values.update(overrides)
    return values


class IssueReviewTests(SimpleTestCase):
    def source_context(self, issue=None, record=None):
        with (
            patch.object(review_module, "connection"),
            patch.object(review_module, "load_subject", return_value=record or subject()),
            patch.object(review_module, "_comparison_computers", return_value=[]) as compare,
        ):
            result = review_module.review_context(issue or finding(), user(), tenant_id=7)
        return result, compare

    def test_contradicted_attachment_explains_the_proposed_computer(self):
        result, compare = self.source_context()
        self.assertIn("different Computer", result["summary"])
        self.assertNotIn("more than one", result["summary"])
        self.assertEqual(result["subject_label"], "Example workstation")
        self.assertIn(str(SUBJECT), result["subject_url"])
        self.assertIn({"label": "Match at detection", "value": "Serial number"}, result["facts"])
        roles, _, tenant = compare.call_args.args
        self.assertEqual(tenant, 7)
        self.assertIn("Attached now", roles[CURRENT])
        self.assertIn("Matched at detection", roles[PROPOSED])
        self.assertEqual(result["actions"], [])
        self.assertTrue(any("no move or merge action" in step for step in result["steps"]))

    def test_changed_and_removed_attachments_are_marked_as_current(self):
        for current in (PROPOSED, None):
            with self.subTest(current=current):
                result, _ = self.source_context(record=subject(device_id=current))
                self.assertTrue(result["attachment_changed"])
                self.assertEqual(result["currently_unattached"], current is None)

    def test_ambiguous_candidates_and_invalid_ids_are_bounded(self):
        candidates = {str(uuid.UUID(int=i)): ["serial"] for i in range(1, 30)}
        candidates["invalid-id"] = ["mac"]
        issue = finding(finding_details={"evidence": {"candidates": candidates}})
        result, compare = self.source_context(issue)
        self.assertIn("more than one", result["summary"])
        self.assertTrue(result["comparison_limited"])
        self.assertLessEqual(len(compare.call_args.args[0]), review_module.MAX_COMPUTERS)
        self.assertNotIn("invalid-id", compare.call_args.args[0])

    def test_empty_evidence_does_not_invent_candidates(self):
        result, _ = self.source_context(finding(finding_details={}))
        self.assertIn("no candidate comparison", result["summary"])

    def test_raw_json_text_is_decoded_for_native_findings(self):
        issue = finding()
        issue.finding_details = json.dumps(issue.finding_details)
        result, _ = self.source_context(issue)
        self.assertIn("different Computer", result["summary"])

    def test_restricted_or_missing_metadata_does_not_reveal_snapshot_names(self):
        for record in (subject(restricted=True), subject(restricted=None), None):
            with (
                self.subTest(record=record),
                patch.object(review_module, "connection"),
                patch.object(review_module, "load_subject", return_value=record),
                patch.object(review_module, "_comparison_computers") as compare,
            ):
                issue = finding(
                    finding_details={
                        "name": "PRIVATE SNAPSHOT",
                        "platform": "PRIVATE SOURCE",
                        "evidence": {"device_id": CURRENT},
                    }
                )
                result = review_module.review_context(issue, user(), tenant_id=7)
                self.assertTrue(result["record_limited"])
                self.assertEqual(result["facts"], [])
                self.assertNotIn("PRIVATE", str(result))
                compare.assert_not_called()

    def test_comparison_hides_restricted_record_names_and_identifiers(self):
        device = SimpleNamespace(
            id=uuid.UUID(CURRENT),
            canonical_hostname="Example Computer",
            client=SimpleNamespace(slug="example"),
        )
        record = {
            "device_id": CURRENT,
            "id": SUBJECT,
            "reported_name": "PRIVATE NAME",
            "canonical_serial": "PRIVATE SERIAL",
            "vm_uuid": "PRIVATE VM",
            "platform": "Example",
            "restricted": True,
            "presence": "present",
        }
        with (
            patch.object(review_module.Device.objects, "filter") as query,
            patch.object(review_module, "connection") as cursor,
            patch.object(review_module, "_rows", return_value=[record]),
        ):
            query.return_value.select_related.return_value = [device]
            result = review_module._comparison_computers({CURRENT: ["Attached now"]}, {}, 7)
            query.assert_called_once_with(tenant_id=7, id__in=[CURRENT], deleted_at__isnull=True)
            sql, params = cursor.cursor.return_value.__enter__.return_value.execute.call_args.args
            self.assertIn("v_entity_observation_admin_metadata", sql)
            self.assertEqual(params, (7, [CURRENT], review_module.MAX_RECORDS + 1))
        self.assertNotIn("PRIVATE", str(result))

    def test_missing_computer_is_retained_as_an_explicit_unavailable_comparison(self):
        with (
            patch.object(review_module.Device.objects, "filter") as query,
            patch.object(review_module, "connection"),
            patch.object(review_module, "_rows", return_value=[]),
        ):
            query.return_value.select_related.return_value = []
            result = review_module._comparison_computers(
                {CURRENT: ["Attached at detection"]}, {}, 1
            )
        self.assertEqual(result[0]["label"], "Computer no longer available")
        self.assertEqual(result[0]["url"], "")

    def test_actions_follow_existing_permissions_and_issue_status(self):
        for permitted, status in ((False, "open"), (True, "resolved"), (True, "open")):
            issue = finding("two_machines_on_one_computer", subject_type="device", status=status)
            result = review_module.review_context(issue, user(permitted), tenant_id=1)
            keys = [action.key for action in result["actions"]]
            self.assertEqual("split_computer_records" in keys, permitted and status == "open")

    def test_case_subject_has_an_investigation_destination(self):
        result = review_module.review_context(
            finding("source_record_duplicate_review", subject_type="source_record_case"),
            user(),
            tenant_id=1,
        )
        self.assertIn(f"/cases/{SUBJECT}/", result["subject_url"])
        self.assertTrue(result["steps"])

    def test_native_request_renders_evidence_and_preserves_a_safe_return_url(self):
        issue = finding()
        review, _ = self.source_context(issue)
        request = RequestFactory().get(
            f"/findings/{issue.id}/review/", {"return": "/findings/?view=flat&page=2"}
        )
        request.user = user()

        def render(_request, name, context):
            return HttpResponse(get_template(name).render({**context, "request": request}))

        with (
            patch.object(views, "get_object_or_404", return_value=issue),
            patch.object(review_module, "review_context", return_value=review),
            patch.object(views, "_os_installation_disagreements", return_value=[]),
            patch.object(views, "render", side_effect=render),
        ):
            response = views.finding_review(request, issue.id)
        html = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Strong identity evidence", html)
        self.assertIn("EXAMPLE-123", html)
        self.assertIn("How to handle this issue", html)
        self.assertIn("/findings/?view=flat&amp;page=2", html)
        self.assertNotIn("Check source health", html)
        self.assertNotIn("Review the linked records", html)
        self.assertTrue(
            views._issues_return_url("https://untrusted.example/").startswith("/findings/")
        )

    def test_template_escapes_evidence_and_posts_only_the_current_issue(self):
        issue = finding("two_machines_on_one_computer", subject_type="device")
        review = review_module.review_context(issue, user(True), tenant_id=1)
        review["facts"] = [{"label": "Reported value", "value": "<script>bad()</script>"}]
        html = get_template("finding_review.html").render({"finding": issue, "review": review})
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        self.assertNotIn("<script>bad()</script>", html)
        self.assertIn(f'name="ids" value="{issue.id}"', html)
        self.assertIn('name="reason" maxlength="400" required', html)
        self.assertIn("return confirm(", html)
        self.assertIn('value="split_computer_records"', html)

    def test_existing_os_disagreements_remain_visible(self):
        html = get_template("finding_review.html").render(
            {
                "finding": finding(),
                "review": {"steps": []},
                "os_disagreements": [
                    {
                        "installation": "example-installation",
                        "computers": [
                            {"label": "Example Computer", "url": "/example/", "shown": True}
                        ],
                    }
                ],
            }
        )
        self.assertIn("Sources disagree about the operating system", html)
        self.assertIn("Example Computer", html)

    def test_comparison_renders_current_records_and_recorded_roles(self):
        review, _ = self.source_context()
        review["computers"] = [
            {
                "label": "Example Computer",
                "url": "/orgs/example/computers/example/",
                "roles": ["Matched at detection"],
                "families": ["Serial number"],
                "records": [
                    {
                        "label": "Example agent",
                        "url": "/record/",
                        "platform": "Example source",
                        "serial": "EXAMPLE-123",
                        "presence": "present",
                    }
                ],
            }
        ]
        html = get_template("finding_review.html").render({"finding": finding(), "review": review})
        self.assertIn("Compare the Computers", html)
        self.assertIn("Matched at detection", html)
        self.assertIn("Example agent", html)
        self.assertIn("?tab=details#source-records", html)
