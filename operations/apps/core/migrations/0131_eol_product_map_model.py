"""Migration 0131 -- give the EOL mapping table a Django model, state only.

`operations.eol_product_map` already exists: SQL migration 078 created it, and
that migration is deployed. This migration therefore declares the model to
Django's state *without* issuing any DDL. A plain CreateModel would fail on the
existing table.

The table needed a model because it is operator-maintained data with no operator
surface -- 078 shipped the table and nothing to edit it with, so mappings could
only be added by hand in SQL. This plus the admin registration closes that.

Column parity with 078 is deliberate and load-bearing, since nothing enforces it
across the two migration runners: id bigserial, tenant_id bigint, raw_pattern
text, eol_product text, priority int, notes text, created_at, updated_at. The
FK to intel.eol_products(name) and the unique index live in 078 and are not
restated here; Django does not need them in state to read and write the table.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('operations', '0130_finding_type_subject_scope'),
    ]

    operations = [
      migrations.SeparateDatabaseAndState(
        database_operations=[],
        state_operations=[
        migrations.CreateModel(
            name='EolProductMap',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('tenant_id', models.BigIntegerField(default=1)),
                ('raw_pattern', models.CharField(help_text="SQL ILIKE pattern matched against catalog.products.canonical_name. Anchor it: 'google chrome' or 'mozilla firefox%', not '%chrome%'. A loose pattern is how a title inherits the wrong product's end-of-life date.", max_length=255)),
                ('eol_product', models.CharField(help_text="endoflife.date product name, e.g. 'chrome', 'notepad-plus-plus'.", max_length=255)),
                ('priority', models.IntegerField(default=100, help_text='Lower wins when several patterns match one title.')),
                ('notes', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'EOL product mapping',
                'verbose_name_plural': 'EOL product mappings',
                'db_table': 'eol_product_map',
                'ordering': ('priority', 'raw_pattern'),
            },
        ),
        ],
      ),
    ]
