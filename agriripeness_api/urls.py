"""
URL configuration for agriripeness_api project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from django.http import HttpResponse, JsonResponse
from datetime import datetime
import os


def health_check(request):
    """Health check endpoint para verificar que el servidor está funcionando"""
    return JsonResponse({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "AgriRipeness Backend",
        "version": "1.0.0"
    })


def test_password_reset_view(request):
    """Vista simple para servir la página de pruebas"""
    html_path = os.path.join(settings.BASE_DIR, 'test_password_reset.html')
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        return HttpResponse(content, content_type='text/html')
    except FileNotFoundError:
        return HttpResponse("Archivo de pruebas no encontrado", status=404)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/health/', health_check, name='health'),  # ← NUEVO: Health check endpoint
    path('api/', include('users.urls')),  # Mantener como 'api/' para evitar duplicación
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('test-password-reset/', test_password_reset_view, name='test_password_reset'),
]

# Servir archivos de media en desarrollo
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
