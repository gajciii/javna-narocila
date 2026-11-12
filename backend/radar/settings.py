import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'local-demo-only-razpisni-radar-change-before-hosting')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],backend,testserver').split(',')]
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.auth', 'rest_framework', 'tenders']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.middleware.common.CommonMiddleware', 'tenders.middleware.LocalOnlyMutationMiddleware']
ROOT_URLCONF = 'radar.urls'
WSGI_APPLICATION = 'radar.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ.get('DATABASE_PATH', str(BASE_DIR / 'db.sqlite3')), 'OPTIONS': {'timeout': 20}}}
LANGUAGE_CODE = 'sl'
TIME_ZONE = 'Europe/Ljubljana'
USE_I18N = True
USE_TZ = True
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
APPEND_SLASH = False
MEDIA_ROOT = Path(os.environ.get('MEDIA_ROOT', str(BASE_DIR / 'media')))
DEMO_DOCUMENTS_ROOT = BASE_DIR / 'demo_documents'
REST_FRAMEWORK = {'DEFAULT_AUTHENTICATION_CLASSES': [], 'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'], 'UNAUTHENTICATED_USER': None, 'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer']}
DATA_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 12 * 1024 * 1024
OPENAI_MODEL = os.environ.get('OPENAI_MODEL', 'gpt-4.1-mini')
OPENROUTER_MODEL = os.environ.get('OPENROUTER_MODEL', 'openai/gpt-6-luna')
DEMO_DATE = os.environ.get('DEMO_DATE', '')
