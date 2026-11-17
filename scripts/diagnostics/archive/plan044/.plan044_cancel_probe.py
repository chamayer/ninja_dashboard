import os
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/app")
import django

django.setup()

from django.db import connection

with connection.cursor() as cursor:
    cursor.execute("SELECT pg_cancel_backend(%s)", [268393])
    print(f"cancelled={cursor.fetchone()[0]}")
