"""
Utilidades para la app users.
Incluye funciones auxiliares para generación de API keys, validaciones, etc.
"""

import random
import string
from django.contrib.auth.models import User


def generate_short_api_key():
    """
    Genera una API Key corta en formato AGR-WK-XXXXXX.

    Formato:
    - Prefijo: AGR-WK-
    - Código aleatorio: 6 caracteres alfanuméricos (A-Z, 0-9)
    - Total: 13 caracteres

    Ejemplo: AGR-WK-A1B2C3

    Returns:
        str: API Key generada en formato AGR-WK-XXXXXX
    """
    chars = string.ascii_uppercase + string.digits  # A-Z, 0-9
    random_part = ''.join(random.choices(chars, k=6))
    return f"AGR-WK-{random_part}"


def generate_unique_username(email=None, first_name=None, last_name=None):
    """
    Genera un username único basado en email o nombres.

    Estrategia:
    1. Intenta usar email (parte antes del @)
    2. Si no hay email, usa first_name.last_name
    3. Si el username ya existe, agrega un número incremental

    Args:
        email (str, optional): Email del usuario
        first_name (str, optional): Nombre del usuario
        last_name (str, optional): Apellido del usuario

    Returns:
        str: Username único

    Examples:
        >>> generate_unique_username(email='joaquin@agri.com')
        'joaquin'

        >>> generate_unique_username(first_name='Joaquin', last_name='Gonzalez')
        'joaquin.gonzalez'
    """
    if email:
        # Usar parte antes del @ como base
        base_username = email.split('@')[0].lower()
    elif first_name and last_name:
        # Usar first.last como base
        base_username = f"{first_name.lower()}.{last_name.lower()}"
    elif first_name:
        # Solo nombre
        base_username = first_name.lower()
    else:
        # Fallback: generar uno aleatorio
        base_username = f"user{random.randint(1000, 9999)}"

    # Limpiar caracteres especiales y espacios
    base_username = base_username.replace(' ', '_')
    base_username = ''.join(c for c in base_username if c.isalnum() or c in '._-')

    # Verificar si el username ya existe
    username = base_username
    counter = 1

    while User.objects.filter(username=username).exists():
        # Agregar número incremental
        username = f"{base_username}{counter}"
        counter += 1

    return username


def validate_api_key_format(api_key):
    """
    Valida el formato de una API Key simple.

    Args:
        api_key (str): API Key a validar

    Returns:
        bool: True si el formato es válido, False si no

    Examples:
        >>> validate_api_key_format('AGR-WK-A1B2C3')
        True

        >>> validate_api_key_format('invalid')
        False
    """
    if not api_key or not isinstance(api_key, str):
        return False

    # Verificar longitud exacta
    if len(api_key) != 13:
        return False

    # Verificar prefijo
    if not api_key.startswith('AGR-WK-'):
        return False

    # Verificar parte aleatoria (6 caracteres alfanuméricos)
    random_part = api_key[7:]  # Caracteres después de 'AGR-WK-'

    if len(random_part) != 6:
        return False

    # Verificar que sean solo letras mayúsculas y dígitos
    if not all(c in string.ascii_uppercase + string.digits for c in random_part):
        return False

    return True
