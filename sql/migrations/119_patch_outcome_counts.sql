-- Compact exact-time counts for Home.  The timestamp remains exact so the
-- rolling 30-day boundary does not depend on a scheduled refresh.
CREATE TABLE ninja_patches.patch_outcome_counts (
    device_id integer NOT NULL,
    installed_at timestamptz NOT NULL,
    status text NOT NULL,
    outcome_count bigint NOT NULL CHECK (outcome_count > 0),
    PRIMARY KEY (device_id, installed_at, status)
);

CREATE INDEX patch_outcome_counts_time_idx
    ON ninja_patches.patch_outcome_counts (installed_at, device_id);

-- Exclude concurrent writers while building the initial summary and installing
-- its trigger.  The migration runner applies this whole file transactionally.
LOCK TABLE ninja_patches.patch_facts IN SHARE ROW EXCLUSIVE MODE;

INSERT INTO ninja_patches.patch_outcome_counts
    (device_id, installed_at, status, outcome_count)
SELECT device_id, installed_at, status, count(*)
  FROM ninja_patches.patch_facts
 WHERE fact_type = 'install_outcome' AND installed_at IS NOT NULL
 GROUP BY device_id, installed_at, status;

CREATE FUNCTION ninja_patches.maintain_patch_outcome_counts()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, ninja_patches
AS $$
DECLARE
    previous_count bigint;
BEGIN
    IF TG_OP = 'UPDATE' AND
       (OLD.device_id, OLD.installed_at, OLD.status, OLD.fact_type)
       IS NOT DISTINCT FROM
       (NEW.device_id, NEW.installed_at, NEW.status, NEW.fact_type) THEN
        RETURN NEW;
    END IF;

    IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.fact_type = 'install_outcome'
       AND OLD.installed_at IS NOT NULL THEN
        SELECT outcome_count INTO previous_count
          FROM ninja_patches.patch_outcome_counts
         WHERE device_id = OLD.device_id AND installed_at = OLD.installed_at
           AND status = OLD.status FOR UPDATE;
        IF previous_count IS NULL THEN
            RAISE EXCEPTION 'Missing patch outcome count';
        ELSIF previous_count = 1 THEN
            DELETE FROM ninja_patches.patch_outcome_counts
             WHERE device_id = OLD.device_id AND installed_at = OLD.installed_at
               AND status = OLD.status;
        ELSE
            UPDATE ninja_patches.patch_outcome_counts
               SET outcome_count = outcome_count - 1
             WHERE device_id = OLD.device_id AND installed_at = OLD.installed_at
               AND status = OLD.status;
        END IF;
    END IF;

    IF TG_OP IN ('INSERT', 'UPDATE') AND NEW.fact_type = 'install_outcome'
       AND NEW.installed_at IS NOT NULL THEN
        INSERT INTO ninja_patches.patch_outcome_counts
            (device_id, installed_at, status, outcome_count)
        VALUES (NEW.device_id, NEW.installed_at, NEW.status, 1)
        ON CONFLICT (device_id, installed_at, status)
        DO UPDATE SET outcome_count = patch_outcome_counts.outcome_count + 1;
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION ninja_patches.maintain_patch_outcome_counts() FROM PUBLIC;
CREATE TRIGGER patch_outcome_counts_maintain
AFTER INSERT OR UPDATE OR DELETE ON ninja_patches.patch_facts
FOR EACH ROW EXECUTE FUNCTION ninja_patches.maintain_patch_outcome_counts();

REVOKE ALL ON ninja_patches.patch_outcome_counts FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ninja_patches.patch_outcome_counts
    FROM operations_app, operations_readonly;
GRANT SELECT ON ninja_patches.patch_outcome_counts TO operations_app, operations_readonly;
