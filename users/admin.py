from django.contrib import admin
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from .models import AnalysisRecord, PasswordResetToken, WorkerAPIKey, UserProfile, ActivatedDevice, Organization, AdminRequest
import json

@admin.register(AnalysisRecord)
class AnalysisRecordAdmin(admin.ModelAdmin):
    """
    Admin limpio para análisis de detección de limones.
    Diseñado para usuarios no técnicos.
    """
    
    # Vista de lista - Columnas principales
    list_display = (
        'thumbnail_preview',
        'analysis_info',
        'user',
        'total_lemons_count',
        'processing_time_display',
        'date_display',
    )
    
    list_display_links = ('thumbnail_preview', 'analysis_info')
    
    list_filter = (
        'user',
        'model_type',
        'created_at',
    )
    
    search_fields = (
        'user__username',
        'local_id',
        'id',
    )
    
    readonly_fields = (
        'image_display',
        'session_info',
        'created_at',
        'updated_at',
    )
    
    ordering = ('-created_at',)
    
    # Organizar campos en secciones
    fieldsets = (
        ('Resultado del Análisis', {
            'fields': (
                'image_display',
                'session_info',
            ),
        }),
        ('Fechas', {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    # ========== MÉTODOS PARA VISTA DE LISTA ==========
    
    def thumbnail_preview(self, obj):
        """Miniatura de la imagen en la lista - CLICKEABLE"""
        if obj.original_image:
            return format_html(
                '<img src="{}" style="width: 60px; height: 60px; object-fit: cover; border-radius: 4px; border: 2px solid #ddd; cursor: pointer;"/>',
                obj.original_image.url
            )
        return format_html('<div style="width: 60px; height: 60px; background: #f0f0f0; border-radius: 4px; display: flex; align-items: center; justify-content: center; font-size: 11px; color: #999;">Sin imagen</div>')
    thumbnail_preview.short_description = "Imagen"
    
    def analysis_info(self, obj):
        """Información del análisis - CLICKEABLE"""
        return format_html(
            '<div style="line-height: 1.5;">'
            '<strong style="font-size: 13px; color: #333;">Análisis #{}</strong><br>'
            '<span style="font-size: 12px; color: #666;">{}</span>'
            '</div>',
            obj.id,
            obj.model_type.replace('_', ' ').title()
        )
    analysis_info.short_description = "Análisis"
    
    def processing_time_display(self, obj):
        """Tiempo de procesamiento en formato legible"""
        time = obj.processing_time or 0.0
        if time < 1:
            return f"{int(time * 1000)}ms"
        return f"{time:.1f}s"
    processing_time_display.short_description = "Tiempo"
    
    def date_display(self, obj):
        """Fecha en formato amigable"""
        from django.utils import timezone
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff.days == 0:
            if diff.seconds < 3600:
                minutes = diff.seconds // 60
                return f"Hace {minutes} min"
            else:
                hours = diff.seconds // 3600
                return f"Hace {hours} hrs"
        elif diff.days == 1:
            return "Ayer"
        elif diff.days < 7:
            return f"Hace {diff.days} días"
        else:
            return obj.created_at.strftime('%d/%m/%Y')
    date_display.short_description = "Fecha"
    
    # ========== MÉTODOS PARA VISTA DETALLADA ==========
    
    def image_display(self, obj):
        """Muestra la imagen del análisis (con bounding boxes si el frontend los dibujó)"""
        if not obj.original_image:
            return mark_safe('<p style="color: #999;">No hay imagen disponible</p>')
        
        # Si hay imagen con anotaciones en base64 (dibujada por el frontend)
        if obj.annotated_image:
            return mark_safe(f'''
                <div style="background: #f5f5f5; padding: 15px; border-radius: 4px;">
                    <h4 style="margin: 0 0 10px 0; color: #333;">{obj.total_lemons_count} Limones Detectados</h4>
                    <img src="data:image/jpeg;base64,{obj.annotated_image}" 
                         style="max-width: 800px; width: 100%; height: auto; border: 1px solid #ddd;"/>
                    <p style="margin: 10px 0 0 0; color: #666; font-size: 12px;">
                        Imagen con detecciones visuales (bounding boxes) •
                        <a href="{obj.original_image.url}" target="_blank" style="color: #007bff; text-decoration: none;">
                            Ver imagen original
                        </a>
                    </p>
                </div>
            ''')
        
        # Si NO hay anotaciones, mostrar imagen original
        return mark_safe(f'''
            <div style="background: #f5f5f5; padding: 15px; border-radius: 4px;">
                <h4 style="margin: 0 0 10px 0; color: #333;">{obj.total_lemons_count} Limones Detectados</h4>
                <img src="{obj.original_image.url}" 
                     style="max-width: 800px; width: 100%; height: auto; border: 1px solid #ddd;"/>
                <p style="margin: 10px 0 0 0; color: #999; font-size: 12px;">
                    Imagen sin bounding boxes visuales
                </p>
            </div>
        ''')
    image_display.short_description = "Imagen del Análisis"
    
    def session_info(self, obj):
        """Información de la sesión de análisis"""
        html = f'''
        <div style="background: #f8f9fa; padding: 12px; border: 1px solid #e0e0e0;">
            <table style="width: 100%; font-size: 13px;">
                <tr>
                    <td style="padding: 6px; font-weight: bold; width: 180px;">Usuario:</td>
                    <td style="padding: 6px;">{obj.user.username}</td>
                </tr>
        '''
        
        # ID Local
        if obj.local_id:
            html += f'''
                <tr>
                    <td style="padding: 6px; font-weight: bold;">ID de Análisis:</td>
                    <td style="padding: 6px; font-family: monospace; font-size: 11px;">{obj.local_id}</td>
                </tr>
            '''
        
        # Modelo usado
        html += f'''
                <tr>
                    <td style="padding: 6px; font-weight: bold;">Modelo:</td>
                    <td style="padding: 6px;">{obj.model_type}</td>
                </tr>
        '''
        
        # Tiempo de procesamiento
        html += f'''
                <tr>
                    <td style="padding: 6px; font-weight: bold;">Tiempo de Proceso:</td>
                    <td style="padding: 6px;">{self.processing_time_display(obj)}</td>
                </tr>
            </table>
        </div>
        '''
        
        return mark_safe(html)
    session_info.short_description = "Información de la Sesión"
    
    # Deshabilitar edición de campos sensibles
    def has_add_permission(self, request):
        """Los análisis solo se crean desde la app, no desde admin"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Solo superusers pueden eliminar análisis"""
        return request.user.is_superuser

@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    """
    Admin para tokens de recuperación de contraseña.
    Monitoreo de solicitudes de reseteo.
    """
    list_display = (
        'user_info',
        'token_preview',
        'status_badge',
        'expiration_display',
        'created_date',
    )
    
    list_display_links = ('user_info', 'token_preview')
    
    list_filter = ('used', 'created_at', 'expires_at')
    search_fields = ('user__username', 'user__email', 'token')
    readonly_fields = ('token', 'created_at', 'expires_at', 'token_info')
    ordering = ('-created_at',)
    
    fieldsets = (
        ('Información del Token', {
            'fields': ('token_info',)
        }),
        ('Usuario', {
            'fields': ('user',)
        }),
        ('Estado', {
            'fields': ('used', 'created_at', 'expires_at')
        }),
    )
    
    # ========== MÉTODOS PARA VISTA DE LISTA ==========
    
    def user_info(self, obj):
        """Información del usuario - CLICKEABLE"""
        return format_html(
            '<div style="line-height: 1.5;">'
            '<strong style="font-size: 13px;">{}</strong><br>'
            '<span style="font-size: 11px; color: #666;">{}</span>'
            '</div>',
            obj.user.username,
            obj.user.email or 'Sin email'
        )
    user_info.short_description = "Usuario"
    
    def token_preview(self, obj):
        """Preview del token"""
        if obj.token:
            preview = obj.token[:8] + '...' + obj.token[-4:]
            return format_html(
                '<code style="font-size: 11px; background: #f4f4f4; padding: 4px 8px; border-radius: 3px; color: #666;">{}</code>',
                preview
            )
        return format_html('<span style="color: #999;">N/A</span>')
    token_preview.short_description = "Token"
    
    def status_badge(self, obj):
        """Estado del token con badge - Paleta limones"""
        if obj.used:
            return format_html(
                '<span style="display: inline-block; padding: 4px 10px; background: #636e72; color: white; '
                'border-radius: 4px; font-size: 11px; font-weight: 500;">USADO</span>'
            )
        elif obj.is_valid():
            return format_html(
                '<span style="display: inline-block; padding: 4px 10px; background: #6ab04c; color: white; '
                'border-radius: 4px; font-size: 11px; font-weight: 500;">VÁLIDO</span>'
            )
        else:
            return format_html(
                '<span style="display: inline-block; padding: 4px 10px; background: #eb4d4b; color: white; '
                'border-radius: 4px; font-size: 11px; font-weight: 500;">EXPIRADO</span>'
            )
    status_badge.short_description = "Estado"
    
    def expiration_display(self, obj):
        """Información de expiración - Paleta limones"""
        from django.utils import timezone
        now = timezone.now()
        
        if obj.used:
            return format_html('<span style="color: #636e72;">Usado</span>')
        
        if obj.expires_at > now:
            diff = obj.expires_at - now
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            
            if diff.days > 0:
                return f"Expira en {diff.days} día(s)"
            elif hours > 0:
                return f"Expira en {hours}h"
            else:
                return f"Expira en {minutes}min"
        else:
            return format_html('<span style="color: #eb4d4b;">Expirado</span>')
    expiration_display.short_description = "Expiración"
    
    def created_date(self, obj):
        """Fecha de creación"""
        return obj.created_at.strftime('%d/%m/%Y %H:%M')
    created_date.short_description = "Creado"
    
    # ========== MÉTODOS PARA VISTA DETALLADA ==========
    
    def token_info(self, obj):
        """Información detallada del token"""
        from django.utils import timezone
        
        # Estado - Paleta limones
        if obj.used:
            status_color = '#636e72'
            status_text = 'USADO'
        elif obj.is_valid():
            status_color = '#6ab04c'
            status_text = 'VÁLIDO'
        else:
            status_color = '#eb4d4b'
            status_text = 'EXPIRADO'
        
        # Tiempo restante
        if not obj.used and obj.expires_at > timezone.now():
            diff = obj.expires_at - timezone.now()
            hours = diff.seconds // 3600
            minutes = (diff.seconds % 3600) // 60
            
            if diff.days > 0:
                time_left = f"{diff.days} día(s)"
            elif hours > 0:
                time_left = f"{hours} hora(s) {minutes} minuto(s)"
            else:
                time_left = f"{minutes} minuto(s)"
        else:
            time_left = "Expirado" if not obj.used else "No aplica"
        
        return mark_safe(f'''
            <div style="background: #f8f9fa; padding: 15px; border-radius: 4px;">
                <table style="width: 100%; font-size: 13px;">
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500; width: 140px;">Estado:</td>
                        <td style="padding: 8px 0;">
                            <span style="display: inline-block; padding: 3px 10px; background: {status_color}; color: white; 
                            border-radius: 3px; font-size: 11px; font-weight: 500;">{status_text}</span>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Token:</td>
                        <td style="padding: 8px 0;">
                            <code style="font-size: 11px; background: #e9ecef; padding: 4px 8px; border-radius: 3px; word-break: break-all;">{obj.token}</code>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Creado:</td>
                        <td style="padding: 8px 0;">{obj.created_at.strftime('%d/%m/%Y %H:%M:%S')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Expira:</td>
                        <td style="padding: 8px 0;">{obj.expires_at.strftime('%d/%m/%Y %H:%M:%S')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Tiempo restante:</td>
                        <td style="padding: 8px 0;">{time_left}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Usado:</td>
                        <td style="padding: 8px 0;">{'Sí' if obj.used else 'No'}</td>
                    </tr>
                </table>
            </div>
        ''')
    token_info.short_description = "Información del Token"
    
    def has_add_permission(self, request):
        """No se pueden crear tokens desde el admin"""
        return False


@admin.register(WorkerAPIKey)
class WorkerAPIKeyAdmin(admin.ModelAdmin):
    """
    Admin para API Keys (Sistema Legacy).
    Gestión de claves de autenticación para workers.
    """
    list_display = (
        'key_info',
        'user_info',
        'status_badge',
        'last_used_display',
        'created_date',
    )
    
    list_display_links = ('key_info',)
    
    list_filter = ('is_active', 'created_at', 'last_used_at')
    search_fields = ('user__username', 'user__email', 'name', 'key_prefix')
    readonly_fields = ('key_prefix', 'key_hash', 'created_at', 'last_used_at', 'usage_info')
    ordering = ('-created_at',)

    fieldsets = (
        ('Información de la API Key', {
            'fields': ('user', 'name', 'usage_info')
        }),
        ('Seguridad', {
            'fields': ('key_prefix', 'key_hash', 'is_active'),
            'description': 'La API key completa solo se muestra una vez al crearla. El hash es irreversible.'
        }),
        ('Registro de Actividad', {
            'fields': ('created_at', 'last_used_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['revoke_keys', 'activate_keys']
    
    # ========== MÉTODOS PARA VISTA DE LISTA ==========
    
    def key_info(self, obj):
        """Información de la API Key - CLICKEABLE"""
        return format_html(
            '<div style="line-height: 1.6;">'
            '<strong style="font-size: 13px; color: #333;">{}</strong><br>'
            '<code style="font-size: 11px; color: #666; background: #f4f4f4; padding: 2px 6px; border-radius: 3px;">{}</code>'
            '</div>',
            obj.name,
            obj.key_prefix + '...'
        )
    key_info.short_description = "API Key"
    
    def user_info(self, obj):
        """Información del usuario"""
        full_name = obj.user.get_full_name() or obj.user.username
        return format_html(
            '<div style="line-height: 1.5;">'
            '<strong style="font-size: 13px;">{}</strong><br>'
            '<span style="font-size: 11px; color: #666;">@{}</span>'
            '</div>',
            full_name,
            obj.user.username
        )
    user_info.short_description = "Usuario"
    
    def status_badge(self, obj):
        """Estado con badge de color - Paleta limones"""
        if obj.is_active:
            if obj.last_used_at:
                from django.utils import timezone
                days_since_use = (timezone.now() - obj.last_used_at).days
                if days_since_use == 0:
                    return format_html(
                        '<span style="display: inline-block; padding: 4px 10px; background: #6ab04c; color: white; '
                        'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVA • Hoy</span>'
                    )
                elif days_since_use <= 30:
                    return format_html(
                        '<span style="display: inline-block; padding: 4px 10px; background: #6ab04c; color: white; '
                        'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVA • Hace {} días</span>',
                        days_since_use
                    )
                else:
                    return format_html(
                        '<span style="display: inline-block; padding: 4px 10px; background: #f9ca24; color: #2d3436; '
                        'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVA • Hace {} días</span>',
                        days_since_use
                    )
            else:
                return format_html(
                    '<span style="display: inline-block; padding: 4px 10px; background: #dfe6e9; color: #2d3436; '
                    'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVA • Sin uso</span>'
                )
        else:
            return format_html(
                '<span style="display: inline-block; padding: 4px 10px; background: #636e72; color: white; '
                'border-radius: 4px; font-size: 11px; font-weight: 500;">REVOCADA</span>'
            )
    status_badge.short_description = "Estado"
    
    def last_used_display(self, obj):
        """Última vez usada"""
        if obj.last_used_at:
            from django.utils import timezone
            diff = timezone.now() - obj.last_used_at
            days_ago = diff.days
            
            if days_ago == 0:
                hours = diff.seconds // 3600
                if hours == 0:
                    minutes = diff.seconds // 60
                    return f"Hace {minutes} min"
                return f"Hace {hours}h"
            elif days_ago == 1:
                return "Ayer"
            elif days_ago < 30:
                return f"Hace {days_ago} días"
            else:
                return obj.last_used_at.strftime('%d/%m/%Y')
        return format_html('<span style="color: #999;">Nunca</span>')
    last_used_display.short_description = "Último Uso"
    
    def created_date(self, obj):
        """Fecha de creación"""
        return obj.created_at.strftime('%d/%m/%Y')
    created_date.short_description = "Creada"
    
    # ========== MÉTODOS PARA VISTA DETALLADA ==========
    
    def usage_info(self, obj):
        """Información de uso de la API Key - Paleta limones"""
        from django.utils import timezone
        
        status_color = '#6ab04c' if obj.is_active else '#636e72'
        status_text = 'ACTIVA' if obj.is_active else 'REVOCADA'
        
        last_used_text = "Nunca usada"
        if obj.last_used_at:
            days_ago = (timezone.now() - obj.last_used_at).days
            if days_ago == 0:
                last_used_text = "Usada hoy"
            elif days_ago == 1:
                last_used_text = "Usada ayer"
            else:
                last_used_text = f"Usada hace {days_ago} días"
        
        return mark_safe(f'''
            <div style="background: #f8f9fa; padding: 15px; border-radius: 4px;">
                <table style="width: 100%; font-size: 13px;">
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500; width: 140px;">Estado:</td>
                        <td style="padding: 6px 0;">
                            <span style="display: inline-block; padding: 3px 10px; background: {status_color}; color: white; 
                            border-radius: 3px; font-size: 11px; font-weight: 500;">{status_text}</span>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Creada:</td>
                        <td style="padding: 6px 0;">{obj.created_at.strftime('%d/%m/%Y %H:%M')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Último Uso:</td>
                        <td style="padding: 6px 0;">{last_used_text}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Prefijo:</td>
                        <td style="padding: 6px 0;"><code style="background: #e9ecef; padding: 2px 6px; border-radius: 3px;">{obj.key_prefix}</code></td>
                    </tr>
                </table>
            </div>
        ''')
    usage_info.short_description = "Información de Uso"

    # ========== SAVE MODEL ==========

    def save_model(self, request, obj, form, change):
        """
        Genera la API key al crear y muestra mensaje amigable.
        """
        if not change:
            # Generar key y guardar
            api_key_obj, plain_key = WorkerAPIKey.create_key(
                user=obj.user,
                name=obj.name
            )

            # Mensaje amigable y claro
            from django.contrib import messages
            messages.success(
                request,
                format_html(
                    '<div style="background: #ffeaa7; padding: 15px; border-radius: 4px; border-left: 4px solid #fdcb6e;">'
                    '<strong style="font-size: 14px; color: #2d3436;">API Key Creada Exitosamente</strong><br><br>'
                    '<strong>Usuario:</strong> {}<br>'
                    '<strong>Dispositivo:</strong> {}<br><br>'
                    '<div style="background: white; padding: 10px; border-radius: 3px; margin: 10px 0;">'
                    '<code style="font-size: 13px; color: #6ab04c; font-weight: bold;">{}</code>'
                    '</div>'
                    '<p style="margin: 10px 0 0 0; color: #2d3436;"><strong>IMPORTANTE:</strong> '
                    'Esta es la única vez que verás la clave completa. Cópiala ahora.</p>'
                    '</div>',
                    obj.user.username,
                    obj.name,
                    plain_key
                )
            )
        else:
            super().save_model(request, obj, form, change)

    # ========== ACCIONES ==========

    def revoke_keys(self, request, queryset):
        """Acción masiva para revocar API keys"""
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} API key(s) revocadas exitosamente.")
    revoke_keys.short_description = "Revocar API keys seleccionadas"

    def activate_keys(self, request, queryset):
        """Acción masiva para activar API keys"""
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} API key(s) activadas exitosamente.")
    activate_keys.short_description = "Activar API keys seleccionadas"


@admin.register(ActivatedDevice)
class ActivatedDeviceAdmin(admin.ModelAdmin):
    """
    Admin para gestión de dispositivos activados.
    Diseñado para facilitar el control de dispositivos de workers.
    """
    list_display = (
        'device_info',
        'worker_info',
        'platform_display',
        'status_badge',
        'last_used_display',
        'activated_date',
    )
    
    list_display_links = ('device_info',)

    list_filter = (
        'is_active',
        'platform',
        'activated_at',
        'last_used'
    )

    search_fields = (
        'worker__username',
        'worker__first_name',
        'worker__last_name',
        'device_id',
        'device_name'
    )

    readonly_fields = (
        'device_token_display',
        'activated_at',
        'last_used',
        'deactivated_at',
        'usage_summary',
        'device_info_detail',
    )

    ordering = ('-activated_at',)

    fieldsets = (
        ('Información del Dispositivo', {
            'fields': ('device_info_detail', 'usage_summary')
        }),
        ('Worker Asignado', {
            'fields': ('worker',)
        }),
        ('Detalles Técnicos', {
            'fields': ('device_id', 'device_name', 'platform', 'app_version'),
            'classes': ('collapse',)
        }),
        ('Seguridad y Estado', {
            'fields': ('device_token_display', 'is_active'),
        }),
        ('Registro de Actividad', {
            'fields': ('activated_at', 'last_used', 'deactivated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['deactivate_devices', 'activate_devices']
    
    # ========== MÉTODOS PARA VISTA DE LISTA ==========
    
    def device_info(self, obj):
        """Información del dispositivo - CLICKEABLE"""
        # Paleta limones: amarillo-verde
        return format_html(
            '<div style="line-height: 1.6;">'
            '<strong style="font-size: 13px; color: #2d3436;">{}</strong><br>'
            '<span style="font-size: 11px; color: #636e72; font-family: monospace;">{}</span>'
            '</div>',
            obj.device_name or 'Dispositivo sin nombre',
            obj.device_id[:16] + '...' if obj.device_id and len(obj.device_id) > 16 else (obj.device_id or 'N/A')
        )
    device_info.short_description = "Dispositivo"
    
    def worker_info(self, obj):
        """Información del worker"""
        full_name = obj.worker.get_full_name() or obj.worker.username
        return format_html(
            '<div style="line-height: 1.5;">'
            '<strong style="font-size: 13px;">{}</strong><br>'
            '<span style="font-size: 11px; color: #666;">@{}</span>'
            '</div>',
            full_name,
            obj.worker.username
        )
    worker_info.short_description = "Worker"
    
    def platform_display(self, obj):
        """Plataforma con badge visual - Paleta limones"""
        if not obj.platform:
            return format_html(
                '<span style="display: inline-block; padding: 4px 12px; background: #b2bec3; color: white; '
                'border-radius: 12px; font-size: 11px; font-weight: 500;">N/A</span>'
            )
        
        # Colores inspirados en limones y naturaleza
        colors = {
            'android': '#6ab04c',  # Verde limón
            'ios': '#f9ca24',      # Amarillo limón
            'web': '#eb4d4b',      # Naranja-rojo
        }
        color = colors.get(obj.platform.lower(), '#95afc0')
        
        return format_html(
            '<span style="display: inline-block; padding: 4px 12px; background: {}; color: white; '
            'border-radius: 12px; font-size: 11px; font-weight: 500;">{}</span>',
            color,
            obj.platform.upper()
        )
    platform_display.short_description = "Plataforma"
    
    def status_badge(self, obj):
        """Estado con badge de color - Paleta limones"""
        if obj.is_active:
            if obj.last_used:
                from django.utils import timezone
                days_since_use = (timezone.now() - obj.last_used).days
                if days_since_use == 0:
                    return format_html(
                        '<span style="display: inline-block; padding: 4px 10px; background: #6ab04c; color: white; '
                        'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVO • Hoy</span>'
                    )
                elif days_since_use <= 7:
                    return format_html(
                        '<span style="display: inline-block; padding: 4px 10px; background: #6ab04c; color: white; '
                        'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVO • Hace {} días</span>',
                        days_since_use
                    )
                else:
                    return format_html(
                        '<span style="display: inline-block; padding: 4px 10px; background: #f9ca24; color: #2d3436; '
                        'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVO • Hace {} días</span>',
                        days_since_use
                    )
            else:
                return format_html(
                    '<span style="display: inline-block; padding: 4px 10px; background: #dfe6e9; color: #2d3436; '
                    'border-radius: 4px; font-size: 11px; font-weight: 500;">ACTIVO • Sin uso</span>'
                )
        else:
            return format_html(
                '<span style="display: inline-block; padding: 4px 10px; background: #636e72; color: white; '
                'border-radius: 4px; font-size: 11px; font-weight: 500;">DESACTIVADO</span>'
            )
    status_badge.short_description = "Estado"

    def last_used_display(self, obj):
        """Última conexión en formato legible"""
        if obj.last_used:
            from django.utils import timezone
            diff = timezone.now() - obj.last_used
            days_ago = diff.days
            
            if days_ago == 0:
                hours = diff.seconds // 3600
                if hours == 0:
                    minutes = diff.seconds // 60
                    return f"Hace {minutes} min"
                return f"Hace {hours}h"
            elif days_ago == 1:
                return "Ayer"
            elif days_ago < 7:
                return f"Hace {days_ago} días"
            else:
                return obj.last_used.strftime('%d/%m/%Y')
        return format_html('<span style="color: #999;">Nunca</span>')
    last_used_display.short_description = "Última Conexión"
    
    def activated_date(self, obj):
        """Fecha de activación"""
        return obj.activated_at.strftime('%d/%m/%Y')
    activated_date.short_description = "Activado"
    
    # ========== MÉTODOS PARA VISTA DETALLADA ==========
    
    def device_info_detail(self, obj):
        """Resumen visual del dispositivo - Paleta limones"""
        platform_display = obj.platform.upper() if obj.platform else 'No especificada'
        return mark_safe(f'''
            <div style="background: #f8f9fa; padding: 15px; border-radius: 4px; border-left: 4px solid #f9ca24;">
                <h3 style="margin: 0 0 12px 0; color: #2d3436; font-size: 16px;">{obj.device_name or 'Dispositivo sin nombre'}</h3>
                <table style="width: 100%; font-size: 13px;">
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500; width: 140px;">ID del Dispositivo:</td>
                        <td style="padding: 6px 0; font-family: monospace; font-size: 11px; color: #636e72;">{obj.device_id or 'N/A'}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Plataforma:</td>
                        <td style="padding: 6px 0;">{platform_display}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Versión de App:</td>
                        <td style="padding: 6px 0;">{obj.app_version or 'No especificada'}</td>
                    </tr>
                </table>
            </div>
        ''')
    device_info_detail.short_description = "Información del Dispositivo"
    
    def usage_summary(self, obj):
        """Resumen de uso del dispositivo - Paleta limones"""
        from django.utils import timezone
        
        status_color = '#6ab04c' if obj.is_active else '#636e72'
        status_text = 'ACTIVO' if obj.is_active else 'DESACTIVADO'
        
        last_used_text = "Nunca usado"
        if obj.last_used:
            days_ago = (timezone.now() - obj.last_used).days
            if days_ago == 0:
                last_used_text = "Usado hoy"
            elif days_ago == 1:
                last_used_text = "Usado ayer"
            else:
                last_used_text = f"Usado hace {days_ago} días"
        
        deactivated_info = ""
        if obj.deactivated_at:
            deactivated_info = f'''
                <tr>
                    <td style="padding: 6px 0; font-weight: 500;">Desactivado:</td>
                    <td style="padding: 6px 0; color: #636e72;">{obj.deactivated_at.strftime('%d/%m/%Y %H:%M')}</td>
                </tr>
            '''
        
        return mark_safe(f'''
            <div style="background: #f8f9fa; padding: 15px; border-radius: 4px;">
                <table style="width: 100%; font-size: 13px;">
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500; width: 140px;">Estado:</td>
                        <td style="padding: 6px 0;">
                            <span style="display: inline-block; padding: 3px 10px; background: {status_color}; color: white; 
                            border-radius: 3px; font-size: 11px; font-weight: 500;">{status_text}</span>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Activado:</td>
                        <td style="padding: 6px 0;">{obj.activated_at.strftime('%d/%m/%Y %H:%M')}</td>
                    </tr>
                    <tr>
                        <td style="padding: 6px 0; font-weight: 500;">Última Conexión:</td>
                        <td style="padding: 6px 0;">{last_used_text}</td>
                    </tr>
                    {deactivated_info}
                </table>
            </div>
        ''')
    usage_summary.short_description = "Resumen de Uso"
    
    def device_token_display(self, obj):
        """Muestra el token de forma segura - Paleta limones"""
        if obj.device_token:
            token_preview = obj.device_token[:12] + '...' + obj.device_token[-12:]
            return format_html(
                '<div style="background: #ffeaa7; padding: 12px; border-radius: 4px; border: 1px solid #fdcb6e;">'
                '<strong style="color: #2d3436; font-size: 12px;">CONFIDENCIAL</strong><br>'
                '<code style="font-size: 11px; color: #636e72;">{}</code>'
                '</div>',
                token_preview
            )
        return "No generado"
    device_token_display.short_description = "Device Token"

    # ========== ACCIONES ==========

    def deactivate_devices(self, request, queryset):
        """Acción para desactivar dispositivos seleccionados"""
        count = 0
        for device in queryset:
            device.deactivate()
            count += 1

        self.message_user(
            request,
            f"{count} dispositivo(s) desactivado(s) correctamente"
        )
    deactivate_devices.short_description = "Desactivar dispositivos seleccionados"

    def activate_devices(self, request, queryset):
        """Acción masiva para reactivar dispositivos"""
        from django.utils import timezone
        count = queryset.filter(is_active=False).update(
            is_active=True,
            deactivated_at=None
        )
        self.message_user(request, f"{count} dispositivo(s) reactivado(s) exitosamente.")
    activate_devices.short_description = "Reactivar dispositivos seleccionados"


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """
    Admin para gestión de perfiles y roles de usuarios.
    Control centralizado de permisos y configuración.
    """
    list_display = (
        'user_info',
        'role_badge',
        'organization_display',
        'permissions_display',
        'devices_summary',
        'created_date',
    )
    
    list_display_links = ('user_info',)
    
    list_filter = ('role', 'pin_configured', 'created_at', 'updated_at')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    readonly_fields = ('created_at', 'updated_at', 'pin_hash', 'pin_configured', 'last_device_activation', 'profile_summary')
    ordering = ('-created_at',)

    fieldsets = (
        ('Información del Usuario', {
            'fields': ('profile_summary',)
        }),
        ('Configuración de Perfil', {
            'fields': ('user', 'role', 'organization', 'created_by'),
        }),
        ('Autenticación Offline', {
            'fields': ('pin_configured', 'last_device_activation'),
            'description': 'El PIN debe ser configurado por el usuario desde la aplicación móvil.'
        }),
        ('Registro', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    # ========== MÉTODOS PARA VISTA DE LISTA ==========
    
    def user_info(self, obj):
        """Información del usuario - CLICKEABLE"""
        full_name = obj.user.get_full_name()
        email = obj.user.email
        
        return format_html(
            '<div style="line-height: 1.6;">'
            '<strong style="font-size: 13px; color: #333;">{}</strong><br>'
            '<span style="font-size: 11px; color: #666;">@{}</span><br>'
            '<span style="font-size: 11px; color: #999;">{}</span>'
            '</div>',
            full_name if full_name else obj.user.username,
            obj.user.username,
            email if email else 'Sin email'
        )
    user_info.short_description = "Usuario"
    
    def role_badge(self, obj):
        """Rol con badge de color - Paleta limones"""
        role_config = {
            'admin': {'color': '#f9ca24', 'text': 'ADMIN', 'text_color': '#2d3436'},      # Amarillo limón
            'worker': {'color': '#6ab04c', 'text': 'WORKER', 'text_color': 'white'},      # Verde limón
            'superadmin': {'color': '#ff9f43', 'text': 'SUPERADMIN', 'text_color': 'white'}, # Naranja
        }
        config = role_config.get(obj.role, {'color': '#95afc0', 'text': obj.role.upper(), 'text_color': 'white'})
        
        return format_html(
            '<span style="display: inline-block; padding: 4px 12px; background: {}; color: {}; '
            'border-radius: 12px; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;">{}</span>',
            config['color'],
            config['text_color'],
            config['text']
        )
    role_badge.short_description = "Rol"
    
    def organization_display(self, obj):
        """Organización del usuario"""
        if obj.organization:
            return format_html(
                '<span style="display: inline-block; padding: 4px 10px; background: #74b9ff; color: white; '
                'border-radius: 8px; font-size: 11px; font-weight: 500;">{}</span>',
                obj.organization.name
            )
        return format_html('<span style="color: #999; font-size: 11px;">Sin organización</span>')
    organization_display.short_description = "Organización"
    
    def permissions_display(self, obj):
        """Permisos del usuario - Paleta limones"""
        permissions = []
        
        if obj.user.is_superuser:
            return format_html(
                '<span style="display: inline-block; padding: 3px 8px; background: #ff9f43; color: white; '
                'border-radius: 3px; font-size: 10px; font-weight: 500;">SUPERUSER</span>'
            )
        
        if obj.user.is_staff:
            permissions.append(
                '<span style="display: inline-block; padding: 3px 8px; background: #636e72; color: white; '
                'border-radius: 3px; font-size: 10px; font-weight: 500; margin-right: 4px;">STAFF</span>'
            )
        
        if obj.pin_configured:
            permissions.append(
                '<span style="display: inline-block; padding: 3px 8px; background: #6ab04c; color: white; '
                'border-radius: 3px; font-size: 10px; font-weight: 500;">PIN</span>'
            )
        
        if permissions:
            return format_html(''.join(permissions))
        
        return format_html('<span style="color: #b2bec3; font-size: 11px;">Usuario básico</span>')
    permissions_display.short_description = "Permisos"
    
    def devices_summary(self, obj):
        """Resumen de dispositivos activos - Paleta limones"""
        active_devices = obj.user.activated_devices.filter(is_active=True).count()
        total_devices = obj.user.activated_devices.count()
        
        if active_devices > 0:
            return format_html(
                '<span style="font-size: 12px; color: #6ab04c; font-weight: 500;">{} activo(s)</span>'
                '<span style="font-size: 11px; color: #636e72;"> / {} total</span>',
                active_devices,
                total_devices
            )
        elif total_devices > 0:
            return format_html(
                '<span style="font-size: 11px; color: #636e72;">{} dispositivo(s)</span>',
                total_devices
            )
        
        return format_html('<span style="color: #b2bec3; font-size: 11px;">Sin dispositivos</span>')
    devices_summary.short_description = "Dispositivos"
    
    def created_date(self, obj):
        """Fecha de creación"""
        return obj.created_at.strftime('%d/%m/%Y')
    created_date.short_description = "Creado"
    
    # ========== MÉTODOS PARA VISTA DETALLADA ==========
    
    def profile_summary(self, obj):
        """Resumen completo del perfil"""
        full_name = obj.user.get_full_name() or obj.user.username
        
        # Role info - Paleta limones
        role_config = {
            'admin': {'color': '#f9ca24', 'text': 'ADMINISTRADOR'},
            'worker': {'color': '#6ab04c', 'text': 'TRABAJADOR'},
            'superadmin': {'color': '#ff9f43', 'text': 'SUPER ADMINISTRADOR'},
        }
        role = role_config.get(obj.role, {'color': '#95afc0', 'text': obj.role.upper()})
        
        # Permissions
        permissions_html = []
        if obj.user.is_superuser:
            permissions_html.append('<span style="padding: 3px 10px; background: #ff9f43; color: white; border-radius: 3px; font-size: 11px; margin-right: 6px;">SUPERUSER</span>')
        if obj.user.is_staff:
            permissions_html.append('<span style="padding: 3px 10px; background: #636e72; color: white; border-radius: 3px; font-size: 11px; margin-right: 6px;">STAFF</span>')
        if obj.pin_configured:
            permissions_html.append('<span style="padding: 3px 10px; background: #6ab04c; color: white; border-radius: 3px; font-size: 11px;">PIN CONFIGURADO</span>')
        
        permissions_display = ''.join(permissions_html) if permissions_html else '<span style="color: #b2bec3;">Sin permisos especiales</span>'
        
        # Devices
        active_devices = obj.user.activated_devices.filter(is_active=True).count()
        total_devices = obj.user.activated_devices.count()
        
        devices_text = f"{active_devices} activo(s) de {total_devices} total(es)" if total_devices > 0 else "Sin dispositivos registrados"
        
        return mark_safe(f'''
            <div style="background: linear-gradient(135deg, #fdcb6e 0%, #6ab04c 100%); padding: 20px; border-radius: 8px; color: white;">
                <h2 style="margin: 0 0 10px 0; font-size: 20px; text-shadow: 1px 1px 2px rgba(0,0,0,0.1);">{full_name}</h2>
                <p style="margin: 0 0 15px 0; font-size: 13px; opacity: 0.95;">@{obj.user.username} • {obj.user.email or 'Sin email'}</p>
                <div style="margin-bottom: 10px;">
                    <span style="display: inline-block; padding: 5px 15px; background: {role['color']}; color: #2d3436; 
                    border-radius: 15px; font-size: 12px; font-weight: 600;">{role['text']}</span>
                </div>
            </div>
            
            <div style="background: #f8f9fa; padding: 15px; border-radius: 4px; margin-top: 15px;">
                <table style="width: 100%; font-size: 13px;">
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500; width: 140px;">Permisos:</td>
                        <td style="padding: 8px 0;">{permissions_display}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Dispositivos:</td>
                        <td style="padding: 8px 0;">{devices_text}</td>
                    </tr>
                    <tr>
                        <td style="padding: 8px 0; font-weight: 500;">Miembro desde:</td>
                        <td style="padding: 8px 0;">{obj.created_at.strftime('%d/%m/%Y')}</td>
                    </tr>
                </table>
            </div>
        ''')
    profile_summary.short_description = "Perfil del Usuario"


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    """
    Admin para gestionar organizaciones (multi-tenancy).
    Cada organización puede tener múltiples usuarios.
    """
    list_display = (
        'name',
        'slug',
        'country',
        'region',
        'is_active',
        'created_at',
        'users_count',
    )
    
    list_filter = (
        'is_active',
        'country',
        'created_at',
    )
    
    search_fields = (
        'name',
        'slug',
        'country',
        'region',
    )
    
    readonly_fields = (
        'slug',
        'created_at',
        'users_list',
    )
    
    ordering = ('name',)
    
    fieldsets = (
        ('Información Básica', {
            'fields': (
                'name',
                'slug',
                'logo',
            ),
        }),
        ('Ubicación', {
            'fields': (
                'country',
                'region',
            ),
        }),
        ('Estado', {
            'fields': (
                'is_active',
                'created_at',
            ),
        }),
        ('Usuarios', {
            'fields': ('users_list',),
            'classes': ('collapse',),
        }),
    )
    
    def users_count(self, obj):
        """Número de usuarios en esta organización"""
        count = obj.profiles.count()
        if count == 0:
            return format_html('<span style="color: #999;">0 usuarios</span>')
        return format_html(
            '<span style="background: #4CAF50; color: white; padding: 3px 10px; border-radius: 12px; font-size: 11px; font-weight: 600;">{} usuario(s)</span>',
            count
        )
    users_count.short_description = "Usuarios"
    
    def users_list(self, obj):
        """Lista de usuarios en esta organización"""
        users = obj.profiles.select_related('user').all()
        if not users:
            return format_html('<p style="color: #999;">No hay usuarios en esta organización.</p>')
        
        users_html = '<div style="background: #f8f9fa; padding: 15px; border-radius: 4px;">'
        users_html += '<h3 style="margin-top: 0;">Usuarios en esta organización:</h3>'
        users_html += '<ul style="list-style: none; padding: 0;">'
        
        for profile in users:
            user = profile.user
            role_colors = {
                'superadmin': '#e74c3c',
                'admin': '#3498db',
                'worker': '#27ae60',
            }
            role_color = role_colors.get(profile.role, '#95a5a6')
            
            users_html += f'''
            <li style="padding: 10px; margin-bottom: 8px; background: white; border-left: 3px solid {role_color}; border-radius: 4px;">
                <strong>{user.username}</strong> 
                <span style="color: #7f8c8d;">({user.first_name} {user.last_name})</span>
                <span style="background: {role_color}; color: white; padding: 2px 8px; border-radius: 10px; font-size: 10px; margin-left: 10px;">{profile.role.upper()}</span>
            </li>
            '''
        
        users_html += '</ul></div>'
        return mark_safe(users_html)
    users_list.short_description = "Usuarios"


# =============================
# ADMIN REQUEST
# =============================

@admin.register(AdminRequest)
class AdminRequestAdmin(admin.ModelAdmin):
    """
    Admin para solicitudes de acceso como administrador.
    Permite aprobar o rechazar solicitudes.
    """
    list_display = (
        'id',
        'applicant_info',
        'organization_name',
        'country_region',
        'status_badge',
        'created_at_display',
    )
    
    list_display_links = ('id', 'applicant_info')
    
    list_filter = (
        'status',
        'country',
        'created_at',
    )
    
    search_fields = (
        'first_name',
        'last_name',
        'email',
        'organization_name',
        'phone',
    )
    
    readonly_fields = (
        'id',
        'first_name',
        'last_name',
        'email',
        'phone',
        'organization_name',
        'country',
        'region',
        'ip_address',
        'user_agent',
        'created_at',
        'reviewed_at',
        'reviewed_by',
    )
    
    fieldsets = (
        ('Información del Solicitante', {
            'fields': (
                'id',
                'first_name',
                'last_name',
                'email',
                'phone',
            ),
        }),
        ('Organización', {
            'fields': (
                'organization_name',
                'country',
                'region',
            ),
        }),
        ('Estado', {
            'fields': (
                'status',
                'rejection_reason',
                'reviewed_at',
                'reviewed_by',
            ),
        }),
        ('Información Técnica', {
            'fields': (
                'ip_address',
                'user_agent',
                'created_at',
            ),
            'classes': ('collapse',),
        }),
    )
    
    ordering = ('-created_at',)
    
    actions = ['approve_requests', 'reject_requests']
    
    def applicant_info(self, obj):
        """Información del solicitante"""
        return format_html(
            '<div style="line-height: 1.5;">'
            '<strong style="font-size: 13px;">{} {}</strong><br>'
            '<span style="font-size: 11px; color: #666;">{}</span>'
            '</div>',
            obj.first_name,
            obj.last_name,
            obj.email
        )
    applicant_info.short_description = "Solicitante"
    
    def country_region(self, obj):
        """País y región"""
        return format_html(
            '<div style="line-height: 1.3;">'
            '<strong>{}</strong><br>'
            '<span style="font-size: 11px; color: #666;">{}</span>'
            '</div>',
            obj.country,
            obj.region
        )
    country_region.short_description = "Ubicación"
    
    def status_badge(self, obj):
        """Badge de estado"""
        colors = {
            'pending': '#FFA726',
            'approved': '#66BB6A',
            'rejected': '#EF5350',
        }
        labels = {
            'pending': 'Pendiente',
            'approved': 'Aprobada',
            'rejected': 'Rechazada',
        }
        return format_html(
            '<span style="background: {}; color: white; padding: 4px 12px; border-radius: 12px; font-size: 11px; font-weight: 600;">{}</span>',
            colors.get(obj.status, '#999'),
            labels.get(obj.status, obj.status)
        )
    status_badge.short_description = "Estado"
    
    def created_at_display(self, obj):
        """Fecha de creación en formato corto"""
        from django.utils import timezone
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff.days == 0:
            if diff.seconds < 3600:
                mins = diff.seconds // 60
                return format_html('<span style="color: #4CAF50; font-weight: 600;">Hace {} min</span>', mins)
            else:
                hours = diff.seconds // 3600
                return format_html('<span style="color: #4CAF50;">Hace {} h</span>', hours)
        elif diff.days == 1:
            return "Ayer"
        elif diff.days < 7:
            return f"Hace {diff.days} días"
        else:
            return obj.created_at.strftime("%d/%m/%Y")
    created_at_display.short_description = "Fecha"
    
    def approve_requests(self, request, queryset):
        """Acción para aprobar solicitudes - ENVÍO AUTOMÁTICO DE CREDENCIALES POR EMAIL"""
        from django.contrib.auth.models import User
        from .models import UserProfile, Organization, generate_unique_username, generate_temp_password
        from django.utils import timezone
        from .email_utils import send_approval_email
        
        approved_count = 0
        errors = []
        approved_users = []  # Lista para mostrar usuarios aprobados
        
        for admin_request in queryset.filter(status='pending'):
            try:
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"🔄 INICIANDO aprobación de {admin_request.email}")
                
                # Generar username único
                username = generate_unique_username(
                    admin_request.email,
                    admin_request.first_name,
                    admin_request.last_name
                )
                logger.info(f"✅ Username generado: {username}")
                
                # Generar contraseña temporal pronunciable
                temp_password = generate_temp_password()
                logger.info(f"✅ Password temporal generada")
                
                # Crear o buscar organización
                logger.info(f"🔄 Creando/buscando organización: {admin_request.organization_name}")
                organization, created = Organization.objects.get_or_create(
                    name=admin_request.organization_name,
                    defaults={
                        'country': admin_request.country,
                        'region': admin_request.region,
                    }
                )
                logger.info(f"✅ Organización {'creada' if created else 'encontrada'}: {organization.name}")
                
                # Buscar usuario existente por email o username
                logger.info(f"🔄 Buscando usuario existente con email: {admin_request.email}")
                user = User.objects.filter(email=admin_request.email).first()
                
                if user:
                    # Usuario ya existe - actualizar contraseña y datos
                    logger.info(f"⚠️ Usuario YA EXISTE (username: {user.username}, ID: {user.id})")
                    logger.info(f"🔄 Actualizando datos del usuario existente...")
                    user.first_name = admin_request.first_name
                    user.last_name = admin_request.last_name
                    user.set_password(temp_password)
                    user.save()
                    logger.info(f"✅ Usuario actualizado exitosamente")
                else:
                    # Usuario nuevo - crear
                    logger.info(f"🔄 Usuario NO existe, creando NUEVO usuario...")
                    logger.info(f"   - Username: {username}")
                    logger.info(f"   - Email: {admin_request.email}")
                    logger.info(f"   - Nombre: {admin_request.first_name} {admin_request.last_name}")
                    
                    user = User.objects.create_user(
                        username=username,
                        email=admin_request.email,
                        first_name=admin_request.first_name,
                        last_name=admin_request.last_name,
                        password=temp_password,
                    )
                    logger.info(f"✅ Usuario creado exitosamente (ID: {user.id}, username: {user.username})")
                
                # Crear UserProfile
                logger.info(f"🔄 Creando/actualizando UserProfile para user ID {user.id}...")
                profile, created = UserProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        'role': 'admin',
                        'organization': organization,
                        'created_by': request.user,
                        'password_change_required': True,
                    }
                )
                logger.info(f"✅ UserProfile {'creado' if created else 'encontrado'} (ID: {profile.id})")
                
                if not created:
                    logger.info(f"🔄 Actualizando UserProfile existente...")
                    profile.role = 'admin'
                    profile.organization = organization
                    profile.created_by = request.user
                    profile.password_change_required = True
                    profile.save()
                    logger.info(f"✅ UserProfile actualizado")
                
                # Actualizar AdminRequest
                logger.info(f"🔄 Actualizando estado de AdminRequest a 'approved'...")
                admin_request.status = 'approved'
                admin_request.reviewed_by = request.user
                admin_request.reviewed_at = timezone.now()
                admin_request.save()
                logger.info(f"✅ AdminRequest actualizado a 'approved'")
                
                # Enviar email con credenciales (SendGrid HTTP API)
                # Usar el username real del usuario (puede ser existente o nuevo)
                actual_username = user.username
                logger.info(f"🔄 Intentando enviar email de aprobación a {admin_request.email} con username: {actual_username}")
                
                email_sent = send_approval_email(admin_request, actual_username, temp_password)
                
                if email_sent:
                    logger.info(f"✅ Email de credenciales enviado exitosamente a {admin_request.email}")
                else:
                    logger.error(f"❌ FALLO al enviar email de credenciales a {admin_request.email}")
                
                approved_count += 1
                
                # Guardar info del usuario aprobado para mostrar
                approved_users.append({
                    'name': f"{admin_request.first_name} {admin_request.last_name}",
                    'email': admin_request.email,
                    'username': actual_username,
                    'email_sent': email_sent,
                })
                
            except Exception as e:
                # Mostrar error completo en Django Admin Y en logs
                import logging
                import traceback
                logger = logging.getLogger(__name__)
                
                error_detail = f"{admin_request.email}: {type(e).__name__}: {str(e)}"
                traceback_str = traceback.format_exc()
                
                logger.error(f"❌ ERROR al aprobar solicitud de {admin_request.email}")
                logger.error(f"❌ Error: {error_detail}")
                logger.error(f"❌ Traceback:\n{traceback_str}")
                
                # Agregar error detallado para mostrar en Django Admin
                errors.append(error_detail)
        
        if approved_count > 0:
            # Construir mensaje con información de usuarios aprobados
            users_info = "\n".join([
                f"• {u['name']} ({u['email']}) -> Username: {u['username']} "
                f"{'[Email enviado]' if u['email_sent'] else '[Email NO enviado]'}"
                for u in approved_users
            ])
            
            emails_sent = sum(1 for u in approved_users if u['email_sent'])
            
            self.message_user(
                request,
                f"✅ {approved_count} solicitud(es) aprobada(s):\n\n{users_info}\n\n"
                f"� Emails enviados: {emails_sent}/{approved_count}\n\n"
                f"✨ Los usuarios recibieron un email con:\n"
                f"   • Username\n"
                f"   • Password temporal\n"
                f"   • Instrucciones para cambiar contraseña\n\n"
                f"⚠️ IMPORTANTE: Los usuarios DEBEN cambiar su contraseña en el primer login."
            )
        
        if errors:
            self.message_user(
                request,
                f"❌ Errores: {', '.join(errors)}",
                level='error'
            )
    
    approve_requests.short_description = "✅ Aprobar solicitudes seleccionadas"
    
    def reject_requests(self, request, queryset):
        """Acción para rechazar solicitudes"""
        from .email_utils import send_rejection_email
        from django.utils import timezone
        
        rejected_count = 0
        
        for admin_request in queryset.filter(status='pending'):
            try:
                admin_request.status = 'rejected'
                admin_request.reviewed_by = request.user
                admin_request.reviewed_at = timezone.now()
                
                # Por defecto usar razón genérica si no hay una específica
                if not admin_request.rejection_reason:
                    admin_request.rejection_reason = (
                        "Después de revisar tu solicitud, hemos decidido no aprobarla en este momento. "
                        "Si tienes preguntas, por favor contáctanos."
                    )
                
                admin_request.save()
                
                # Enviar email
                send_rejection_email(admin_request)
                
                rejected_count += 1
                
            except Exception as e:
                self.message_user(
                    request,
                    f"Error rechazando {admin_request.email}: {str(e)}",
                    level='error'
                )
        
        if rejected_count > 0:
            self.message_user(
                request,
                f"❌ {rejected_count} solicitud(es) rechazada(s)."
            )
    
    reject_requests.short_description = "❌ Rechazar solicitudes seleccionadas"
