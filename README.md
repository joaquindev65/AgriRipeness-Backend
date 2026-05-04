# AgriRipeness API & Inference Backend 🍊

AgriRipeness Backend es el motor lógico y la API RESTful (desarrollada con **Django** y **Python 3.12**) que da soporte a la aplicación móvil AgriRipeness. 

Este sistema no solo gestiona la autenticación estructurada y la organización de los usuarios, sino que está diseñado para recibir, registrar y organizar los datos de inferencia provenientes de modelos de visión computacional (YOLOv8) orientados a la agricultura.

## 🚀 Arquitectura y Funcionalidades

*   **Gestión de Autenticación Híbrida:** Implementación de autenticación basada en tokens y un sistema robusto de API Keys (`simpleApiKeyAuth`) para la comunicación segura con dispositivos de terreno.
*   **Sistema Multi-Tenancy Básico:** Estructuración de datos jerárquica a través de organizaciones (`Organization`) para agrupar trabajadores y administradores.
*   **Gestión de Registros Agrícolas:** Modelado de la base de datos para almacenar metadatos de análisis (`AnalysisRecord`), incluyendo número de foto, posición (cuartel/hilera) y resultados del modelo de IA.
*   **Comandos de Gestión (CLI):** Scripts personalizados de Django (`assign_roles.py`, `create_superuser_if_missing.py`) para la automatización de la infraestructura en despliegues automatizados.
*   **Utilidades de Notificación:** Sistema integrado para la verificación y envío de correos electrónicos (`email_utils.py`).

## 🛠️ Stack Tecnológico & Entorno

*   **Core:** Python 3.12, Django, Django REST Framework.
*   **Gestión de Dependencias:** Entorno optimizado utilizando `uv` (resolución ultrarrápida de dependencias).
*   **Base de Datos:** PostgreSQL (preparado).
*   **Docker & DevOps:** Contenedores gestionados vía `docker-compose.yml`.
*   **Despliegue Cloud-Ready:** Configuración nativa para despliegue PaaS usando Nixpacks (`nixpacks.toml`), Railway (`railway.json`) y Gunicorn (`Procfile`, `wsgi.py`).

## 📁 Estructura del Proyecto

El repositorio sigue las convenciones de separación de aplicaciones de Django:

*   `agriripeness_api/`: Directorio principal de configuración (Settings, URLs principales, ASGI/WSGI).
*   `users/`: Aplicación principal que contiene la lógica de negocio:
    *   `models.py` & `serializers.py`: Definición de perfiles, organizaciones y registros de análisis.
    *   `views.py` & `urls.py`: Endpoints de la API REST.
    *   `services.py` & `utils.py`: Capa de servicios para la lógica de IA y utilidades de la aplicación.
    *   `management/commands/`: Automatización de tareas de administración.
*   `templates/admin/`: Personalización del panel de administración de Django (ej. generación de API Keys).

## 💻 Instalación y Uso Local

### Opción A: Despliegue con Docker (Recomendado)
El proyecto incluye un entorno Docker listo para usar.
```bash
# 1. Clonar el repositorio
git clone [https://github.com/joaquindev65/AgriRipeness-Backend.git](https://github.com/joaquindev65/AgriRipeness-Backend.git)
cd AgriRipeness-Backend

# 2. Levantar los servicios (API y Base de Datos)
docker-compose up --build

# 3. Aplicar migraciones iniciales
docker-compose exec web python manage.py migrate

# 4. Crear superusuario (usando script automatizado)
docker-compose exec web python manage.py create_superuser_if_missing