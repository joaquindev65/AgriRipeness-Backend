from users import views
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from rest_framework.routers import DefaultRouter
from .views import WorkerProfileViewSet
# from simple_upload import react_native_image_upload  # Comentado temporalmente

# Configuración del router para ViewSets
router = DefaultRouter()
router.register(r'analysis-records', views.AnalysisRecordViewSet, basename='analysisrecord')
router.register(r'api-keys', views.WorkerAPIKeyViewSet, basename='api-keys')
router.register(r'workers', views.WorkerViewSet, basename='workers')
router.register(r'workerprofiles', WorkerProfileViewSet, basename='workerprofile')


urlpatterns = [
    # ========== ENDPOINTS DE AUTENTICACIÓN ==========
    path("login/", views.login, name="login"),  # POST /api/login/ - Login con EMAIL + password
    path("refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("register/", views.register, name="register"),
    path("me/", views.profile, name="profile"),  # GET /api/me/ - Info del usuario autenticado
    
    # ALIAS para compatibilidad con frontend (mismo endpoint, diferente ruta)
    path("auth/login/", views.login, name="auth_login"),  # POST /api/auth/login/ - Alias de /api/login/
    path("auth/change-password/", views.password_change, name="auth_password_change"),  # POST /api/auth/change-password/ - Alias
    path("users/me/", views.profile, name="users_me"),  # GET /api/users/me/ - Alias legacy de /api/me/

    # ========== ENDPOINTS DE WORKERS ==========
    path("validate-api-key/", views.validate_api_key, name="validate_api_key"),
    path("workers/login/", views.worker_login, name="worker_login"),  # POST /api/workers/login/ - Login worker con EMAIL + PIN
    path("workers/activation-list/", views.get_workers_for_activation, name="activation_list"),
    path("workers/set-pin/", views.set_worker_pin, name="set_worker_pin"),
    path("workers/activate-device/", views.activate_device, name="activate_device"),
    path("workers/validate-device/", views.validate_device_token, name="validate_device"),
    path("workers/regenerate-device-token/", views.regenerate_device_token, name="regenerate_device_token"),

    # ========== SISTEMA SIMPLE CON API KEY CORTA ==========
    path("workers/create-simple/", views.create_simple_worker, name="create_simple_worker"),  # POST - Crear worker con API key corta
    path("workers/validate-key/", views.validate_simple_key, name="validate_simple_key"),  # POST - Validar API key corta
    path("workers/<int:pk>/api-key/", views.get_worker_api_key, name="get_worker_api_key"),  # GET - Obtener API key de worker

    # ========== ENDPOINTS DE PASSWORD MANAGEMENT ==========
    path("password-reset/request/", views.password_reset_request, name="password_reset_request"),
    path("password-reset/confirm/", views.password_reset_confirm, name="password_reset_confirm"),
    path("password-reset/validate-token/", views.password_reset_validate_token, name="password_reset_validate_token"),
    path("password-change/", views.password_change, name="password_change"),  # POST /api/password-change/ - Legacy

    # NUEVO: Vista web para generar API keys (solo para staff)
    path("generate-api-key/", views.generate_worker_api_key_view, name="generate_api_key"),

    # Endpoints legacy de historial (mantener para compatibilidad)
    path("history/", views.history, name="history"),
    path("history/<int:pk>/", views.history_detail, name="history_detail"),

    # NUEVO: Endpoint específico para imágenes base64 de React Native
    path("analysis-records/base64/", views.create_analysis_record_base64, name="analysis_base64"),

    # NUEVO: Endpoint SIMPLE para React Native con soporte para API key (workers offline)
    path("upload/simple/", views.upload_simple, name="upload_simple"),

    # ========== v2.0: ENDPOINTS DE SESIONES (6+ FOTOS) ==========
    path("sessions/upload/", views.upload_session, name="upload_session"),  # POST - Subir sesión completa con detección server-side
    path("sessions/<str:session_id>/summary/", views.session_summary, name="session_summary"),  # GET - Obtener resumen de sesión

    # NUEVO: Endpoint para solicitud de acceso como administrador
    path("admins/request/", views.admin_request_view, name="admin_request"),

    # Incluir las rutas del router para el ViewSet
    path("", include(router.urls)),
]
