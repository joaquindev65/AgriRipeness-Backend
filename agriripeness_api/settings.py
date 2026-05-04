from pathlib import Path
from corsheaders.defaults import default_headers
import os
from datetime import timedelta
from dotenv import load_dotenv
import dj_database_url

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Manejo profesional de DEBUG
# IMPORTANTE: Por defecto False en producción, explícitamente True solo en dev
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")

# Seguridad
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "django-insecure-change-me-in-production-123456789")

# ALLOWED_HOSTS para Railway
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
# Agregar Railway host dinámicamente
if "RAILWAY_STATIC_URL" in os.environ:
    RAILWAY_HOST = os.environ["RAILWAY_STATIC_URL"].replace("https://", "").replace("http://", "")
    ALLOWED_HOSTS.append(RAILWAY_HOST)
ALLOWED_HOSTS.extend([
    "*.railway.app",
    "192.168.100.6",
    "192.168.1.158",
    "192.168.1.10"
])

# CSRF Trusted Origins
CSRF_TRUSTED_ORIGINS = os.environ.get(
    "CSRF_TRUSTED_ORIGINS",
    "https://*.railway.app"
).split(",")

# Configuración de la base de datos - Railway provee DATABASE_URL automáticamente
# dj_database_url.config() busca la variable DATABASE_URL primero
# Si no existe, usa el fallback (solo para desarrollo local)
DATABASES = {
    "default": dj_database_url.config(
        default=os.getenv(
            'DATABASE_URL',
            f"postgresql://{os.getenv('DB_USER', 'agriripeness_user')}:{os.getenv('DB_PASSWORD', 'agriripeness_pass')}@{os.getenv('DB_HOST', 'localhost')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'agriripeness_db')}"
        ),
        conn_max_age=600,
        conn_health_checks=True,
    )
}

# CORS profesional
if DEBUG:
    CORS_ALLOW_ALL_ORIGINS = True
else:
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = [
        "https://agriripeness-ejbgh2a3cgbxf9a7.westus3-01.azurewebsites.net",
        "http://localhost:8081",
        "http://127.0.0.1:8081",
    ]

CORS_ALLOW_HEADERS = list(default_headers) + ["content-type"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
    "users",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    # "react_native_middleware.ReactNativeMultipartFixMiddleware",  # Fix React Native multipart issues - COMENTADO TEMPORALMENTE
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # Servir archivos estáticos en producción
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "agriripeness_api.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # Agregar directorio de templates
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "agriripeness_api.wsgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"

USE_I18N = True
USE_L10N = True


TIME_ZONE = "America/Santiago"

USE_I18N = True

USE_TZ = True


STATIC_URL = "static/"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",  # JWT para admins
        "users.authentication.ApiKeyAuthentication",  # API Key para workers offline
        "users.authentication.DeviceTokenAuthentication",  # Device Token para PIN offline
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=60),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Configuración de archivos de media
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Configuración de archivos estáticos (Whitenoise para Railway)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Configuración de Cache - Adaptativa según disponibilidad de Redis
# CRÍTICO: Solo usar Redis si REDIS_URL está configurado, sino LocMem
REDIS_URL = os.environ.get('REDIS_URL', None)

if REDIS_URL:
    # Redis disponible (producción con Redis o desarrollo con USE_REDIS=true)
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': REDIS_URL,
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
                'CONNECTION_POOL_KWARGS': {
                    'max_connections': 50,
                    'socket_keepalive': True,
                    'socket_keepalive_options': {},
                },
            }
        }
    }
    RATELIMIT_ENABLE = True
    print(f"[CONFIG] Usando Redis para cache | URL: {REDIS_URL[:20]}...")
else:
    # Sin Redis: usar cache local en memoria (funciona en dev y prod sin Redis)
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
            'LOCATION': 'agriripeness-cache',
        }
    }
    RATELIMIT_ENABLE = True
    print("[CONFIG] Usando cache local (LocMem) - Redis no disponible")

# Configuración de Rate Limiting
RATELIMIT_USE_CACHE = 'default'

# Configuración de logging - Adaptativo según entorno
# En producción (Railway), solo usar consola porque el filesystem es efímero
# En desarrollo local, usar archivo + consola
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

# Crear directorio de logs solo si estamos en desarrollo
if DEBUG and not os.path.exists(LOGS_DIR):
    try:
        os.makedirs(LOGS_DIR)
    except OSError:
        pass  # Si falla, usar solo consola

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {name} {module}.{funcName} - {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
        'sync': {
            'format': '[SYNC] {asctime} [{levelname}] {message}',
            'style': '{',
            'datefmt': '%Y-%m-%d %H:%M:%S',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'sync_console': {
            'class': 'logging.StreamHandler',
            'formatter': 'sync',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'users.services': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'sync': {
            'handlers': ['sync_console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}

# Agregar handler de archivo solo en desarrollo
if DEBUG and os.path.exists(LOGS_DIR):
    LOGGING['handlers']['sync_file'] = {
        'class': 'logging.FileHandler',
        'filename': os.path.join(LOGS_DIR, 'sync_operations.log'),
        'formatter': 'sync',
        'encoding': 'utf-8',
    }
    # Agregar handler de archivo al logger sync
    LOGGING['loggers']['sync']['handlers'].append('sync_file')

# Incrementar el límite de tamaño de carga
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10 MB

# ========== CONFIGURACIÓN DE EMAIL ==========

# SendGrid API Key (producción) - USAR HTTP API, NO SMTP
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY', '')

# Email por defecto del remitente
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL', 'agriripeness@gmail.com')

# Email del superadmin para notificaciones
SUPERADMIN_EMAIL = os.environ.get('SUPERADMIN_EMAIL', 'agriripeness@gmail.com')

# URL del frontend para los enlaces de restablecimiento
FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:3000')

# SIEMPRE usar consola backend (los emails se envían manualmente con SendGrid HTTP API)
# Railway BLOQUEA puertos SMTP (25, 587, 465) por seguridad
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

if SENDGRID_API_KEY:
    print("[CONFIG] SendGrid HTTP API configurado (NO usar SMTP)")
else:
    print("[CONFIG] SendGrid NO configurado - emails solo en consola")
