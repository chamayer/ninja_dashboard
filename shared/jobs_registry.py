"""Declarative metadata shared by Operations and ingest Jobs consumers.

This module deliberately imports only the standard library.  It describes the
current durable operator-queue definitions; it does not import handlers,
connect to Postgres, choose resource capacity, or make an unconverted legacy
path safe to execute.
"""

from __future__ import annotations

import hashlib
import json
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
    resource_keys: tuple[str, ...] = ()
    supersession_family: str = ""
    supersession_rank: int = 0
    handler_version: str = "registry-v1"
    retry_policy: str = "manual_only_unreviewed"
    kill_safe: bool = False
    successors: tuple[str, ...] = ()

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
            "resource_keys": list(self.resource_keys),
            "supersession_family": self.supersession_family,
            "supersession_rank": self.supersession_rank,
            "successors": list(self.successors),
        }

    def snapshot_digest(self) -> str:
        encoded = json.dumps(
            self.snapshot_metadata(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


_RAW_DEFINITIONS = (
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
        schedule_ids=("patch_ingest_cycle",),
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
        schedule_ids=("agent_observations_cycle",),
    ),
    JobDefinition(
        "documentation-observations",
        "Documentation observations",
        "Refresh documentation records from Hudu.",
        "source ingest",
        "collection",
        "run/sources/enqueue",
        "source.Hudu",
        "run_log_like",
        "ingest.main.run_documentation_observations_once",
        run_all=False,
        schedule_ids=("documentation_observations_cycle",),
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
        "source-demand",
        "Source demand worker",
        "Process one queued on-demand source refresh with its retained source record.",
        "maintenance",
        "collection",
        "",
        "source_run_queue",
        "run_log",
        "ingest.source_run_queue.process_next",
        run_all=False,
        schedule_ids=("source_demand_cycle",),
    ),
    JobDefinition(
        "source-demand-recovery",
        "Source demand recovery",
        "Mark source-demand work whose execution lease expired for operator review.",
        "maintenance",
        "service",
        "",
        "source_run_queue",
        "run_log",
        "ingest.source_run_queue.recover_stale",
        run_all=False,
        schedule_ids=("source_demand_recovery_cycle",),
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
)


_SCHEDULE_DEFINITIONS = (
    ScheduleDefinition("patch_ingest_cycle", "patches", "PATCH_INGEST_SCHEDULE_HOURS"),
    ScheduleDefinition("agent_observations_cycle", "agent-observations", "AGENT_COMPLIANCE_SCHEDULE_HOURS"),
    ScheduleDefinition("documentation_observations_cycle", "documentation-observations", "DOCUMENTATION_SCHEDULE_HOURS"),
    ScheduleDefinition("identity_resolver_cycle", "resolver", "constant:30", "minutes"),
    ScheduleDefinition("platform_evaluate_cycle", "platform-evaluate", "constant:4"),
    ScheduleDefinition("software_classify_cycle", "software-classify-only", "SOFTWARE_CLASSIFY_SCHEDULE_HOURS"),
    ScheduleDefinition("software_classify_full_rebuild_cycle", "software-classify-full", "SOFTWARE_CLASSIFY_FULL_REBUILD_HOURS"),
    ScheduleDefinition("software_enqueue_orgs_cycle", "software-enqueue-orgs", "SOFTWARE_INGEST_SCHEDULE_HOURS"),
    ScheduleDefinition("software_queue_drain_cycle", "software-queue-drain", "SOFTWARE_QUEUE_POLL_MINUTES", "minutes"),
    ScheduleDefinition("source_action_requests_cycle", "source-actions", "constant:1", "minutes"),
    ScheduleDefinition("source_demand_cycle", "source-demand", "constant:1", "minutes"),
    ScheduleDefinition("source_demand_recovery_cycle", "source-demand-recovery", "constant:15", "minutes"),
    ScheduleDefinition("run_log_recovery_cycle", "run-log-recovery", "constant:30", "minutes"),
    ScheduleDefinition("platform_health_evaluate_cycle", "platform-health-evaluate", "constant:30", "minutes"),
    ScheduleDefinition("notifications_dispatch_cycle", "notifications-dispatch", "NOTIFY_DISPATCH_SCHEDULE_MINUTES", "minutes"),
    ScheduleDefinition("notifications_digest_cycle", "notifications-digest", "NOTIFY_DIGEST_HOUR", "cron-hour"),
    ScheduleDefinition("observation_history_retention_cycle", "retention-history", "OBSERVATION_HISTORY_RETENTION_HOUR", "cron-hour"),
    ScheduleDefinition("agent_compliance_ingest_cycle", "agent-compliance", "AGENT_COMPLIANCE_SCHEDULE_HOURS"),
    ScheduleDefinition("agent_compliance_evaluate_cycle", "agent-compliance-evaluate", "AGENT_COMPLIANCE_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_nvd_cycle", "intel-nvd", "INTEL_NVD_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_cpe_dict_cycle", "intel-cpe-dict", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_kev_cycle", "intel-kev", "INTEL_KEV_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_epss_cycle", "intel-epss", "INTEL_EPSS_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_matcher_cycle", "intel-matcher", "INTEL_MATCHER_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_winget_cycle", "intel-winget", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_chocolatey_cycle", "intel-chocolatey", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_otx_cycle", "intel-otx", "INTEL_OSINT_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_abusech_cycle", "intel-abusech", "INTEL_OSINT_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_endoflife_cycle", "intel-endoflife", "INTEL_CATALOG_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_capability_cycle", "intel-capability", "INTEL_CAPABILITY_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_category_cycle", "intel-category", "INTEL_CATEGORY_SCHEDULE_HOURS"),
    ScheduleDefinition("intel_lolrmm_cycle", "intel-lolrmm", "INTEL_CATALOG_SCHEDULE_HOURS"),
)

# Initial limits preserve the only capacity behavior the current process proves:
# two durable handlers in total and one poller per lane.  They are a ceiling,
# not a worker-service replica count or a claim that narrower scopes are unsafe.
INITIAL_EXECUTION_CAPACITY = 2
INITIAL_LANE_CAPACITIES = MappingProxyType({
    "collection": 1,
    "evaluation": 1,
    "software": 1,
    "intelligence": 1,
    "service": 1,
})

_GLOBAL_ONLY = frozenset({
    "intel-nvd", "intel-cpe-dict", "intel-kev", "intel-epss",
    "intel-capability", "intel-lolrmm", "intel-category",
})
_RESOURCE_KEYS_BY_DEFINITION: dict[str, tuple[str, ...]] = {
    item.key: (() if item.key in _GLOBAL_ONLY else ("tenant:{tenant_id}:state",))
    for item in _RAW_DEFINITIONS
}
for _key in ("intel-nvd", "intel-cpe-dict", "intel-kev", "intel-epss", "intel-matcher"):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("global:intel-cve-corpus",)
for _key in (
    "software-classify", "software-classify-only", "software-classify-full",
    "intel-winget", "intel-chocolatey", "intel-capability", "intel-lolrmm",
    "intel-category", "intel-endoflife",
):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("global:software-catalog",)
for _key in (
    "software-enqueue-orgs", "software-queue-drain", "software-classify",
    "software-classify-only", "software-classify-full",
):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("tenant:{tenant_id}:software-inventory",)
for _key in (
    "notifications-dispatch", "notifications-digest",
    "agent-compliance-review-digest",
):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("tenant:{tenant_id}:notification-delivery",)
for _key in (
    "agent-compliance", "agent-compliance-evaluate",
    "agent-compliance-review-digest",
):
    _RESOURCE_KEYS_BY_DEFINITION[_key] += ("tenant:{tenant_id}:legacy-agent-compliance",)

_SUPERSESSION_RANKS = MappingProxyType({
    "software-classify-only": 1,
    "software-classify-full": 2,
    "software-classify": 3,
})
_SUPERSESSION_FAMILIES = MappingProxyType({
    key: "software-classifier" for key in _SUPERSESSION_RANKS
})
_WORKFLOW_SUCCESSORS = MappingProxyType({
    "patches": ("patch-classify", "resolver"),
    "patch-classify": ("platform-evaluate",),
    "resolver": ("platform-evaluate",),
    "agent-observations": ("resolver",),
    "documentation-observations": ("resolver",),
    "source-demand": ("resolver",),
    "source-actions": ("resolver",),
    "software-queue-drain": ("software-classify-only",),
    "agent-compliance": ("resolver",),
    "intel-nvd": ("intel-matcher",),
    "intel-cpe-dict": ("intel-matcher",),
    "intel-kev": ("intel-matcher",),
    "intel-epss": ("intel-matcher",),
    "intel-matcher": ("software-classify-full",),
    "intel-winget": ("software-classify-full",),
    "intel-chocolatey": ("software-classify-full",),
    "intel-capability": ("software-classify-full",),
    "intel-lolrmm": ("software-classify-full",),
    "intel-otx": ("software-classify-full",),
    "intel-abusech": ("software-classify-full",),
    "intel-endoflife": ("software-classify-full",),
    "intel-category": ("software-classify-full",),
})
if set(_RESOURCE_KEYS_BY_DEFINITION) != {item.key for item in _RAW_DEFINITIONS}:
    raise RegistryValidationError("Missing Jobs resource policy")

_DEFINITIONS = tuple(
    replace(
        item,
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
_SCHEDULE_INDEX = MappingProxyType({schedule.schedule_id: schedule for schedule in _SCHEDULE_DEFINITIONS})
if len(_SCHEDULE_INDEX) != len(_SCHEDULE_DEFINITIONS):
    raise RegistryValidationError("Duplicate Jobs schedule key")
if set(_SCHEDULE_INDEX) != {schedule_id for item in _DEFINITIONS for schedule_id in item.schedule_ids}:
    raise RegistryValidationError("Jobs schedule metadata does not match registry definitions")


def definitions() -> tuple[JobDefinition, ...]:
    return _DEFINITIONS


def schedule_definitions() -> tuple[ScheduleDefinition, ...]:
    """Return every declared automatic cadence in stable registry order."""
    return _SCHEDULE_DEFINITIONS


def workflow_edges(root_key: str) -> tuple[tuple[str, str], ...]:
    """Return the declared completion graph in prerequisite-first order."""
    definition(root_key)
    edges: list[tuple[str, str]] = []
    visited: set[str] = set()

    def visit(prerequisite: str, ancestors: frozenset[str]) -> None:
        if prerequisite in ancestors:
            raise RegistryValidationError("Jobs workflow contains a cycle")
        for dependent in definition(prerequisite).successors:
            definition(dependent)
            edge = (prerequisite, dependent)
            if edge not in visited:
                visited.add(edge)
                edges.append(edge)
                visit(dependent, ancestors | {prerequisite})

    visit(root_key, frozenset())
    return tuple(edges)


def definition(key: str) -> JobDefinition:
    try:
        return _INDEX[key]
    except KeyError as exc:
        raise RegistryValidationError(f"Unknown Jobs definition: {key}") from exc


def definition_keys() -> frozenset[str]:
    return frozenset(_INDEX)


def catalog_entries() -> tuple[dict[str, object], ...]:
    return tuple(definition.catalog_entry() for definition in _DEFINITIONS)


def scheduled_definition_keys() -> frozenset[str]:
    return frozenset(
        definition.key for definition in _DEFINITIONS if definition.schedule_ids
    )


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
