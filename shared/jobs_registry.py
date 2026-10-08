"""Declarative metadata shared by Operations and ingest Jobs consumers.

This module deliberately imports only the standard library.  It describes the
current durable operator-queue definitions; it does not import handlers,
connect to Postgres, choose resource capacity, or make an unconverted legacy
path safe to execute.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Iterable, Mapping


class RegistryValidationError(ValueError):
    """Raised when a consumer does not exactly match the shared registry."""


@dataclass(frozen=True)
class ScheduleDefinition:
    """Durable cadence identity; the ingest runtime resolves its setting value."""

    schedule_id: str
    job_key: str
    cadence_setting: str
    cadence_unit: str = "hours"


@dataclass(frozen=True)
class DependencyDefinition:
    """One declared successor contract for a published prerequisite revision."""

    successor: str
    revision_name: str
    condition: str = "always"
    scope_mode: str = "inherit"
    coalescing: str = "definition_scope"
    failure_rule: str = "block"

    def snapshot(self) -> dict[str, str]:
        return {
            "successor": self.successor,
            "revision_name": self.revision_name,
            "condition": self.condition,
            "scope_mode": self.scope_mode,
            "coalescing": self.coalescing,
            "failure_rule": self.failure_rule,
        }


@dataclass(frozen=True)
class WorkflowEdge:
    prerequisite: str
    dependent: str
    revision_name: str
    condition: str
    scope_mode: str
    coalescing: str
    failure_rule: str


@dataclass(frozen=True)
class OperatorJobDefinition:
    """One Job shown to an administrator.

    ``execution_keys`` exists only to preserve compatible historical and mode
    keys while the product presents one Job. System services never appear in
    this catalog.
    """

    key: str
    group_key: str
    name: str
    description: str
    start_description: str
    primary_execution_key: str
    execution_keys: tuple[str, ...]


@dataclass(frozen=True)
class JobDefinition:
    """Presentation and current execution metadata for one Jobs definition.

    Resource and supersession metadata records the approved conservative
    Step 2.3 baseline. It applies only when a definition is converted to the
    constrained Jobs APIs; legacy version-0 writers remain compatibility paths.
    Retry and cancellation fields remain unreviewed.
    """

    key: str
    display_name: str
    description: str
    category: str
    lane: str
    endpoint: str
    status_key: str
    status_source: str
    owner: str
    capability: str = "always"
    run_all: bool = True
    legacy_bridge: bool = False
    schedule_ids: tuple[str, ...] = ()
    capacity_keys: tuple[str, ...] = ()
    resource_keys: tuple[str, ...] = ()
    supersession_family: str = ""
    supersession_rank: int = 0
    handler_version: str = "registry-v1"
    timeout_minutes: int = 90
    priority: int = 50
    coalescing_scope: str = "definition_scope"
    concurrency_scope: str = "resource_keys"
    retry_policy: str = "manual_only_unreviewed"
    progress_contract: str = "stage"
    result_contract: str = "rows_or_outcome"
    permission: str = "administrator"
    kill_safe: bool = False
    successors: tuple[DependencyDefinition, ...] = ()

    def catalog_entry(self) -> dict[str, object]:
        """Return the stable operator-facing shape used by the current UI."""
        entry: dict[str, object] = {
            "id": self.key,
            "name": self.display_name,
            "category": self.category,
            "endpoint": self.endpoint,
            "status_key": self.status_key,
            "status_source": self.status_source,
            "description": self.description,
        }
        if not self.run_all:
            entry["run_all"] = False
        if self.legacy_bridge:
            entry["legacy_bridge"] = True
        return entry

    def snapshot_metadata(self) -> dict[str, object]:
        """Return credential-free immutable metadata for the Jobs ledger."""
        return {
            "key": self.key,
            "lane": self.lane,
            "owner": self.owner,
            "capability": self.capability,
            "capacity_keys": list(self.capacity_keys),
            "resource_keys": list(self.resource_keys),
            "supersession_family": self.supersession_family,
            "supersession_rank": self.supersession_rank,
            "timeout_minutes": self.timeout_minutes,
            "priority": self.priority,
            "coalescing_scope": self.coalescing_scope,
            "concurrency_scope": self.concurrency_scope,
            "retry_policy": self.retry_policy,
            "recovery_mode": _RECOVERY_MODE_BY_DEFINITION[self.key],
            "progress_contract": self.progress_contract,
            "result_contract": self.result_contract,
            "permission": self.permission,
            "successors": [successor.snapshot() for successor in self.successors],
        }

    def snapshot_digest(self) -> str:
        encoded = json.dumps(
            self.snapshot_metadata(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


_RAW_DEFINITIONS = (
    JobDefinition(
        "source-refresh",
        "Source refresh",
        "Collect current data from one configured source.",
        "source ingest",
        "collection",
        "",
        "source.refresh",
        "run_log_like",
        "ingest.operator_job_queue._run_source_refresh",
        run_all=False,
        handler_version="source-refresh-v1",
    ),
    JobDefinition(
        "patches",
        "Ninja source cycle",
        "Refresh computers, patches, and activity from Ninja.",
        "source ingest",
        "collection",
        "run/patches",
        "source.Ninja",
        "run_log_like",
        "ingest.main.run_patching_once",
    ),
    JobDefinition(
        "agent-observations",
        "Agent observations",
        "Refresh agent records from connected security and support tools.",
        "source ingest",
        "collection",
        "run/agents",
        "source.",
        "run_log_like",
        "ingest.main.run_agent_observations_once",
    ),
    JobDefinition(
        "documentation-observations",
        "Hudu records",
        "Refresh Hudu CMDB records.",
        "source ingest",
        "collection",
        "run/sources/enqueue",
        "source.Hudu",
        "run_log_like",
        "ingest.main.run_documentation_observations_once",
        run_all=False,
    ),
    JobDefinition(
        "software-classify",
        "Software classifier (+ auto-intel)",
        "Refresh software intelligence, then update software findings.",
        "evaluators",
        "software",
        "run/software-classify",
        "software_classifier",
        "run_log",
        "ingest.operator_job_queue._software_classify_with_intel",
    ),
    JobDefinition(
        "software-classify-only",
        "Software classifier (no intel refresh)",
        "Update changed software findings using intelligence already on hand.",
        "evaluators",
        "software",
        "run/software-classify-only",
        "software_classifier",
        "run_log",
        "ingest.software_findings.classify",
        run_all=False,
        schedule_ids=("software_classify_cycle",),
    ),
    JobDefinition(
        "software-classify-full",
        "Software classifier (full rebuild)",
        "Rebuild every software finding after a rule, decision, or intelligence-wide change.",
        "evaluators",
        "software",
        "",
        "software_classifier",
        "run_log",
        "ingest.software_findings.classify",
        run_all=False,
        schedule_ids=("software_classify_full_rebuild_cycle",),
    ),
    JobDefinition(
        "patch-classify",
        "Patch classifier",
        "Update patch findings from current Ninja patch data.",
        "evaluators",
        "evaluation",
        "run/patch-classify",
        "patch_findings",
        "run_log",
        "ingest.patch_findings.classify",
    ),
    JobDefinition(
        "platform-evaluate",
        "Platform evaluator",
        "Update computer, coverage, identity, and lifecycle findings.",
        "evaluators",
        "evaluation",
        "run/platform-evaluate",
        "platform_evaluator",
        "run_log",
        "ingest.evaluator.evaluate",
        schedule_ids=("platform_evaluate_cycle",),
    ),
    JobDefinition(
        "cmdb-evaluate",
        "CMDB evaluation",
        "Evaluate CMDB findings from completed documentation-source evidence.",
        "evaluation",
        "evaluation",
        "",
        "cmdb_findings",
        "run_log",
        "ingest.cmdb_findings.evaluate",
        run_all=False,
    ),
    JobDefinition(
        "resolver",
        "Identity resolver",
        "Match source records to the right computer.",
        "evaluators",
        "evaluation",
        "run/resolver",
        "identity_resolver",
        "run_log",
        "ingest.identity.resolver.drain_resolution",
        schedule_ids=("identity_resolver_cycle",),
    ),
    JobDefinition(
        "parity-check",
        "Parity check",
        "Find gaps between collected data and Operations.",
        "evaluators",
        "evaluation",
        "run/parity-check",
        "parity_check",
        "run_log",
        "ingest.parity_check.run",
    ),
    JobDefinition(
        "agent-compliance",
        "Agent compliance",
        "Refresh the legacy agent-compliance bridge when it is enabled.",
        "evaluators",
        "evaluation",
        "run/agent-compliance",
        "agent_compliance",
        "run_log",
        "ingest.agent_compliance.ingest.run",
        capability="legacy_agent_compliance",
        run_all=False,
        legacy_bridge=True,
        schedule_ids=("agent_compliance_ingest_cycle",),
    ),
    JobDefinition(
        "agent-compliance-evaluate",
        "Agent compliance review",
        "Reassess the legacy agent-compliance bridge when it is enabled.",
        "evaluators",
        "evaluation",
        "run/agent-compliance/evaluate",
        "agent_compliance.evaluate",
        "run_log",
        "ingest.agent_compliance.ingest.evaluate",
        capability="legacy_agent_compliance",
        run_all=False,
        legacy_bridge=True,
        schedule_ids=("agent_compliance_evaluate_cycle",),
    ),
    JobDefinition(
        "agent-compliance-review-digest",
        "Agent compliance review digest",
        "Send the enabled legacy agent-compliance review summary.",
        "notifications",
        "service",
        "run/agent-compliance-review-digest",
        "agent_compliance.review_digest",
        "run_log",
        "ingest.main.run_review_digest_once",
        capability="legacy_agent_compliance",
        run_all=False,
        legacy_bridge=True,
    ),
    JobDefinition(
        "intel-kev",
        "Intel: CISA KEV",
        "Refresh CISA's list of actively exploited vulnerabilities.",
        "intel",
        "intelligence",
        "run/intel-kev",
        "cisa_kev",
        "intel",
        "ingest.intel.cisa_kev.run_once",
        capability="intel",
        schedule_ids=("intel_kev_cycle",),
    ),
    JobDefinition(
        "intel-nvd",
        "Intel: NVD (CVE feed)",
        "Refresh vulnerability details from NIST's NVD.",
        "intel",
        "intelligence",
        "run/intel-nvd",
        "nvd",
        "intel",
        "ingest.intel.nvd.run_once",
        capability="intel",
        schedule_ids=("intel_nvd_cycle",),
    ),
    JobDefinition(
        "intel-cpe-dict",
        "Intel: CPE dictionary",
        "Refresh the software identification catalog used for CVE matching.",
        "intel",
        "intelligence",
        "run/intel-cpe-dict",
        "cpe_dict",
        "intel",
        "ingest.intel.cpe_dict.run_once",
        capability="intel",
        schedule_ids=("intel_cpe_dict_cycle",),
    ),
    JobDefinition(
        "intel-epss",
        "Intel: EPSS scores",
        "Refresh exploit-likelihood scores from EPSS.",
        "intel",
        "intelligence",
        "run/intel-epss",
        "epss",
        "intel",
        "ingest.intel.epss.run_once",
        capability="intel",
        schedule_ids=("intel_epss_cycle",),
    ),
    JobDefinition(
        "intel-matcher",
        "Intel: title × CVE matcher",
        "Match installed software to known vulnerabilities.",
        "intel",
        "intelligence",
        "run/intel-matcher",
        "matcher",
        "intel",
        "ingest.intel.matcher.run_once",
        capability="intel",
        schedule_ids=("intel_matcher_cycle",),
    ),
    JobDefinition(
        "intel-winget",
        "Intel: Winget enrichment",
        "Improve software records from Windows Package Manager.",
        "intel",
        "intelligence",
        "run/intel-winget",
        "winget",
        "intel",
        "ingest.intel.winget.run_once",
        capability="intel",
        schedule_ids=("intel_winget_cycle",),
    ),
    JobDefinition(
        "intel-chocolatey",
        "Intel: Chocolatey enrichment",
        "Improve software records from Chocolatey.",
        "intel",
        "intelligence",
        "run/intel-chocolatey",
        "chocolatey",
        "intel",
        "ingest.intel.chocolatey.run_once",
        capability="intel",
        schedule_ids=("intel_chocolatey_cycle",),
    ),
    JobDefinition(
        "intel-capability",
        "Intel: capability projection",
        "Update known software capabilities from catalog rules.",
        "intel",
        "intelligence",
        "run/intel-capability",
        "capability_match",
        "intel",
        "ingest.intel.capability_match.run_once",
        capability="intel",
        schedule_ids=("intel_capability_cycle",),
    ),
    JobDefinition(
        "intel-lolrmm",
        "Intel: LOLRMM corpus",
        "Refresh remote-management tool detection data.",
        "intel",
        "intelligence",
        "run/intel-lolrmm",
        "lolrmm",
        "intel",
        "ingest.intel.lolrmm.run_once",
        capability="intel",
        schedule_ids=("intel_lolrmm_cycle",),
    ),
    JobDefinition(
        "intel-otx",
        "Intel: AlienVault OTX",
        "Refresh threat intelligence from AlienVault OTX.",
        "intel",
        "intelligence",
        "run/intel-otx",
        "otx",
        "intel",
        "ingest.intel.otx.run_once",
        capability="intel",
        schedule_ids=("intel_otx_cycle",),
    ),
    JobDefinition(
        "intel-abusech",
        "Intel: abuse.ch",
        "Refresh malware intelligence from MalwareBazaar and ThreatFox.",
        "intel",
        "intelligence",
        "run/intel-abusech",
        "abusech",
        "intel",
        "ingest.intel.abusech.run_once",
        capability="intel",
        schedule_ids=("intel_abusech_cycle",),
    ),
    JobDefinition(
        "intel-endoflife",
        "Intel: end-of-life",
        "Refresh software support dates from endoflife.date.",
        "intel",
        "intelligence",
        "run/intel-endoflife",
        "endoflife",
        "intel",
        "ingest.main.run_intel_endoflife_once",
        capability="intel",
        schedule_ids=("intel_endoflife_cycle",),
    ),
    JobDefinition(
        "intel-category",
        "Intel: software categories",
        "Update software categories from catalog data.",
        "intel",
        "intelligence",
        "run/intel-category",
        "category_match",
        "intel",
        "ingest.intel.category_match.run_once",
        capability="intel",
        schedule_ids=("intel_category_cycle",),
    ),
    JobDefinition(
        "notifications-dispatch",
        "Notifications dispatch",
        "Send notifications that are ready to go out.",
        "notifications",
        "service",
        "run/notifications/dispatch",
        "notifications_dispatch",
        "run_log",
        "ingest.notifications.dispatch",
        capability="notifications",
        schedule_ids=("notifications_dispatch_cycle",),
    ),
    JobDefinition(
        "notifications-digest",
        "Notifications digest",
        "Send scheduled notification summaries.",
        "notifications",
        "service",
        "run/notifications/digest",
        "notifications_digest",
        "run_log",
        "ingest.notifications_digest.send_digest",
        capability="notification_digest",
        schedule_ids=("notifications_digest_cycle",),
    ),
    JobDefinition(
        "retention-history",
        "History cleanup",
        "Remove closed history that has reached its retention date.",
        "maintenance",
        "service",
        "",
        "retention.observation_history",
        "run_log",
        "ingest.retention_observations.purge_all",
        run_all=False,
        schedule_ids=("observation_history_retention_cycle",),
    ),
    JobDefinition(
        "software-enqueue-orgs",
        "Software inventory schedule",
        "Queue the next scheduled Ninja software inventory sweep.",
        "maintenance",
        "service",
        "",
        "",
        "run_log",
        "ingest.inventory.queue.enqueue_scheduled",
        capability="software_queue",
        run_all=False,
        schedule_ids=("software_enqueue_orgs_cycle",),
    ),
    JobDefinition(
        "software-queue-drain",
        "Software inventory worker",
        "Process queued Ninja software inventory work.",
        "maintenance",
        "collection",
        "",
        "",
        "run_log",
        "ingest.inventory.queue.drain_background",
        capability="software_queue",
        run_all=False,
        schedule_ids=("software_queue_drain_cycle",),
    ),
    JobDefinition(
        "source-actions",
        "Source actions worker",
        "Process approved external source actions with their retained audit records.",
        "maintenance",
        "service",
        "",
        "source_action_requests",
        "run_log",
        "ingest.source_actions.process_pending",
        run_all=False,
        schedule_ids=("source_action_requests_cycle",),
    ),
    JobDefinition(
        "run-log-recovery",
        "Diagnostic run recovery",
        "Close stale diagnostic run records that no active process can complete.",
        "maintenance",
        "service",
        "",
        "run_log",
        "run_log",
        "ingest.runlog.reap_stale",
        run_all=False,
        schedule_ids=("run_log_recovery_cycle",),
    ),
    JobDefinition(
        "platform-health-evaluate",
        "Platform health evaluator",
        "Evaluate source failures and queue thresholds for Admin Health.",
        "maintenance",
        "service",
        "",
        "platform_findings",
        "run_log",
        "ingest.platform_findings.evaluate",
        run_all=False,
        schedule_ids=("platform_health_evaluate_cycle",),
    ),
    JobDefinition(
        "metabase-bootstrap",
        "Metabase dashboard bootstrap",
        "Provision the configured Metabase dashboards after service startup or an explicit request.",
        "maintenance",
        "service",
        "",
        "metabase_bootstrap",
        "run_log",
        "ingest.main.bootstrap_metabase",
        capability="metabase_bootstrap",
        run_all=False,
    ),
)

# Recovery policy is deliberately separate from execution snapshots: it is an
# audited statement about replay after an interrupted run, not permission to
# change the historical definition that admitted that run.
REPLAY_SAFE_RECOVERY_EVIDENCE = MappingProxyType(
    {
        "source-refresh": (
            "A source refresh only reads the configured source API and reconciles local "
            "evidence. Replaying it converges to current source data and performs no "
            "source-side mutation."
        ),
        "intel-matcher": (
            "The CVE matcher rebuilds local match rows in one database transaction and "
            "refreshes a local read model afterward. A later replay converges to current "
            "installed software and intelligence data and has no external mutation."
        ),
        "intel-endoflife": (
            "The end-of-life refresh only reads the public endoflife.date API and "
            "upserts local corpus rows. A later replay converges to current source data "
            "and has no external mutation."
        ),
        "intel-kev": (
            "The KEV refresh only performs a transaction-scoped conditional upsert "
            "of the public CISA exploited-vulnerability feed. A later replay converges "
            "to the current feed and has no external mutation."
        ),
        "intel-nvd": (
            "The NVD refresh only performs transaction-scoped conditional upserts "
            "of a public vulnerability feed. A later replay converges to the current "
            "feed and has no external mutation."
        ),
        "intel-cpe-dict": (
            "The CPE dictionary refresh only performs cursor-backed, transaction-scoped "
            "conditional upserts of a public feed. A later replay resumes or converges "
            "to the current dictionary and has no external mutation."
        ),
        "intel-otx": (
            "The AlienVault OTX refresh only reads the subscribed-pulse feed and performs "
            "transaction-scoped conditional upserts of local threat signals. A later replay "
            "converges to current feed state and has no external mutation."
        ),
        "intel-abusech": (
            "The abuse.ch refresh only reads public MalwareBazaar and ThreatFox feeds and "
            "performs transaction-scoped conditional upserts of local threat signals. A later "
            "replay converges to current feed state and has no external mutation."
        ),
        "intel-epss": (
            "The EPSS refresh only performs a transaction-scoped conditional update "
            "of existing CVE scores. A later replay converges to the current public "
            "EPSS feed and has no external mutation."
        ),
        "software-classify-only": (
            "Incremental software classification only reconciles Operations findings "
            "and exact-state markers in one database transaction. A later replay "
            "converges to the current installation and policy state and has no external mutation."
        ),
        "software-classify-full": (
            "Full software classification only reconciles Operations intelligence, "
            "findings, and a read model from current source data. A later replay "
            "converges to the current installation and policy state and has no external mutation."
        ),
        "patches": (
            "The Ninja collection cycle only reads the vendor API and reconciles local "
            "source projections from the current response. A later replay converges to "
            "current source state and has no vendor-side mutation."
        ),
        "agent-observations": (
            "Agent observation collection only reads connected source APIs and writes "
            "current local observations and derived projections. A later replay "
            "converges to current source state and has no source-side mutation."
        ),
        "documentation-observations": (
            "Documentation observation collection only reads CMDB source APIs and writes "
            "current local observations and derived projections. A later replay "
            "converges to current source state and has no source-side mutation."
        ),
    }
)

# Every definition has an explicit recovery posture. Only definitions with
# reviewed evidence may be replayed automatically; all others remain safely
# contained for administrator review after interruption.
_RECOVERY_MODE_BY_DEFINITION = MappingProxyType(
    {
        definition.key: (
            "replay_safe" if definition.key in REPLAY_SAFE_RECOVERY_EVIDENCE else "manual_review"
        )
        for definition in _RAW_DEFINITIONS
    }
)


_SCHEDULE_DEFINITIONS = (
    ScheduleDefinition("identity_resolver_cycle", "resolver", "constant:30", "minutes"),
    ScheduleDefinition("platform_evaluate_cycle", "platform-evaluate", "constant:4"),
    ScheduleDefinition(
        "software_classify_cycle", "software-classify-only", "SOFTWARE_CLASSIFY_SCHEDULE_HOURS"
    ),
    ScheduleDefinition(
        "software_classify_full_rebuild_cycle",
        "software-classify-full",
        "SOFTWARE_CLASSIFY_FULL_REBUILD_HOURS",
    ),
    ScheduleDefinition(
        "software_enqueue_orgs_cycle", "software-enqueue-orgs", "SOFTWARE_INGEST_SCHEDULE_HOURS"
    ),
    ScheduleDefinition(
        "software_queue_drain_cycle",
        "software-queue-drain",
        "SOFTWARE_QUEUE_POLL_MINUTES",
        "minutes",
    ),
    ScheduleDefinition("source_action_requests_cycle", "source-actions", "constant:1", "minutes"),
    ScheduleDefinition("run_log_recovery_cycle", "run-log-recovery", "constant:30", "minutes"),
    ScheduleDefinition(
        "platform_health_evaluate_cycle", "platform-health-evaluate", "constant:30", "minutes"
    ),
    ScheduleDefinition(
        "notifications_dispatch_cycle",
        "notifications-dispatch",
        "NOTIFY_DISPATCH_SCHEDULE_MINUTES",
        "minutes",
    ),
    ScheduleDefinition(
        "notifications_digest_cycle", "notifications-digest", "NOTIFY_DIGEST_HOUR", "cron-hour"
    ),
    ScheduleDefinition(
        "observation_history_retention_cycle",
        "retention-history",
        "OBSERVATION_HISTORY_RETENTION_HOUR",
        "cron-hour",
    ),
    ScheduleDefinition(
        "agent_compliance_ingest_cycle", "agent-compliance", "AGENT_COMPLIANCE_SCHEDULE_HOURS"
    ),
    ScheduleDefinition(
        "agent_compliance_evaluate_cycle",
        "agent-compliance-evaluate",
        "AGENT_COMPLIANCE_SCHEDULE_HOURS",
    ),
    ScheduleDefinition("intel_nvd_cycle", "intel-nvd", "INTEL_NVD_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_cpe_dict_cycle", "intel-cpe-dict", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_kev_cycle", "intel-kev", "INTEL_KEV_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_epss_cycle", "intel-epss", "INTEL_EPSS_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_matcher_cycle", "intel-matcher", "INTEL_MATCHER_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_winget_cycle", "intel-winget", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition(
        "intel_chocolatey_cycle", "intel-chocolatey", "INTEL_CATALOG_SCHEDULE_HOURS"
    ),
    ScheduleDefinition("intel_otx_cycle", "intel-otx", "INTEL_OSINT_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_abusech_cycle", "intel-abusech", "INTEL_OSINT_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_endoflife_cycle", "intel-endoflife", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition(
        "intel_capability_cycle", "intel-capability", "INTEL_CAPABILITY_SCHEDULE_HOURS"
    ),
    ScheduleDefinition("intel_category_cycle", "intel-category", "INTEL_CATEGORY_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_lolrmm_cycle", "intel-lolrmm", "INTEL_CATALOG_SCHEDULE_HOURS"),
)

EXECUTION_POOL_POLICIES = MappingProxyType(
    {
        "capacity:external-io": {
            "label": "Source connections",
            "capacity": 3,
            "minimum": 1,
            "maximum": 3,
        },
        "capacity:processing": {
            "label": "Data processing",
            "capacity": 2,
            "minimum": 1,
            "maximum": 2,
        },
        "capacity:control": {"label": "Control work", "capacity": 1, "minimum": 1, "maximum": 2},
    }
)
READY_WINDOW_CAPACITY = 2
# A fuse only: ordinary admission remains governed by the separate pools.
EMERGENCY_CHILD_CAPACITY = 5

_GLOBAL_ONLY = frozenset(
    {
        "intel-nvd",
        "intel-cpe-dict",
        "intel-kev",
        "intel-epss",
        "intel-capability",
        "intel-lolrmm",
        "intel-category",
    }
)
_RESOURCE_KEYS_BY_DEFINITION: dict[str, tuple[str, ...]] = {
    "source-refresh": ("tenant:{tenant_id}:source-binding:{scope_identity}",),
    "patches": ("tenant:{tenant_id}:ninja-source",),
    "agent-observations": ("tenant:{tenant_id}:agent-sources",),
    "documentation-observations": ("tenant:{tenant_id}:documentation-source",),
    "software-classify": ("tenant:{tenant_id}:software-state",),
    "software-classify-only": ("tenant:{tenant_id}:software-state",),
    "software-classify-full": ("tenant:{tenant_id}:software-state",),
    "patch-classify": ("tenant:{tenant_id}:patch-state",),
    "platform-evaluate": ("tenant:{tenant_id}:platform-findings",),
    "cmdb-evaluate": ("tenant:{tenant_id}:cmdb-findings",),
    "resolver": ("tenant:{tenant_id}:identity-state",),
    "parity-check": ("tenant:{tenant_id}:parity-state",),
    "agent-compliance": ("tenant:{tenant_id}:legacy-agent-compliance",),
    "agent-compliance-evaluate": ("tenant:{tenant_id}:legacy-agent-compliance",),
    "agent-compliance-review-digest": (
        "tenant:{tenant_id}:legacy-agent-compliance",
        "tenant:{tenant_id}:notification-delivery",
    ),
    "intel-kev": (),
    "intel-nvd": (),
    "intel-cpe-dict": (),
    "intel-epss": (),
    "intel-matcher": ("tenant:{tenant_id}:software-cve-match",),
    "intel-winget": (),
    "intel-chocolatey": (),
    "intel-capability": (),
    "intel-lolrmm": (),
    "intel-otx": ("tenant:{tenant_id}:threat-intelligence",),
    "intel-abusech": ("tenant:{tenant_id}:threat-intelligence",),
    "intel-endoflife": (),
    "intel-category": (),
    "notifications-dispatch": ("tenant:{tenant_id}:notification-delivery",),
    "notifications-digest": ("tenant:{tenant_id}:notification-delivery",),
    "retention-history": ("tenant:{tenant_id}:history-retention",),
    "software-enqueue-orgs": ("tenant:{tenant_id}:software-inventory",),
    "software-queue-drain": ("tenant:{tenant_id}:software-inventory",),
    "source-actions": ("tenant:{tenant_id}:source-actions",),
    "run-log-recovery": ("tenant:{tenant_id}:run-history",),
    "platform-health-evaluate": ("tenant:{tenant_id}:platform-health",),
    "metabase-bootstrap": ("tenant:{tenant_id}:reporting",),
}
for _key in ("intel-nvd", "intel-cpe-dict", "intel-kev", "intel-epss", "intel-matcher"):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("global:intel-cve-corpus",)
for _key in (
    "intel-winget",
    "intel-chocolatey",
    "intel-capability",
    "intel-lolrmm",
    "intel-category",
    "intel-endoflife",
):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("global:software-catalog",)
for _key in (
    "software-enqueue-orgs",
    "software-queue-drain",
):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("tenant:{tenant_id}:software-inventory",)
for _key in ("software-classify", "software-classify-only", "software-classify-full"):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("tenant:{tenant_id}:software-findings",)

_CAPACITY_KEYS_BY_DEFINITION: dict[str, tuple[str, ...]] = {
    "source-refresh": ("capacity:external-io",),
    "patches": (),
    "agent-observations": (),
    "documentation-observations": (),
    "software-classify": ("capacity:processing",),
    "software-classify-only": ("capacity:processing",),
    "software-classify-full": ("capacity:processing",),
    "patch-classify": ("capacity:processing",),
    "platform-evaluate": ("capacity:processing",),
    "cmdb-evaluate": ("capacity:processing",),
    "resolver": ("capacity:processing",),
    "parity-check": ("capacity:processing",),
    "agent-compliance": ("capacity:processing",),
    "agent-compliance-evaluate": ("capacity:processing",),
    "agent-compliance-review-digest": ("capacity:control",),
    "intel-kev": (),
    "intel-nvd": (),
    "intel-cpe-dict": (),
    "intel-epss": (),
    "intel-matcher": ("capacity:processing",),
    "intel-winget": (),
    "intel-chocolatey": (),
    "intel-capability": ("capacity:processing",),
    "intel-lolrmm": (),
    "intel-otx": (),
    "intel-abusech": (),
    "intel-endoflife": (),
    "intel-category": ("capacity:processing",),
    "notifications-dispatch": ("capacity:control",),
    "notifications-digest": ("capacity:control",),
    "retention-history": ("capacity:control",),
    "software-enqueue-orgs": ("capacity:control",),
    "software-queue-drain": (),
    "source-actions": (),
    "run-log-recovery": ("capacity:control",),
    "platform-health-evaluate": ("capacity:processing", "capacity:control"),
    "metabase-bootstrap": ("capacity:control",),
}

_SUPERSESSION_RANKS = MappingProxyType(
    {
        "software-classify-only": 1,
        "software-classify-full": 2,
        "software-classify": 3,
    }
)
_SUPERSESSION_FAMILIES = MappingProxyType(
    {key: "software-classifier" for key in _SUPERSESSION_RANKS}
)
_WORKFLOW_SUCCESSORS = MappingProxyType(
    {
        "source-refresh": (
            DependencyDefinition(
                "patch-classify", "ninja.patch-snapshot", "ninja_source"
            ),
            DependencyDefinition(
                "resolver", "source.identity-observations", "identity_source"
            ),
            DependencyDefinition(
                "cmdb-evaluate", "source.documentation-observations", "documentation_source"
            ),
            DependencyDefinition(
                "intel-matcher", "source.reference-match-data", "reference_match_data"
            ),
            DependencyDefinition(
                "software-classify-only",
                "source.reference-software-data",
                "reference_software_data",
            ),
        ),
        "patches": (
            DependencyDefinition("patch-classify", "ninja.patch-snapshot"),
            DependencyDefinition("resolver", "ninja.identity-snapshot"),
        ),
        "patch-classify": (DependencyDefinition("platform-evaluate", "patch.findings"),),
        "resolver": (DependencyDefinition("platform-evaluate", "identity.current"),),
        "agent-observations": (DependencyDefinition("resolver", "source.identity-observations"),),
        "documentation-observations": (
            DependencyDefinition("cmdb-evaluate", "source.documentation-observations"),
        ),
        "source-actions": (
            DependencyDefinition(
                "cmdb-evaluate", "source.documentation-observations", "documentation_source"
            ),
        ),
        "software-queue-drain": (
            DependencyDefinition("software-classify-only", "software.inventory-batch"),
        ),
        "agent-compliance": (DependencyDefinition("resolver", "agent-compliance.observations"),),
        "intel-nvd": (DependencyDefinition("intel-matcher", "intel.cves", "material_change"),),
        "intel-cpe-dict": (DependencyDefinition("intel-matcher", "intel.cpes", "material_change"),),
        "intel-kev": (DependencyDefinition("intel-matcher", "intel.kev", "material_change"),),
        "intel-epss": (DependencyDefinition("intel-matcher", "intel.epss", "material_change"),),
        # Routine intelligence changes feed the incremental classifier.  It touches
        # only installations whose source state is new or changed; the separately
        # scheduled full rebuild remains the weekly safety net for fleet-wide rule,
        # decision, and intelligence reconciliation.
        "intel-matcher": (
            DependencyDefinition("software-classify-only", "software.cve-match", "material_change"),
        ),
        "intel-winget": (
            DependencyDefinition(
                "software-classify-only", "software.winget-signals", "material_change"
            ),
        ),
        "intel-chocolatey": (
            DependencyDefinition(
                "software-classify-only", "software.chocolatey-signals", "material_change"
            ),
        ),
        "intel-capability": (
            DependencyDefinition(
                "software-classify-only", "software.capabilities", "material_change"
            ),
        ),
        "intel-lolrmm": (
            DependencyDefinition("software-classify-only", "software.lolrmm", "material_change"),
        ),
        "intel-otx": (
            DependencyDefinition(
                "software-classify-only", "software.otx-signals", "material_change"
            ),
        ),
        "intel-abusech": (
            DependencyDefinition(
                "software-classify-only", "software.abusech-signals", "material_change"
            ),
        ),
        "intel-endoflife": (
            DependencyDefinition(
                "software-classify-only", "software.end-of-life", "material_change"
            ),
        ),
        "intel-category": (
            DependencyDefinition(
                "software-classify-only", "software.categories", "material_change"
            ),
        ),
    }
)
if set(_RESOURCE_KEYS_BY_DEFINITION) != {item.key for item in _RAW_DEFINITIONS}:
    raise RegistryValidationError("Missing Jobs resource policy")
if set(_CAPACITY_KEYS_BY_DEFINITION) != {item.key for item in _RAW_DEFINITIONS}:
    raise RegistryValidationError("Missing Jobs capacity policy")

_DEFINITIONS = tuple(
    replace(
        item,
        capacity_keys=_CAPACITY_KEYS_BY_DEFINITION[item.key],
        resource_keys=_RESOURCE_KEYS_BY_DEFINITION[item.key],
        supersession_family=_SUPERSESSION_FAMILIES.get(item.key, ""),
        supersession_rank=_SUPERSESSION_RANKS.get(item.key, 0),
        successors=_WORKFLOW_SUCCESSORS.get(item.key, ()),
    )
    for item in _RAW_DEFINITIONS
)

_INDEX = MappingProxyType({definition.key: definition for definition in _DEFINITIONS})
if len(_INDEX) != len(_DEFINITIONS):
    raise RegistryValidationError("Duplicate Jobs registry key")
_SCHEDULE_INDEX = MappingProxyType(
    {schedule.schedule_id: schedule for schedule in _SCHEDULE_DEFINITIONS}
)
if len(_SCHEDULE_INDEX) != len(_SCHEDULE_DEFINITIONS):
    raise RegistryValidationError("Duplicate Jobs schedule key")
if set(_SCHEDULE_INDEX) != {
    schedule_id for item in _DEFINITIONS for schedule_id in item.schedule_ids
}:
    raise RegistryValidationError("Jobs schedule metadata does not match registry definitions")


def definitions() -> tuple[JobDefinition, ...]:
    return _DEFINITIONS


def registry_digest() -> str:
    """Return one credential-free identity for the complete live registry."""
    payload = [{"digest": item.snapshot_digest(), "key": item.key} for item in _DEFINITIONS]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def schedule_definitions() -> tuple[ScheduleDefinition, ...]:
    """Return cadences for operation entry points, never dependent steps."""
    dependent_keys = {successor.successor for item in _DEFINITIONS for successor in item.successors}
    return tuple(
        schedule
        for schedule in _SCHEDULE_DEFINITIONS
        if schedule.job_key not in dependent_keys
        and schedule.job_key not in _SOURCE_OWNED_DEFINITION_KEYS
    )


_SYSTEM_SERVICE_KEYS = frozenset(
    {
        "source-refresh",
        "patches",
        "agent-observations",
        "documentation-observations",
        "intel-nvd",
        "intel-cpe-dict",
        "intel-kev",
        "intel-epss",
        "intel-winget",
        "intel-chocolatey",
        "intel-lolrmm",
        "intel-otx",
        "intel-abusech",
        "intel-endoflife",
        "source-actions",
        "run-log-recovery",
        "platform-health-evaluate",
        "metabase-bootstrap",
        "software-enqueue-orgs",
    }
)
_SOURCE_OWNED_DEFINITION_KEYS = frozenset(
    {
        "intel-nvd", "intel-cpe-dict", "intel-kev", "intel-epss", "intel-winget",
        "intel-chocolatey", "intel-lolrmm", "intel-otx", "intel-abusech",
        "intel-endoflife",
    }
)
_LEGACY_JOB_KEYS = frozenset(
    {
        "agent-compliance",
        "agent-compliance-evaluate",
        "agent-compliance-review-digest",
    }
)
_JOB_MODE_PARENT = MappingProxyType(
    {
        "software-classify": "software-classify-only",
        "software-classify-full": "software-classify-only",
    }
)
_JOB_PRESENTATION = MappingProxyType(
    {
        "patches": ("Refresh Ninja data", "Refresh computers, patches, and activity from Ninja."),
        "agent-observations": (
            "Refresh connected-agent data",
            "Refresh records from connected security and support tools.",
        ),
        "documentation-observations": (
            "Refresh Hudu records",
            "Refresh Hudu CMDB records.",
        ),
        "software-queue-drain": (
            "Refresh software inventory",
            "Refresh requested and scheduled software inventory.",
        ),
        "software-classify-only": (
            "Update software status",
            "Update software findings using current inventory and intelligence.",
        ),
        "patch-classify": ("Update patch status", "Update patch findings from current patch data."),
        "platform-evaluate": (
            "Evaluate client status",
            "Update computer, coverage, identity, and lifecycle findings.",
        ),
        "cmdb-evaluate": (
            "Review Hudu records",
            "Update findings from current Hudu CMDB records.",
        ),
        "resolver": ("Match records", "Match source records to the correct client and computer."),
        "parity-check": (
            "Check data consistency",
            "Check that collected data is represented in Operations.",
        ),
        "intel-kev": (
            "Update known exploited vulnerabilities",
            "Refresh CISA known exploited vulnerability data.",
        ),
        "intel-nvd": ("Update vulnerability data", "Refresh vulnerability data from NVD."),
        "intel-cpe-dict": (
            "Update software matching data",
            "Refresh the CPE dictionary used for software matching.",
        ),
        "intel-epss": ("Update vulnerability likelihood", "Refresh EPSS likelihood data."),
        "intel-matcher": (
            "Match software to vulnerabilities",
            "Match installed software to known vulnerabilities.",
        ),
        "intel-winget": (
            "Update WinGet software data",
            "Refresh Windows Package Manager software data.",
        ),
        "intel-chocolatey": (
            "Update Chocolatey software data",
            "Refresh Chocolatey software data.",
        ),
        "intel-capability": ("Update software capabilities", "Update known software capabilities."),
        "intel-lolrmm": (
            "Update remote-access software data",
            "Refresh remote-management software information.",
        ),
        "intel-otx": (
            "Update threat information (OTX)",
            "Refresh AlienVault OTX threat information.",
        ),
        "intel-abusech": (
            "Update threat information (abuse.ch)",
            "Refresh abuse.ch threat information.",
        ),
        "intel-endoflife": ("Update end-of-life data", "Refresh software end-of-life information."),
        "intel-category": ("Update software categories", "Update software category information."),
        "notifications-dispatch": ("Send alerts", "Deliver pending operational alerts."),
        "notifications-digest": ("Send summary", "Deliver the scheduled operational summary."),
        "retention-history": ("Clean up history", "Apply the configured history-retention policy."),
    }
)

_JOB_START_PRESENTATION = MappingProxyType(
    {
        "patch-classify": "After Ninja refresh",
        "platform-evaluate": "After source data refresh",
        "cmdb-evaluate": "After Hudu refresh",
        "resolver": "After source data refresh",
        "software-classify-only": "After software inventory or vulnerability data changes",
        "intel-matcher": "After vulnerability data refresh",
    }
)


_OPERATOR_JOB_GROUPS = (
    ("source-data", "Refresh Source Data"),
    ("software-data", "Refresh Software Data"),
    ("security-data", "Refresh Security Data"),
    ("matching", "Match Records"),
    ("analysis", "Analyze Source Information"),
    ("maintenance", "Maintain Operations"),
    ("notifications", "Send Notifications"),
)
_OPERATOR_JOB_GROUP_BY_KEY = MappingProxyType(
    {
        "software-queue-drain": "source-data",
        "intel-capability": "software-data",
        "intel-category": "software-data",
        "resolver": "matching",
        "intel-matcher": "matching",
        "software-classify-only": "analysis",
        "patch-classify": "analysis",
        "platform-evaluate": "analysis",
        "cmdb-evaluate": "analysis",
        "parity-check": "maintenance",
        "retention-history": "maintenance",
        "notifications-dispatch": "notifications",
        "notifications-digest": "notifications",
    }
)


def operator_job_group_definitions() -> tuple[tuple[str, str], ...]:
    """Return ordered, operator-facing Jobs groups."""
    return _OPERATOR_JOB_GROUPS


def operator_job_definitions() -> tuple[OperatorJobDefinition, ...]:
    """Return the Jobs catalog; System services and legacy bridges stay out."""
    members: dict[str, list[str]] = {}
    for item in _DEFINITIONS:
        if item.key in _SYSTEM_SERVICE_KEYS or item.key in _LEGACY_JOB_KEYS:
            continue
        catalog_key = _JOB_MODE_PARENT.get(item.key, item.key)
        members.setdefault(catalog_key, []).append(item.key)
    catalog_keys = set(members)
    configured_keys = set(_OPERATOR_JOB_GROUP_BY_KEY)
    if catalog_keys != configured_keys:
        raise RegistryValidationError(
            "Operator Jobs grouping does not cover the visible Jobs catalog: "
            f"missing={sorted(catalog_keys - configured_keys)} "
            f"unknown={sorted(configured_keys - catalog_keys)}"
        )
    group_keys = {key for key, _label in _OPERATOR_JOB_GROUPS}
    result = []
    for key, execution_keys in members.items():
        item = _INDEX[key]
        name, description = _JOB_PRESENTATION.get(key, (item.display_name, item.description))
        group_key = _OPERATOR_JOB_GROUP_BY_KEY[key]
        if group_key not in group_keys:
            raise RegistryValidationError(f"Operator Job {key} has an unknown group")
        result.append(
            OperatorJobDefinition(
                key=key,
                group_key=group_key,
                name=name,
                description=description,
                start_description=_JOB_START_PRESENTATION.get(key, ""),
                primary_execution_key=key,
                execution_keys=tuple(execution_keys),
            )
        )
    return tuple(sorted(result, key=lambda item: item.name.lower()))


def operator_job_definition(key: str) -> OperatorJobDefinition:
    try:
        return next(item for item in operator_job_definitions() if item.key == key)
    except StopIteration as exc:
        raise RegistryValidationError(f"Unknown operator Job: {key}") from exc


def operator_job_key_for_execution(key: str) -> str | None:
    """Return the visible Job owning an execution key, or None for services."""
    if key not in _INDEX or key in _SYSTEM_SERVICE_KEYS or key in _LEGACY_JOB_KEYS:
        return None
    return _JOB_MODE_PARENT.get(key, key)


def system_service_definition_keys() -> frozenset[str]:
    return _SYSTEM_SERVICE_KEYS


def legacy_job_definition_keys() -> frozenset[str]:
    return _LEGACY_JOB_KEYS


def workflow_edges(
    root_key: str, conditions: frozenset[str] = frozenset({"always"})
) -> tuple[WorkflowEdge, ...]:
    """Return matching root edges plus transitive always-required edges."""
    definition(root_key)
    edges: list[WorkflowEdge] = []
    visited: set[tuple[str, str, str]] = set()

    def visit(prerequisite: str, ancestors: frozenset[str], root: bool) -> None:
        if prerequisite in ancestors:
            raise RegistryValidationError("Jobs workflow contains a cycle")
        for successor in definition(prerequisite).successors:
            if successor.condition not in (conditions if root else frozenset({"always"})):
                continue
            definition(successor.successor)
            identity = (prerequisite, successor.successor, successor.revision_name)
            if identity not in visited:
                visited.add(identity)
                edge = WorkflowEdge(
                    prerequisite,
                    successor.successor,
                    successor.revision_name,
                    successor.condition,
                    successor.scope_mode,
                    successor.coalescing,
                    successor.failure_rule,
                )
                edges.append(edge)
                visit(successor.successor, ancestors | {prerequisite}, False)

    visit(root_key, frozenset(), True)
    return tuple(edges)


def definition(key: str) -> JobDefinition:
    try:
        return _INDEX[key]
    except KeyError as exc:
        raise RegistryValidationError(f"Unknown Jobs definition: {key}") from exc


def definition_keys() -> frozenset[str]:
    return frozenset(_INDEX)


def _validate_dependency_contracts() -> None:
    allowed_conditions = {
        "always",
        "identity_source",
        "documentation_source",
        "ninja_source",
        "reference_match_data",
        "reference_software_data",
        "material_change",
    }
    revision_pattern = re.compile(r"[a-z0-9][a-z0-9._-]{2,119}")
    errors: list[str] = []
    graph: dict[str, tuple[str, ...]] = {}
    for job in _DEFINITIONS:
        targets: set[str] = set()
        graph[job.key] = tuple(successor.successor for successor in job.successors)
        for successor in job.successors:
            if successor.successor not in _INDEX:
                errors.append(f"{job.key} has unknown successor {successor.successor}")
            if successor.successor in targets:
                errors.append(f"{job.key} has duplicate successor {successor.successor}")
            targets.add(successor.successor)
            if revision_pattern.fullmatch(successor.revision_name) is None:
                errors.append(f"{job.key} has invalid revision name")
            if successor.condition not in allowed_conditions:
                errors.append(f"{job.key} has invalid dependency condition")
            if successor.scope_mode not in {"inherit", "tenant"}:
                errors.append(f"{job.key} has unsupported dependency scope")
            if successor.coalescing != "definition_scope":
                errors.append(f"{job.key} has unsupported dependency coalescing")
            if successor.failure_rule != "block":
                errors.append(f"{job.key} has unsupported dependency failure rule")
        if not 1 <= job.timeout_minutes <= 1440:
            errors.append(f"{job.key} has an invalid timeout")
        if not 0 <= job.priority <= 100:
            errors.append(f"{job.key} has an invalid priority")
        if job.coalescing_scope != "definition_scope":
            errors.append(f"{job.key} has an unsupported coalescing scope")
        if job.concurrency_scope != "resource_keys":
            errors.append(f"{job.key} has an unsupported concurrency scope")
        if any(key not in EXECUTION_POOL_POLICIES for key in job.capacity_keys):
            errors.append(f"{job.key} has an invalid capacity policy")
        if any(key.startswith("capacity:") for key in job.resource_keys):
            errors.append(f"{job.key} mixes capacity and domain resources")
        if job.progress_contract != "stage":
            errors.append(f"{job.key} has an unsupported progress contract")
        if job.result_contract != "rows_or_outcome":
            errors.append(f"{job.key} has an unsupported result contract")
        if job.permission not in {"administrator", "system"}:
            errors.append(f"{job.key} has an unsupported permission contract")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            errors.append(f"Jobs workflow contains a cycle at {key}")
            return
        if key in visited:
            return
        visiting.add(key)
        for successor in graph.get(key, ()):
            visit(successor)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
    for key, evidence in REPLAY_SAFE_RECOVERY_EVIDENCE.items():
        if key not in _INDEX:
            errors.append(f"Jobs recovery policy has unknown definition {key}")
        if not 20 <= len(evidence) <= 2000:
            errors.append(f"Jobs recovery policy has invalid evidence for {key}")
    if errors:
        raise RegistryValidationError("; ".join(errors))


def catalog_entries() -> tuple[dict[str, object], ...]:
    return tuple(definition.catalog_entry() for definition in _DEFINITIONS)


def scheduled_definition_keys() -> frozenset[str]:
    return frozenset(schedule.job_key for schedule in schedule_definitions())


def capability_state(
    definition_key: str, enabled_capabilities: Mapping[str, bool]
) -> tuple[bool, str]:
    """Return an operator label without reading environment or database state."""
    job = definition(definition_key)
    if enabled_capabilities.get(job.capability, job.capability == "always"):
        return True, "Available"
    capability_label = {
        "legacy_agent_compliance": "legacy bridge",
    }.get(job.capability, job.capability.replace("_", " "))
    return False, f"Disabled — {capability_label} is not enabled."


def validate_registry(
    *,
    catalog_keys: Iterable[str] = (),
    executable_keys: Iterable[str] = (),
    scheduled_keys: Iterable[str] = (),
) -> None:
    """Fail closed when a consumer omits, adds, or duplicates a definition."""
    expected = definition_keys()
    supplied = {
        "catalog": tuple(catalog_keys),
        "executable": tuple(executable_keys),
        "scheduled": tuple(scheduled_keys),
    }
    errors: list[str] = []
    for name, values in supplied.items():
        if not values:
            continue
        actual = frozenset(values)
        if len(actual) != len(values):
            errors.append(f"{name} has duplicate keys")
        required = scheduled_definition_keys() if name == "scheduled" else expected
        missing = sorted(required - actual)
        extra = sorted(actual - required)
        if missing:
            errors.append(f"{name} missing {', '.join(missing)}")
        if extra:
            errors.append(f"{name} has unregistered {', '.join(extra)}")
    if errors:
        raise RegistryValidationError("; ".join(errors))


_validate_dependency_contracts()
