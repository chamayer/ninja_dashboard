-- Migration 109 added condition predicates to this view. Apply the owner
-- grants separately so existing databases that already recorded 109 receive
-- the required base-table permissions.
GRANT SELECT ON operations.condition_assessments,
    operations.condition_policy_versions
TO operations_view_owner;
