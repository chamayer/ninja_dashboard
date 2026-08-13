import os, sys
sys.path.insert(0, "/app")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
import django
django.setup()
from apps.core import views, models  # noqa: E402
import config.urls  # noqa: E402,F401
print("operations imports ok")
