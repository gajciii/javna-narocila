import sys
import os
from urllib.parse import urlsplit, parse_qs, unquote
from pathlib import Path
from dotenv import load_dotenv
from .deployment import public_origin

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR.parent / '.env')
PUBLIC_APP_URL, PUBLIC_APP_HOST = public_origin(os.environ.get('PUBLIC_APP_URL', ''))
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'local-demo-only-razpisni-radar-change-before-hosting')
DEBUG = os.environ.get('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1],backend,testserver').split(',')]
if PUBLIC_APP_HOST and PUBLIC_APP_HOST not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(PUBLIC_APP_HOST)
INSTALLED_APPS = ['django.contrib.contenttypes', 'django.contrib.auth', 'django.contrib.sessions', 'rest_framework', 'tenders']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware', 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'tenders.middleware.HostedAccessMiddleware',
    'tenders.middleware.LocalOnlyMutationMiddleware']
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_SECURE = os.environ.get('SESSION_COOKIE_SECURE', '0') == '1'
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE
CSRF_TRUSTED_ORIGINS = [value.strip() for value in os.environ.get('DJANGO_CSRF_TRUSTED_ORIGINS',
    PUBLIC_APP_URL or 'http://localhost:5174,http://127.0.0.1:5174').split(',') if value.strip()]
if PUBLIC_APP_URL and PUBLIC_APP_URL not in CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS.append(PUBLIC_APP_URL)
HOSTED_REQUIRE_LOGIN = os.environ.get('HOSTED_REQUIRE_LOGIN', '0') == '1'
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https') if os.environ.get('DJANGO_TRUST_PROXY_SSL', '0') == '1' else None
SECURE_SSL_REDIRECT = os.environ.get('DJANGO_SECURE_SSL_REDIRECT', '0') == '1'
SECURE_REDIRECT_EXEMPT = [r'^api/health$']
ROOT_URLCONF = 'radar.urls'
WSGI_APPLICATION = 'radar.wsgi.application'
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ.get('DATABASE_PATH', str(BASE_DIR / 'db.sqlite3')), 'OPTIONS': {'timeout': 20}}}
if os.environ.get('DATABASE_URL'):
    db = urlsplit(os.environ['DATABASE_URL'])
    if db.scheme not in ('postgres', 'postgresql'):
        raise ValueError('DATABASE_URL mora biti PostgreSQL URL.')
    DATABASES = {'default': {'ENGINE': 'django.db.backends.postgresql', 'NAME': unquote(db.path.lstrip('/')),
        'USER': unquote(db.username or ''), 'PASSWORD': unquote(db.password or ''), 'HOST': db.hostname,
        'PORT': db.port or 5432, 'CONN_MAX_AGE': 30,
        'OPTIONS': {k: v[-1] for k, v in parse_qs(db.query).items() if k in ('sslmode', 'connect_timeout')}}}
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
SUBMISSION_REVIEW_MODEL = os.environ.get('SUBMISSION_REVIEW_MODEL', 'openai/gpt-6.1-terra')
DEMO_DATE = os.environ.get('DEMO_DATE', '')
PIPELINE_REMOTE = os.environ.get('PIPELINE_REMOTE', '0') == '1'
# Coolify may inject optional variables as empty strings rather than omit them.
PIPELINE_MAX_DOWNLOAD = int(os.environ.get('PIPELINE_MAX_DOWNLOAD', '').strip() or 8 * 1024**3)
PIPELINE_MAX_EXPANDED = int(os.environ.get('PIPELINE_MAX_EXPANDED', '').strip() or 32 * 1024**3)
PIPELINE_MAX_DOCUMENT = int(os.environ.get('PIPELINE_MAX_DOCUMENT', '').strip() or 512 * 1024**2)
PIPELINE_MAX_PAGES = int(os.environ.get('PIPELINE_MAX_PAGES', '').strip() or 10000)
# Off by default: web requests also extract text and must not wait on OCR. Pipeline workers enable it.
PIPELINE_OCR = os.environ.get('PIPELINE_OCR', '0') == '1'
PIPELINE_OCR_LANGUAGES = os.environ.get('PIPELINE_OCR_LANGUAGES', '').strip() or 'slv+eng'
PIPELINE_OCR_DPI = int(os.environ.get('PIPELINE_OCR_DPI', '').strip() or 200)
PIPELINE_OCR_MAX_PAGES = int(os.environ.get('PIPELINE_OCR_MAX_PAGES', '').strip() or 40)
PIPELINE_OCR_PAGE_TIMEOUT = int(os.environ.get('PIPELINE_OCR_PAGE_TIMEOUT', '').strip() or 60)
PIPELINE_OCR_BUDGET = int(os.environ.get('PIPELINE_OCR_BUDGET', '').strip() or 240)
PIPELINE_S3_ENDPOINT = os.environ.get('PIPELINE_S3_ENDPOINT', '')
PIPELINE_S3_BUCKET = os.environ.get('PIPELINE_S3_BUCKET', 'razpizi-documents')
PIPELINE_S3_ACCESS_KEY = os.environ.get('PIPELINE_S3_ACCESS_KEY', '')
PIPELINE_S3_SECRET_KEY = os.environ.get('PIPELINE_S3_SECRET_KEY', '')

# Email provider is selected explicitly; credentials stay on the server.
EMAIL_PROVIDER = os.environ.get('EMAIL_PROVIDER', 'smtp').strip().lower()
RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '')
EMAIL_BACKEND = os.environ.get('EMAIL_BACKEND', 'django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = os.environ.get('EMAIL_HOST', '')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '').strip() or 587)
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', '1') == '1'
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', '0') == '1'
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', '')

# Set to 0 only for an explicitly public, anonymous demo. Accounts are required by default.
# Tests call the API anonymously unless they enable accounts with override_settings.
ACCOUNT_REQUIRE_LOGIN = os.environ.get('ACCOUNT_REQUIRE_LOGIN', '0' if 'test' in sys.argv[1:2] else '1') == '1'
# Slow follow-up work (AI relevance, improvement suggestions) runs after the response in a thread.
# Tests run it inline so assertions see the finished result.
BACKGROUND_TASKS_INLINE = os.environ.get('BACKGROUND_TASKS_INLINE', '1' if 'test' in sys.argv[1:2] else '0') == '1'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
