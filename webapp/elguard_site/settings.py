from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# the data prepared by pipeline/export_site_data.py
DATA_DIR = BASE_DIR.parent / "site" / "data"

SECRET_KEY = "dev-only-change-me"
DEBUG = True
ALLOWED_HOSTS = ["127.0.0.1", "localhost"]

INSTALLED_APPS = ["django.contrib.staticfiles", "dashboard"]
MIDDLEWARE = ["django.middleware.common.CommonMiddleware"]
ROOT_URLCONF = "elguard_site.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": ["django.template.context_processors.request"]},
}]
DATABASES = {}          # no database needed: the site reads JSON files
STATIC_URL = "static/"
USE_TZ = True
