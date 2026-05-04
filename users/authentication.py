"""
Custom authentication classes for the AgriRipeness API.
"""
from rest_framework import authentication
from rest_framework import exceptions
from .models import WorkerAPIKey, ActivatedDevice


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """
    Autenticación mediante header X-API-Key.

    Este método soporta DOS formatos de API keys:
    1. Sistema COMPLEJO: AGR-WORKER-XXXX-XXXX-XXXX (25 chars) - Hasheado en DB
    2. Sistema SIMPLE: AGR-WK-XXXXXX (13 chars) - Texto plano en UserProfile

    El header debe ser:
    X-API-Key: AGR-WORKER-XXXX-XXXX-XXXX  (sistema complejo)
    X-API-Key: AGR-WK-XXXXXX              (sistema simple)
    """

    keyword = 'X-API-Key'

    def authenticate(self, request):
        """
        Intenta autenticar el request usando el header X-API-Key.

        Detecta automáticamente el formato y aplica el método de validación correspondiente.

        Returns:
            tuple: (user, auth) si la autenticación es exitosa
            None: si no se proporciona API key (para probar siguiente método)

        Raises:
            AuthenticationFailed: si la API key es inválida
        """
        # Obtener API key desde headers
        # Django convierte 'X-API-Key' a 'HTTP_X_API_KEY' en request.META
        api_key = request.META.get('HTTP_X_API_KEY')

        # Si no hay API key, retornar None para que DRF pruebe el siguiente método
        if not api_key:
            return None

        # DETECTAR FORMATO Y VALIDAR
        # Sistema SIMPLE: AGR-WK-XXXXXX (13 caracteres)
        if len(api_key) == 13 and api_key.startswith('AGR-WK-'):
            return self._authenticate_simple_key(api_key)

        # Sistema COMPLEJO: AGR-WORKER-XXXX-XXXX-XXXX (25 caracteres)
        elif len(api_key) == 25 and api_key.startswith('AGR-WORKER-'):
            return self._authenticate_complex_key(api_key)

        # Formato no reconocido
        else:
            raise exceptions.AuthenticationFailed('Formato de API key inválido')

    def _authenticate_simple_key(self, api_key):
        """
        Autenticación con API Key SIMPLE (AGR-WK-XXXXXX).

        Busca directamente en UserProfile.api_key_short (texto plano).

        Args:
            api_key (str): API Key en formato simple

        Returns:
            tuple: (user, 'simple_api_key')

        Raises:
            AuthenticationFailed: si la key es inválida
        """
        from .models import UserProfile

        try:
            # Buscar usuario por API Key simple
            profile = UserProfile.objects.select_related('user').get(
                api_key_short=api_key,
                role='worker',
                user__is_active=True
            )

            # Retornar el usuario asociado
            # El segundo valor indica el tipo de autenticación
            return (profile.user, 'simple_api_key')

        except UserProfile.DoesNotExist:
            raise exceptions.AuthenticationFailed('API key simple inválida o usuario inactivo')

    def _authenticate_complex_key(self, api_key):
        """
        Autenticación con API Key COMPLEJA (AGR-WORKER-XXXX-XXXX-XXXX).

        Valida contra WorkerAPIKey (hasheado en DB).

        Args:
            api_key (str): API Key en formato complejo

        Returns:
            tuple: (user, api_key_obj)

        Raises:
            AuthenticationFailed: si la key es inválida
        """
        # Validar la API key compleja (método existente)
        api_key_obj = WorkerAPIKey.validate_key(api_key)

        if api_key_obj is None:
            raise exceptions.AuthenticationFailed('API key compleja inválida o inactiva')

        # Actualizar timestamp de último uso
        from django.utils import timezone
        api_key_obj.last_used_at = timezone.now()
        api_key_obj.save(update_fields=['last_used_at'])

        # Retornar el usuario asociado a la API key
        return (api_key_obj.user, api_key_obj)

    def authenticate_header(self, request):
        """
        Retorna el string que se usará en el header WWW-Authenticate
        cuando la autenticación falla.
        """
        return self.keyword


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    """
    Autenticación mediante header X-Device-Token.

    Este método permite a workers offline autenticarse usando
    device tokens generados durante la activación del dispositivo con PIN.

    El header debe ser:
    X-Device-Token: <token-generado-durante-activacion>
    """

    keyword = 'X-Device-Token'

    def authenticate(self, request):
        """
        Intenta autenticar el request usando el header X-Device-Token.

        Returns:
            tuple: (user, device) si la autenticación es exitosa
            None: si no se proporciona device token (para probar siguiente método)

        Raises:
            AuthenticationFailed: si el device token es inválido o inactivo
        """
        # Obtener device token desde headers
        # Django convierte 'X-Device-Token' a 'HTTP_X_DEVICE_TOKEN' en request.META
        device_token = request.META.get('HTTP_X_DEVICE_TOKEN')

        # Si no hay device token, retornar None para que DRF pruebe el siguiente método
        if not device_token:
            return None

        try:
            # Buscar dispositivo activo con este token
            device = ActivatedDevice.objects.select_related('worker').get(
                device_token=device_token,
                is_active=True
            )

            # Actualizar timestamp de último uso
            device.update_last_used()

            # Retornar el usuario (worker) asociado al dispositivo
            # El segundo valor (auth) es el objeto device para que esté disponible en request.auth
            return (device.worker, device)

        except ActivatedDevice.DoesNotExist:
            raise exceptions.AuthenticationFailed('Device token inválido o inactivo')

    def authenticate_header(self, request):
        """
        Retorna el string que se usará en el header WWW-Authenticate
        cuando la autenticación falla.
        """
        return self.keyword
