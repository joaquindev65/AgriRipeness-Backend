from django.db import models
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator, MinValueValidator, RegexValidator
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify
import os
import secrets
import hashlib
import uuid
import re
import random
from datetime import timedelta


# ========== ORGANIZATION MODEL (MULTI-TENANT) ==========

class Organization(models.Model):
    """
    Organización/Parcela para multi-tenancy.
    Cada Admin pertenece a una organización y gestiona sus propios workers.
    """
    name = models.CharField(
        max_length=200,
        verbose_name='Nombre de la Organización'
    )
    slug = models.SlugField(
        unique=True,
        verbose_name='Slug',
        help_text='Identificador único para URLs'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Creación'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Activa'
    )
    
    # Metadatos opcionales
    country = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='País'
    )
    region = models.CharField(
        max_length=100,
        blank=True,
        verbose_name='Región'
    )
    logo = models.ImageField(
        upload_to='organizations/',
        blank=True,
        null=True,
        verbose_name='Logo'
    )
    
    class Meta:
        verbose_name = 'Organización'
        verbose_name_plural = 'Organizaciones'
        ordering = ['name']
    
    def __str__(self):
        return self.name
    
    def save(self, *args, **kwargs):
        # Auto-generar slug si no existe
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


# ========== ADMIN REQUEST MODEL (REGISTRATION) ==========

# Validador para teléfonos internacionales
phone_regex = RegexValidator(
    regex=r'^\+?1?\d{8,15}$',
    message="Teléfono debe tener formato internacional (ej: +56912345678)"
)


class AdminRequest(models.Model):
    """
    Modelo para almacenar solicitudes de administradores.
    Los potenciales admins solicitan acceso y el superadmin aprueba/rechaza.
    """
    STATUS_CHOICES = [
        ('pending', 'Pendiente'),
        ('approved', 'Aprobado'),
        ('rejected', 'Rechazado'),
    ]
    
    # Datos del solicitante
    first_name = models.CharField(
        max_length=50,
        verbose_name='Nombre'
    )
    last_name = models.CharField(
        max_length=50,
        verbose_name='Apellido'
    )
    email = models.EmailField(
        unique=True,
        verbose_name='Email'
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        validators=[phone_regex],
        verbose_name='Teléfono',
        help_text='Formato internacional: +56912345678'
    )
    
    # Datos de la organización
    organization_name = models.CharField(
        max_length=100,
        verbose_name='Nombre de Organización'
    )
    country = models.CharField(
        max_length=100,
        verbose_name='País'
    )
    region = models.CharField(
        max_length=100,
        verbose_name='Región'
    )
    
    # Estado y metadatos
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
        verbose_name='Estado'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Solicitud'
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de Revisión'
    )
    reviewed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_admin_requests',
        verbose_name='Revisado por'
    )
    
    # Notas del revisor
    rejection_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name='Razón de Rechazo'
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name='Notas Internas'
    )
    
    # Relación con User creado (al aprobar)
    created_user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='admin_request',
        verbose_name='Usuario Creado'
    )
    
    # Anti-spam fields
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name='IP de Solicitud'
    )
    user_agent = models.TextField(
        blank=True,
        null=True,
        verbose_name='User Agent'
    )
    
    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Solicitud de Administrador'
        verbose_name_plural = 'Solicitudes de Administradores'
        indexes = [
            models.Index(fields=['email', 'status']),
            models.Index(fields=['status', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.email}) - {self.get_status_display()}"
    
    def get_full_name(self):
        """Retorna nombre completo del solicitante"""
        return f"{self.first_name} {self.last_name}"


# ========== UTILITY FUNCTIONS FOR ADMIN REQUEST ==========

def generate_unique_username(email, first_name, last_name):
    """
    Genera username único basado en email.
    
    Ejemplos:
    - juan.perez@parcela.com → juan.perez
    - juan.perez@parcela.com (duplicado) → juan.perez1
    - jp@mail.com → jp
    """
    # Tomar parte antes del @
    base_username = email.split('@')[0]
    
    # Limpiar caracteres no válidos
    base_username = re.sub(r'[^\w.-]', '', base_username)
    
    # Asegurar longitud mínima
    if len(base_username) < 3:
        base_username = f"{first_name.lower()}.{last_name.lower()}"
        base_username = re.sub(r'[^\w.-]', '', base_username)
    
    # Verificar si es único
    username = base_username
    counter = 1
    
    while User.objects.filter(username=username).exists():
        username = f"{base_username}{counter}"
        counter += 1
    
    return username


def generate_temp_password():
    """
    Genera contraseña temporal segura pero pronunciable.
    Ejemplo: Arbol2024Limon!
    """
    words = [
        'Arbol', 'Limon', 'Campo', 'Verde', 'Fruto',
        'Hoja', 'Flor', 'Sol', 'Agua', 'Tierra',
        'Cielo', 'Nube', 'Rio', 'Monte', 'Valle'
    ]
    numbers = str(random.randint(1000, 9999))
    symbols = ['!', '@', '#', '$', '%']
    
    word1 = random.choice(words)
    word2 = random.choice(words)
    symbol = random.choice(symbols)
    
    return f"{word1}{numbers}{word2}{symbol}"


class MediaTypeChoices(models.TextChoices):
    """Tipos de medios soportados para análisis"""
    IMAGE = 'image', 'Imagen'
    VIDEO = 'video', 'Video'

class SourceTypeChoices(models.TextChoices):
    """Fuente del medio analizado"""
    CAMERA = 'camera', 'Cámara'
    GALLERY = 'gallery', 'Galería'

class RipenessLevel(models.TextChoices):
    """Niveles de madurez de los limones"""
    UNRIPE = 'unripe', 'Verde (No maduro)'
    SEMI_RIPE = 'semi_ripe', 'Semi-maduro'
    RIPE = 'ripe', 'Maduro'
    OVERRIPE = 'overripe', 'Sobre-maduro'

class AnalysisRecord(models.Model):
    """
    Modelo principal para almacenar registros de análisis de medios.
    Soporta tanto imágenes como videos y almacena específicamente
    el conteo de limones detectados por nivel de madurez.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        related_name='analysis_records',
        verbose_name='Usuario',
        null=True,
        blank=True
    )

    local_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        db_index=True
     )

    # v2.0: Campos para agrupar análisis por sesión (árbol)
    session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        verbose_name='ID de Sesión',
        help_text='UUID de la sesión local del mobile (agrupa 6+ fotos del mismo árbol)'
    )

    photo_number = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='Número de Foto',
        help_text='Número de foto dentro de la sesión (1, 2, 3, 4, 5, 6, ...)'
    )

    # Tipo de medio y fuente
    media_type = models.CharField(
        max_length=10,
        choices=MediaTypeChoices.choices,
        default=MediaTypeChoices.IMAGE,
        verbose_name='Tipo de Medio'
    )
    source_type = models.CharField(
        max_length=10,
        choices=SourceTypeChoices.choices,
        default=SourceTypeChoices.GALLERY,
        verbose_name='Fuente del Medio'
    )
    
    # Archivos originales
    original_image = models.ImageField(
        upload_to="analysis/images/",
        validators=[FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'webp'])],
        blank=True,
        null=True,
        verbose_name='Imagen Original'
    )
    
    # Archivos procesados
    processed_image_url = models.URLField(
        blank=True, 
        null=True,
        verbose_name='URL Imagen Procesada'
    )
    
    # Conteo específico de limones - Campo principal
    total_lemons_count = models.PositiveIntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        verbose_name='Total de Limones Detectados'
    )
    
    # Datos adicionales del análisis
    detection_confidence = models.FloatField(
        blank=True,
        null=True,
        verbose_name='Confianza Promedio de Detección',
        help_text='Valor entre 0 y 1 indicando la confianza del modelo'
    )
    
    processing_time = models.FloatField(
        default=0.0,
        verbose_name='Tiempo de Procesamiento',
        help_text='Tiempo en segundos'
    )
    
    model_type = models.CharField(
        max_length=50,
        default='tensorflow_lite',
        verbose_name='Tipo de Modelo',
        help_text='Modelo usado para la detección'
    )
    
    # Metadatos adicionales
    analysis_metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Metadatos del Análisis',
        help_text='Información adicional como coordenadas de detección, configuración del modelo, etc.'
    )
    
    # NUEVO: Campo para detecciones específicas del frontend
    detected_lemons = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Detecciones de Limones',
        help_text='Array JSON con coordenadas y detalles de cada limón detectado'
    )
    
    # NUEVO: Campo para imagen anotada con bounding boxes
    annotated_image = models.TextField(
        blank=True,
        null=True,
        verbose_name='Imagen Anotada Base64',
        help_text='Imagen con bounding boxes en formato base64'
    )
    
    # Timestamps
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Creación'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='Fecha de Actualización'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Registro de Análisis'
        verbose_name_plural = 'Registros de Análisis'
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['media_type', 'source_type']),
            models.Index(fields=['total_lemons_count']),
            models.Index(fields=['created_at']),
            # v2.0: Índices compuestos para queries por sesión
            models.Index(fields=['session_id', 'photo_number']),
            models.Index(fields=['user', 'session_id']),
        ]

    def __str__(self):
        media_info = f"{self.get_media_type_display()} ({self.get_source_type_display()})"
        return f"Análisis {self.id} - {self.user.username} - {media_info} - {self.total_lemons_count} limones"

    def clean(self):
        """Validaciones personalizadas del modelo"""
        from django.core.exceptions import ValidationError
        
        # Validar que se tenga el archivo correcto según el tipo de medio
        # Solo validar archivos si no tenemos total_lemons_count (caso de análisis existente)
        if self.media_type == MediaTypeChoices.IMAGE:
            if not self.original_image and self.total_lemons_count == 0:
                raise ValidationError("Se requiere una imagen para análisis de tipo imagen")
        
        # NOTA: No validamos VIDEO porque el campo original_video fue eliminado
        # La app solo trabaja con imágenes ahora, no con videos

    def save(self, *args, **kwargs):
        """Override del save para ejecutar validaciones y cálculos automáticos"""
        self.clean()
        super().save(*args, **kwargs)

    @property
    def media_file(self):
        """Retorna el archivo de media principal según el tipo"""
        # Solo soportamos imágenes ahora (original_video fue eliminado)
        return self.original_image

    @property
    def processed_media_url(self):
        """Retorna la URL de la imagen procesada"""
        return self.processed_image_url

    @property
    def file_size_mb(self):
        """Retorna el tamaño del archivo en MB"""
        try:
            media_file = self.media_file
            if media_file and media_file.name:
                return round(media_file.size / (1024 * 1024), 2)
        except Exception:
            pass
        return None
    
    @property
    def confidence_score(self):
        """
        Retorna el score de confianza del análisis.
        """
        return self.analysis_data.get('confidence', 0)
    
    @property
    def predicted_class(self):
        """
        Retorna la clase predicha del análisis.
        """
        return self.analysis_data.get('predicted_class', 'unknown')
    
    def get_analysis_summary(self):
        """
        Retorna un resumen del análisis en formato legible.
        """
        confidence = self.confidence_score
        predicted_class = self.predicted_class
        return f"{predicted_class.title()} (Confianza: {confidence:.2%})"


class PasswordResetToken(models.Model):
    """
    Modelo para manejar tokens de restablecimiento de contraseña.
    Los tokens expiran después de 1 hora para mayor seguridad.
    """
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE,
        related_name='password_reset_tokens',
        verbose_name='Usuario'
    )
    token = models.CharField(
        max_length=64,
        unique=True,
        verbose_name='Token de Restablecimiento'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Creación'
    )
    expires_at = models.DateTimeField(
        verbose_name='Fecha de Expiración'
    )
    used = models.BooleanField(
        default=False,
        verbose_name='Token Usado'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Token de Restablecimiento'
        verbose_name_plural = 'Tokens de Restablecimiento'

    def save(self, *args, **kwargs):
        if not self.token:
            self.token = secrets.token_urlsafe(32)
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=1)
        super().save(*args, **kwargs)

    def is_valid(self):
        """Verifica si el token es válido (no usado y no expirado)"""
        return not self.used and timezone.now() < self.expires_at

    def mark_as_used(self):
        """Marca el token como usado"""
        self.used = True
        self.save()

    def __str__(self):
        status = "Válido" if self.is_valid() else "Inválido"
        return f"Token {self.token[:8]}... para {self.user.username} - {status}"


class WorkerAPIKey(models.Model):
    """
    Modelo para manejar API keys de workers offline.
    Formato: AGR-WORKER-XXXX-XXXX-XXXX
    Las keys se almacenan hasheadas para seguridad.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='api_keys',
        verbose_name='Usuario'
    )
    name = models.CharField(
        max_length=100,
        verbose_name='Nombre/Descripción',
        help_text='Nombre identificador del worker (ej: "Worker-001", "Tablet-Campo-A")'
    )
    key_prefix = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
        verbose_name='Prefijo de Key',
        help_text='Primeros caracteres de la key para identificación'
    )
    key_hash = models.CharField(
        max_length=128,
        unique=True,
        editable=False,
        verbose_name='Hash de Key',
        help_text='Hash SHA-256 de la API key completa'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Creación'
    )
    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Último Uso'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Si está desactivado, la key no funcionará aunque sea válida'
    )

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'API Key de Worker'
        verbose_name_plural = 'API Keys de Workers'
        indexes = [
            models.Index(fields=['key_hash']),
            models.Index(fields=['key_prefix']),
            models.Index(fields=['is_active', 'last_used_at']),
        ]

    @staticmethod
    def generate_key():
        """
        Genera una API key en formato: AGR-WORKER-XXXX-XXXX-XXXX
        Retorna la key en texto plano (debe mostrarse solo UNA VEZ al usuario)
        """
        import random
        import string

        def generate_segment():
            """Genera un segmento aleatorio de 4 caracteres alfanuméricos"""
            chars = string.ascii_uppercase + string.digits
            return ''.join(random.choices(chars, k=4))

        return f"AGR-WORKER-{generate_segment()}-{generate_segment()}-{generate_segment()}"

    @staticmethod
    def hash_key(key):
        """Hash de la API key usando SHA-256"""
        import hashlib
        return hashlib.sha256(key.encode()).hexdigest()

    def save(self, *args, **kwargs):
        """
        Si es una nueva instancia, se debe proporcionar la key en texto plano
        mediante un atributo temporal '_plain_key'
        """
        if not self.pk and hasattr(self, '_plain_key'):
            # Es una nueva API key
            plain_key = self._plain_key
            self.key_hash = self.hash_key(plain_key)
            # Guardar prefijo para identificación (primeros 15 caracteres)
            # Ejemplo: "AGR-WORKER-ABC1"
            self.key_prefix = plain_key[:15]

        super().save(*args, **kwargs)

    @classmethod
    def create_key(cls, user, name):
        """
        Crea una nueva API key para un usuario.
        Retorna una tupla: (WorkerAPIKey instance, plain_key_string)
        """
        plain_key = cls.generate_key()

        api_key = cls(user=user, name=name)
        api_key._plain_key = plain_key  # Atributo temporal
        api_key.save()

        # Retornar la instancia y la key en texto plano
        # La key solo se muestra aquí, nunca se guarda en texto plano
        return api_key, plain_key

    @classmethod
    def validate_key(cls, plain_key):
        """
        Valida una API key y retorna el objeto WorkerAPIKey si es válida.
        Actualiza last_used_at si la key es válida.
        Retorna None si la key es inválida.
        """
        try:
            key_hash = cls.hash_key(plain_key)
            api_key = cls.objects.get(key_hash=key_hash, is_active=True)

            # Actualizar timestamp de último uso
            api_key.last_used_at = timezone.now()
            api_key.save(update_fields=['last_used_at'])

            return api_key
        except cls.DoesNotExist:
            return None

    def mark_inactive(self):
        """Desactiva esta API key"""
        self.is_active = False
        self.save(update_fields=['is_active'])

    def __str__(self):
        status = "Activa" if self.is_active else "Inactiva"
        last_used = f"Usado: {self.last_used_at.strftime('%Y-%m-%d')}" if self.last_used_at else "Nunca usado"
        return f"{self.key_prefix}... - {self.name} ({self.user.username}) - {status} - {last_used}"


# ========== ACTIVATED DEVICE MODEL (FASE 3) ==========

class ActivatedDevice(models.Model):
    """
    Dispositivo activado para un trabajador.
    Permite rastrear qué dispositivos tienen acceso offline con PIN.

    Cada dispositivo tiene un token único que se usa para autenticación
    después de la activación inicial con PIN.
    """

    # ID único del dispositivo activado
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name='ID'
    )

    # Worker dueño del dispositivo
    worker = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='activated_devices',
        verbose_name='Trabajador',
        help_text='Trabajador propietario de este dispositivo'
    )

    # Identificador único del dispositivo (generado por el móvil)
    device_id = models.CharField(
        max_length=255,
        unique=True,
        verbose_name='ID del Dispositivo',
        help_text='ID único del dispositivo (ej: Android_Pixel6_1699...)'
    )

    # Nombre legible del dispositivo
    device_name = models.CharField(
        max_length=255,
        verbose_name='Nombre del Dispositivo',
        help_text='Nombre del dispositivo (ej: "Pixel 6 - Android")'
    )

    # Token único para este dispositivo
    device_token = models.CharField(
        max_length=128,
        unique=True,
        verbose_name='Token del Dispositivo',
        help_text='Token único generado para este dispositivo'
    )

    # Estado del dispositivo
    is_active = models.BooleanField(
        default=True,
        verbose_name='Activo',
        help_text='Si está activo, el dispositivo puede hacer login offline'
    )

    # Timestamps
    activated_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de Activación',
        help_text='Fecha y hora de activación'
    )

    last_used = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Último Uso',
        help_text='Última vez que se usó este dispositivo'
    )

    deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha de Desactivación',
        help_text='Fecha y hora de desactivación (si aplica)'
    )

    # Metadatos adicionales
    platform = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name='Plataforma',
        help_text='Plataforma del dispositivo (Android/iOS)'
    )

    app_version = models.CharField(
        max_length=20,
        null=True,
        blank=True,
        verbose_name='Versión de la App',
        help_text='Versión de la app al momento de activación'
    )

    class Meta:
        verbose_name = 'Dispositivo Activado'
        verbose_name_plural = 'Dispositivos Activados'
        ordering = ['-activated_at']
        indexes = [
            models.Index(fields=['worker', 'is_active']),
            models.Index(fields=['device_id']),
            models.Index(fields=['device_token']),
        ]

    def __str__(self):
        status = "✓ Activo" if self.is_active else "✗ Inactivo"
        return f"{self.worker.username} - {self.device_name} - {status}"

    def deactivate(self):
        """Desactiva este dispositivo"""
        self.is_active = False
        self.deactivated_at = timezone.now()
        self.save(update_fields=['is_active', 'deactivated_at'])

    def update_last_used(self):
        """Actualiza el timestamp de último uso"""
        self.last_used = timezone.now()
        self.save(update_fields=['last_used'])

    def regenerate_token(self):
        """
        Regenera el device token para este dispositivo.
        Útil cuando el worker pierde acceso o necesita renovar su autenticación.
        """
        self.device_token = self.generate_device_token()
        self.activated_at = timezone.now()  # Actualizar fecha de activación
        self.is_active = True  # Asegurar que esté activo
        self.save(update_fields=['device_token', 'activated_at', 'is_active'])

    @staticmethod
    def generate_device_token():
        """Genera un token único para el dispositivo"""
        return secrets.token_urlsafe(32)


# ========== USER PROFILE MODEL (FASE 2) ==========

class UserProfile(models.Model):
    """
    Perfil extendido de usuario para almacenar información adicional.
    Se relaciona con User mediante OneToOneField.

    FASE 2: Campo 'role' agregado para controlar roles desde el backend.
    FASE 3: Campos de autenticación offline con PIN agregados.
    FASE 4: Multi-tenancy con Organization y jerarquía de usuarios.
    """

    ROLE_CHOICES = [
        ('admin', 'Administrador'),
        ('worker', 'Trabajador'),
        ('superadmin', 'Super Administrador'),
    ]

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Usuario'
    )

    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='worker',
        verbose_name='Rol del Usuario',
        help_text='Rol del usuario en el sistema'
    )
    
    # ========== MULTI-TENANCY ==========

    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name='profiles',
        null=True,
        blank=True,
        verbose_name='Organización',
        help_text='Organización a la que pertenece el usuario'
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_profiles',
        verbose_name='Creado por',
        help_text='Admin que creó este usuario (solo para workers)'
    )

    # ========== CAMPOS PARA AUTENTICACIÓN OFFLINE ==========

    # PIN para autenticación offline (4-6 dígitos, hasheado)
    pin_hash = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        verbose_name='Hash de PIN',
        help_text='Hash SHA-256 del PIN del trabajador (4-6 dígitos)'
    )

    # Indica si el PIN ha sido configurado
    pin_configured = models.BooleanField(
        default=False,
        verbose_name='PIN Configurado',
        help_text='True si el trabajador tiene un PIN configurado'
    )

    # Fecha de última activación de dispositivo
    last_device_activation = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Última Activación de Dispositivo',
        help_text='Última vez que se activó un dispositivo para este worker'
    )
    
    # Flag para forzar cambio de contraseña (admins recién aprobados)
    password_change_required = models.BooleanField(
        default=False,
        verbose_name='Cambio de Contraseña Requerido',
        help_text='True si el usuario debe cambiar su contraseña en el próximo login'
    )

    # ========== SISTEMA DE AUTENTICACIÓN SIMPLE ==========

    # API Key corta para sistema simplificado (formato: AGR-WK-XXXXXX)
    api_key_short = models.CharField(
        max_length=13,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        verbose_name='API Key Simple',
        help_text='API Key corta para autenticación offline (formato: AGR-WK-XXXXXX)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuarios'
        db_table = 'users_userprofile'

    def __str__(self):
        return f"{self.user.username} - {self.get_role_display()}"

    def set_pin(self, pin: str):
        """
        Hashea y guarda el PIN del trabajador

        Args:
            pin: PIN en texto plano (4-6 dígitos numéricos)

        Raises:
            ValueError: Si el PIN no cumple con los requisitos
        """
        if not pin.isdigit():
            raise ValueError("El PIN debe contener solo dígitos numéricos")

        if len(pin) < 4 or len(pin) > 6:
            raise ValueError("El PIN debe contener entre 4 y 6 dígitos")

        # Hashear con SHA-256
        self.pin_hash = hashlib.sha256(pin.encode()).hexdigest()
        self.pin_configured = True
        self.save(update_fields=['pin_hash', 'pin_configured'])

    def verify_pin(self, pin: str) -> bool:
        """
        Verifica si el PIN proporcionado es correcto

        Args:
            pin: PIN en texto plano a verificar

        Returns:
            True si el PIN es correcto, False si no
        """
        if not self.pin_hash:
            return False

        pin_hash = hashlib.sha256(pin.encode()).hexdigest()
        return pin_hash == self.pin_hash


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """
    Signal para crear automáticamente un UserProfile cuando se crea un User.
    Asigna el rol basándose en is_staff y is_superuser.
    """
    if created:
        # Determinar rol inicial
        if instance.is_superuser:
            role = 'superadmin'
        elif instance.is_staff:
            role = 'admin'
        else:
            role = 'worker'

        UserProfile.objects.create(user=instance, role=role)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """
    Signal para guardar el profile cuando se guarda el User.
    """
    # Solo guardar si el profile ya existe
    if hasattr(instance, 'profile'):
        instance.profile.save()