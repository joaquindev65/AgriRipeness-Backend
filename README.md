# AgriRipeness Backend API

Sistema de análisis de madurez de frutas cítricas con autenticación multirol y gestión de workers.

[![Django](https://img.shields.io/badge/Django-5.2.7-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.16.1-blue.svg)](https://www.django-rest-framework.org/)
[![Python](https://img.shields.io/badge/Python-3.12+-yellow.svg)](https://www.python.org/)

---

## Descripción

Backend API REST para la aplicación móvil **AgriRipeness**, diseñada para análisis de madurez de frutas cítricas mediante visión por computadora. Proporciona:

- Autenticación multirol (Admin/Worker)
- Gestión de API keys para dispositivos offline
- Detección automática de frutas usando Hugging Face AI
- Análisis de madurez basado en colores RGB/HSV

### Stack Tecnológico

| Componente | Tecnología |
|------------|------------|
| Framework | Django 5.2.7 + Django REST Framework 3.16.1 |
| Base de Datos | PostgreSQL (producción) / SQLite (desarrollo) |
| Autenticación | JWT (djangorestframework-simplejwt) |
| Cache | Redis (opcional) / LocMemCache (fallback) |
| IA | Hugging Face API |
| Deploy | Railway |

---

## Instalación

### Prerrequisitos

- Python 3.12+
- pip / virtualenv
- PostgreSQL (opcional para desarrollo)
- Git

### Pasos

```bash
# 1. Clonar repositorio
git clone <url-del-repositorio>
cd django_backend

# 2. Crear entorno virtual
python -m venv .venv

# Windows PowerShell
.\.venv\Scripts\Activate.ps1

# Linux/Mac
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env con los valores apropiados

# 5. Aplicar migraciones
python manage.py migrate

# 6. Crear superusuario
python manage.py createsuperuser

# 7. Ejecutar servidor de desarrollo
python manage.py runserver
```

### Verificación

- API: http://localhost:8000/api/
- Admin: http://localhost:8000/admin/
- Health Check: http://localhost:8000/api/health/

---

## Estructura del Proyecto

```
django_backend/
├── agriripeness_api/          # Configuración principal Django
│   ├── settings.py            # Configuración (cache, auth, etc.)
│   ├── urls.py                # URLs principales
│   └── wsgi.py                # WSGI config
│
├── users/                     # Aplicación principal
│   ├── models.py              # Modelos (User, AnalysisRecord, APIKey)
│   ├── views.py               # Vistas de API
│   ├── serializers.py         # Serializers DRF
│   ├── urls.py                # URLs de la app
│   ├── authentication.py      # Backends de autenticación
│   └── services.py            # Servicios (HuggingFace, email)
│
├── docs/                      # Documentación técnica
├── templates/                 # Templates Django admin
├── logs/                      # Logs de aplicación
│
├── requirements.txt           # Dependencias Python
├── .env.example               # Plantilla de variables de entorno
├── Procfile                   # Configuración Railway/Heroku
└── manage.py                  # CLI Django
```

---

## API Endpoints Principales

### Autenticación

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| POST | `/api/auth/login/` | Login para Admin |
| POST | `/api/workers/login/` | Login para Workers (password o PIN) |
| POST | `/api/auth/change-password/` | Cambiar contraseña |
| POST | `/api/refresh/` | Refrescar token JWT |
| GET | `/api/me/` | Obtener usuario actual |

### Workers

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/workers/` | Listar workers |
| POST | `/api/workers/` | Crear worker |
| GET | `/api/workers/{id}/` | Detalle de worker |
| POST | `/api/workers/{id}/regenerate-api-key/` | Regenerar API key |

### Análisis

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/analysis-records/` | Listar análisis |
| POST | `/api/analysis-records/` | Crear análisis |
| GET | `/api/analysis-records/{id}/` | Detalle de análisis |

Para documentación completa, ver [docs/API_ENDPOINTS_DOCUMENTATION.md](docs/API_ENDPOINTS_DOCUMENTATION.md).

---

## Autenticación

### JWT Tokens

El sistema usa JWT para autenticación:

- **Access Token**: Válido por 1 hora
- **Refresh Token**: Válido por 7 días

```http
Authorization: Bearer <access_token>
```

### API Keys (Workers Offline)

Workers pueden usar API keys para autenticación sin conexión:

```http
X-API-Key: AGR-WORKER-abc123...
```

---

## Configuración

### Variables de Entorno

Ver `.env.example` para todas las variables disponibles.

**Variables críticas:**

| Variable | Descripción | Requerido |
|----------|-------------|-----------|
| `DJANGO_SECRET_KEY` | Clave secreta Django | Sí |
| `DEBUG` | Modo debug (False en producción) | No |
| `DATABASE_URL` | URL de conexión PostgreSQL | Sí (prod) |
| `SENDGRID_API_KEY` | API key de SendGrid | Sí |
| `HF_API_TOKEN` | Token de Hugging Face | Sí |

### Cache

El sistema implementa cache adaptativo:

- Si `REDIS_URL` está definido: usa Redis
- Si no: usa LocMemCache automáticamente

---

## Deployment

### Railway

1. Conectar repositorio a Railway
2. Configurar variables de entorno
3. Railway detecta automáticamente el Procfile
4. Deploy automático en cada push

### Variables Railway

```bash
DATABASE_URL=postgresql://...     # Auto-provisto
DJANGO_SECRET_KEY=<generar>       # Requerido
ALLOWED_HOSTS=*.railway.app       # Configurar
```

### Health Check

```bash
curl https://<tu-app>.railway.app/api/health/
```

---

## Testing

```bash
# Tests unitarios
python manage.py test

# Tests específicos
python manage.py test users.tests
```

---

## Documentación Adicional

| Documento | Descripción |
|-----------|-------------|
| [CHANGELOG.md](CHANGELOG.md) | Historial de cambios |
| [docs/API_ENDPOINTS_DOCUMENTATION.md](docs/API_ENDPOINTS_DOCUMENTATION.md) | Documentación API completa |
| [docs/ARQUITECTURA_AUTH.md](docs/ARQUITECTURA_AUTH.md) | Arquitectura de autenticación |
| [docs/RAILWAY_DEPLOYMENT_INSTRUCTIONS.md](docs/RAILWAY_DEPLOYMENT_INSTRUCTIONS.md) | Guía de deployment |
| [docs/DEUDA_TECNICA.md](docs/DEUDA_TECNICA.md) | Deuda técnica y mejoras pendientes |

---

## Licencia

Este proyecto fue desarrollado como parte del Capstone 005D.

---

**Versión**: 1.2.1
**Última actualización**: Diciembre 2025
