-- 088: deterministic lifecycle coverage for known high-risk product families.
--
-- These are managed global reference rules, not an operator queue.  They do
-- not contain lifecycle dates, build numbers, or fuzzy matching: the refreshed
-- endoflife.date corpus remains the source of cycles and dates, and the
-- projector still requires an exact version-prefix/year-cycle match.

CREATE TABLE IF NOT EXISTS intel.eol_managed_product_rules (
    rule_key          text PRIMARY KEY,
    title_pattern     text NOT NULL,
    publisher_pattern text NOT NULL DEFAULT '',
    eol_product       text NOT NULL REFERENCES intel.eol_products(name) ON DELETE CASCADE,
    version_pattern   text NOT NULL DEFAULT '',
    eol_cycle         text NOT NULL DEFAULT '',
    priority          integer NOT NULL DEFAULT 100,
    enabled           boolean NOT NULL DEFAULT true,
    notes             text NOT NULL DEFAULT '',
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS eol_managed_product_rules_order_idx
    ON intel.eol_managed_product_rules (enabled, priority, rule_key);

INSERT INTO intel.eol_managed_product_rules (
    rule_key, title_pattern, publisher_pattern, eol_product,
    version_pattern, eol_cycle, priority, notes
)
VALUES
    -- Existing verified browser/editor/runtime coverage, now self-maintaining.
    ('chrome', 'google chrome', '', 'chrome', '', '', 10,
     'Exact Google Chrome product title.'),
    ('firefox', 'mozilla firefox%', '', 'firefox', '', '', 10,
     'Mozilla Firefox product family.'),
    ('notepad-plus-plus', 'notepad++%', '', 'notepad-plus-plus', '', '', 10,
     'Notepad++ product family.'),
    ('powershell-7', 'powershell 7%', '', 'powershell', '', '', 10,
     'PowerShell 7 only; inbox Windows PowerShell follows Windows servicing.'),

    -- Perpetual Office uses the existing year-in-title cycle derivation.  M365
    -- titles intentionally do not match: channel currency is a separate fact.
    ('office-2010', 'microsoft office%2010%', '', 'office', '', '', 20,
     'Perpetual Office 2010; title year selects the corpus cycle.'),
    ('office-2013', 'microsoft office%2013%', '', 'office', '', '', 20,
     'Perpetual Office 2013; title year selects the corpus cycle.'),
    ('office-2016', 'microsoft office%2016%', '', 'office', '', '', 20,
     'Perpetual Office 2016; title year selects the corpus cycle.'),
    ('office-2019', 'microsoft office%2019%', '', 'office', '', '', 20,
     'Perpetual Office 2019; title year selects the corpus cycle.'),
    ('office-2021', 'microsoft office%2021%', '', 'office', '', '', 20,
     'Perpetual Office 2021; title year selects the corpus cycle.'),

    -- Oracle and Sun gates avoid applying the JDK lifecycle to unrelated Java
    -- tooling.  JRE and JDK titles carry the installed numeric version.
    ('oracle-java', 'java%', 'oracle%', 'oracle-jdk', '', '', 30,
     'Oracle JRE/JDK family.'),
    ('sun-java', 'java%', 'sun%', 'oracle-jdk', '', '', 30,
     'Sun-branded JRE/JDK family retained by Oracle lifecycle history.'),
    ('oracle-jdk', 'jdk%', 'oracle%', 'oracle-jdk', '', '', 30,
     'Oracle JDK package family.'),
    ('sun-jdk', 'jdk%', 'sun%', 'oracle-jdk', '', '', 30,
     'Sun JDK package family.'),

    -- Specific .NET Framework rule outranks the broader modern .NET rule.
    ('dotnet-framework', 'microsoft .net framework%', '', 'dotnetfx', '', '', 40,
     '.NET Framework family.'),
    ('dotnet', 'microsoft .net%', '', 'dotnet', '', '', 60,
     'Modern Microsoft .NET SDK/runtime family.'),
    ('windows-desktop-runtime', 'microsoft windows desktop runtime%', '', 'dotnet', '', '', 60,
     'Windows Desktop Runtime is a modern .NET runtime.'),

    -- Version/year constrained patterns deliberately exclude adjacent tools
    -- such as Visual Studio Code and SQL Server Management Studio.
    ('visual-studio', 'microsoft visual studio%20%', '', 'visual-studio', '', '', 70,
     'Versioned Visual Studio IDE releases.'),
    ('python', 'python%', '', 'python', '', '', 80,
     'Python interpreter family.'),
    ('nodejs', 'node.js%', '', 'nodejs', '', '', 80,
     'Node.js runtime family.'),
    ('nodejs-alt', 'nodejs%', '', 'nodejs', '', '', 80,
     'Node.js alternate title spelling.'),
    ('sql-server', 'microsoft sql server 20%', '', 'mssqlserver', '', '', 90,
     'Year-versioned Microsoft SQL Server engine releases.'),
    ('postgresql', 'postgresql%', '', 'postgresql', '', '', 90,
     'PostgreSQL server family.'),
    ('mysql-server', 'mysql server%', '', 'mysql', '', '', 90,
     'MySQL Server only; client tools are excluded.'),
    ('vcenter', 'vmware vcenter server%', '', 'vcenter', '', '', 90,
     'VMware vCenter Server family.'),
    ('libreoffice', 'libreoffice%', '', 'libreoffice', '', '', 90,
     'LibreOffice suite family.')
ON CONFLICT (rule_key) DO UPDATE SET
    title_pattern     = EXCLUDED.title_pattern,
    publisher_pattern = EXCLUDED.publisher_pattern,
    eol_product       = EXCLUDED.eol_product,
    version_pattern   = EXCLUDED.version_pattern,
    eol_cycle         = EXCLUDED.eol_cycle,
    priority          = EXCLUDED.priority,
    enabled           = EXCLUDED.enabled,
    notes             = EXCLUDED.notes,
    updated_at        = now();

REVOKE ALL ON intel.eol_managed_product_rules FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON intel.eol_managed_product_rules
    FROM ninja_ingest, operations_app, operations_readonly, metabase_ro;
GRANT SELECT ON intel.eol_managed_product_rules
    TO ninja_ingest, operations_app, operations_readonly, metabase_ro;

-- Preserve historical tenant mappings for projection compatibility, but do not
-- leave an operator-maintained path beside the managed lifecycle source.
REVOKE INSERT, UPDATE, DELETE ON operations.eol_product_map FROM operations_app;
REVOKE USAGE, SELECT ON SEQUENCE operations.eol_product_map_id_seq
    FROM operations_app;

-- The old queue exists only to ask an operator to maintain mappings. Managed
-- rules supersede it for the selected family set, and the expensive broad
-- candidate scan is expressly out of scope for the automated lifecycle path.
DROP MATERIALIZED VIEW IF EXISTS operations.v_eol_mapping_candidates;

COMMENT ON TABLE intel.eol_managed_product_rules IS
    'Read-only, migration-seeded lifecycle family rules. The rules identify '
    'known product families but never store a lifecycle date or build map.';
