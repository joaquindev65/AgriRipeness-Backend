from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.auth import authenticate
from .models import AnalysisRecord, PasswordResetToken, WorkerAPIKey, AdminRequest, UserProfile, Organization
import json

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'password', 'password_confirm')
        
    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('El email ya está en uso.')
        return value

    def validate(self, attrs):
        print('DEBUG PAYLOAD:', attrs)
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Las contraseñas no coinciden"})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)  # write_only para no retornar en response

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        # Paso 1: Buscar usuario por email
        try:
            from django.contrib.auth.models import User
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError("Credenciales inválidas")
        
        # Paso 2: Autenticar con username (Django requiere username internamente)
        from django.contrib.auth import authenticate
        user = authenticate(username=user.username, password=password)
        if not user:
            raise serializers.ValidationError("Credenciales inválidas")
        
        # Paso 3: Agregar usuario a attrs para uso en view
        attrs['user'] = user
        return attrs
    
class UserSerializerMin(serializers.ModelSerializer):
    api_key = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'first_name', 'last_name', 'email', 'is_active', 'date_joined', 'api_key')

    def get_api_key(self, obj):
        """Obtiene la API key activa del worker (solo prefijo)"""
        api_key = obj.api_keys.filter(is_active=True).order_by('-created_at').first()
        if api_key:
            return api_key.key_prefix + "..."
        return None

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name']

class UserProfileSerializer(serializers.ModelSerializer):
    user = UserSerializerMin(read_only=True)
    organization = OrganizationSerializer(read_only=True)
    organization_id = serializers.PrimaryKeyRelatedField(queryset=Organization.objects.all(), source='organization', write_only=True, required=False)

    class Meta:
        model = UserProfile
        fields = [
            'id', 'user', 'role', 'organization', 'organization_id',
            'created_by'
        ]
        read_only_fields = ('id', 'user', 'organization', 'created_by')


class JSONStringField(serializers.JSONField):
    """
    Custom JSONField that handles string inputs from FormData
    """
    def __init__(self, *args, **kwargs):
        self.default_value = kwargs.pop('default_value', None)
        super().__init__(*args, **kwargs)
    
    def to_internal_value(self, data):
        # Obtener nombre del campo para debug específico
        field_name = getattr(self, 'field_name', getattr(self, 'source', 'unknown_field'))
        
        debug_info = f"JSONStringField[{field_name}].to_internal_value: {type(data)} = {str(data)[:200]}..."
        print(debug_info)
        
        # Debug file específico para JSONStringField
        try:
            with open('debug_jsonfield.log', 'a', encoding='utf-8') as f:
                from django.utils import timezone
                f.write(f"{timezone.now()}: {debug_info}\n")
        except:
            pass
        
        if data is None or data == '':
            print(f"- [{field_name}] Returning default for empty data")
            return self.default_value if self.default_value is not None else {}
            
        # DETECCIÓN ESPECIAL: Django REST Framework JSONString object
        data_str = str(data)  # Convertir a string sin importar el tipo
        
        if isinstance(data, str) or 'JSONString' in str(type(data)):
            try:
                import json
                parsed = json.loads(data_str)
                print(f"- [{field_name}] Successfully parsed JSON: {type(parsed)} with {len(str(parsed))} chars")
                # Debug file con resultado exitoso
                try:
                    with open('debug_jsonfield.log', 'a', encoding='utf-8') as f:
                        f.write(f"   SUCCESS: Parsed to {type(parsed)} with content: {str(parsed)[:100]}...\n")
                except:
                    pass
                return parsed
            except (json.JSONDecodeError, TypeError) as e:
                print(f"- [{field_name}] JSON parse error: {e}")
                
                # ARREGLO ESPECÍFICO: Detectar Python dict/list strings y convertirlos
                print(f"- [{field_name}] Attempting Python literal evaluation...")
                try:
                    import ast
                    # Usar ast.literal_eval que es seguro para evaluar literales de Python
                    parsed = ast.literal_eval(data_str)
                    print(f"- [{field_name}] SUCCESS with ast.literal_eval: {type(parsed)}")
                    # Debug file con éxito de AST
                    try:
                        with open('debug_jsonfield.log', 'a', encoding='utf-8') as f:
                            f.write(f"   AST SUCCESS: Parsed to {type(parsed)} with content: {str(parsed)[:100]}...\n")
                    except:
                        pass
                    return parsed
                except (ValueError, SyntaxError) as ast_error:
                    print(f"- [{field_name}] AST parse also failed: {ast_error}")
                    # Debug file con error de AST
                    try:
                        with open('debug_jsonfield.log', 'a', encoding='utf-8') as f:
                            f.write(f"   ERROR: Both JSON and AST failed\n")
                            f.write(f"   JSON error: {e}\n")
                            f.write(f"   AST error: {ast_error}\n")
                            f.write(f"   Raw data: {repr(data_str[:200])}\n")
                    except:
                        pass
                
                # Si ambos métodos fallan, devolver valor por defecto
                if field_name == 'analysis_metadata':
                    return {}
                elif field_name == 'detected_lemons':
                    return []
                return self.default_value if self.default_value is not None else {}
                
        # Si ya es dict/list, devolverlo tal como está
        if isinstance(data, (dict, list)):
            print(f"- [{field_name}] Data already parsed: {type(data)} with {len(data) if hasattr(data, '__len__') else 'N/A'} items")
            # Debug file con éxito de dict/list
            try:
                with open('debug_jsonfield.log', 'a', encoding='utf-8') as f:
                    f.write(f"   PASSTHROUGH: {type(data)} with content: {str(data)[:100]}...\n")
            except:
                pass
            return data
            
        # Para cualquier otro tipo, usar superclase
        print(f"- [{field_name}] Using superclass for type: {type(data)}")
        return super().to_internal_value(data)

class AnalysisRecordSerializer(serializers.ModelSerializer):
    """
    Serializer para registros de análisis de medios (solo imágenes).
    Incluye validaciones personalizadas, campos computados y manejo de conteo de limones.
    """
    user_id = serializers.IntegerField(source='user.id', read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)
    local_id = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    days_since_created = serializers.SerializerMethodField()
    file_size_mb = serializers.ReadOnlyField()
    media_file_url = serializers.SerializerMethodField()
    processed_media_url = serializers.ReadOnlyField()
    annotated_image = serializers.CharField(read_only=True)
    
    # Campos específicos que el frontend espera
    detection_boxes_length = serializers.SerializerMethodField()
    detections_count = serializers.SerializerMethodField()
    
    # Custom fields for JSON handling
    analysis_metadata = JSONStringField(required=False, allow_null=True, default_value={})
    detected_lemons = JSONStringField(required=False, allow_null=True, default_value=[])
    
    class Meta:
        model = AnalysisRecord
        fields = [
            "id",
            "user_id",
            "local_id",
            "user_username",
            "media_type",
            "source_type",
            "original_image",
            "processed_image_url",
            "media_file_url",
            "processed_media_url",
            "total_lemons_count",
            "detection_confidence",
            "processing_time",
            "model_type",
            "analysis_metadata",
            "detected_lemons",
            "file_size_mb",
            "created_at",
            "updated_at",
            "days_since_created",
            "annotated_image",
            "detection_boxes_length",
            "detections_count",
        ]
        read_only_fields = [
            "id",
            "user_id",  # ID del usuario (solo lectura)
            "created_at", 
            "updated_at",
            "user_username", 
            "days_since_created",
            "file_size_mb",
            "ripeness_distribution",
            "media_file_url",
            "processed_media_url"
        ]
    
    def create(self, validated_data):
        """
        Crear registro de análisis.
        """
        # Crear la instancia
        instance = super().create(validated_data)
        
        print(f"✅ Análisis creado: ID {instance.id} con {instance.total_lemons_count} limones")
        
        return instance
    
    def get_days_since_created(self, obj):
        """Calcula los días transcurridos desde la creación del análisis."""
        from django.utils import timezone
        delta = timezone.now() - obj.created_at
        return delta.days
    
    def get_media_file_url(self, obj):
        """Retorna la URL del archivo de media principal."""
        media_file = obj.media_file
        if media_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(media_file.url)
            return media_file.url
        return None
    
    def get_detection_boxes_length(self, obj):
        """Retorna la longitud del array de detection_boxes en analysis_metadata."""
        if obj.analysis_metadata and isinstance(obj.analysis_metadata, dict):
            detection_boxes = obj.analysis_metadata.get('detection_boxes', [])
            return len(detection_boxes) if detection_boxes else 0
        return 0
    
    def get_detections_count(self, obj):
        """Retorna el número de detecciones encontradas."""
        if obj.detected_lemons and isinstance(obj.detected_lemons, list):
            return len(obj.detected_lemons)
        return obj.total_lemons_count  # Fallback al conteo total
    
    def validate(self, attrs):
        """Validaciones a nivel de serializer."""
        media_type = attrs.get('media_type')
        original_image = attrs.get('original_image')
        
        # Validar que se tenga el archivo correcto según el tipo de medio
        if media_type == 'image':
            if not original_image:
                raise serializers.ValidationError({
                    'original_image': 'Se requiere una imagen para análisis de tipo imagen.'
                })
        
        return attrs
    
    def validate_original_image(self, value):
        """Valida el archivo de imagen original."""
        if value:
            # Validar tamaño máximo (10MB)
            if value.size > 10 * 1024 * 1024:
                raise serializers.ValidationError("La imagen no puede superar los 10MB.")
            
            # Validar formato de imagen
            valid_formats = ['image/jpeg', 'image/png', 'image/jpg', 'image/webp']
            if hasattr(value, 'content_type') and value.content_type not in valid_formats:
                raise serializers.ValidationError("Formato de imagen no válido. Use JPEG, PNG o WebP.")
        
        return value
    
    def validate_detection_confidence(self, value):
        """Valida que la confianza de detección esté en el rango correcto."""
        if value is not None and not (0 <= value <= 1):
            raise serializers.ValidationError("La confianza debe estar entre 0 y 1.")
        return value
    
    def validate_analysis_metadata(self, value):
        """Valida que los metadatos sean un diccionario válido o JSON string."""
        # Debug para capturar el problema
        debug_info = f"VALIDATE_ANALYSIS_METADATA: {type(value)} = {value}"
        print(debug_info)
        
        try:
            with open('debug_validation.log', 'a', encoding='utf-8') as f:
                from django.utils import timezone
                f.write(f"{timezone.now()}: {debug_info}\n")
        except:
            pass
            
        # Casos explícitos para evitar problemas
        if value is None:
            print(f"- Value is None, returning empty dict")
            return {}
            
        if value == "":
            print(f"- Value is empty string, returning empty dict")
            return {}
            
        # Si es string, intentar parsearlo como JSON
        if isinstance(value, str):
            try:
                import json
                parsed = json.loads(value)
                print(f"- Parsed JSON from string: {parsed}")
                return parsed
            except json.JSONDecodeError as e:
                print(f"- JSON parse error: {e}, returning empty dict")
                return {}
                
        # Si ya es dict, retornarlo tal como está
        if isinstance(value, dict):
            print(f"- Value is dict with {len(value)} keys, returning as-is")
            return value
            
        # Para cualquier otro tipo, convertir a dict vacío
        print(f"- Unexpected type {type(value)}, returning empty dict")
        return {}
        
    def validate_detected_lemons(self, value):
        """Valida que las detecciones sean una lista válida o JSON string."""
        # Debug para capturar el problema
        debug_info = f"VALIDATE_DETECTED_LEMONS: {type(value)} = {value}"
        print(debug_info)
        
        try:
            with open('debug_validation.log', 'a', encoding='utf-8') as f:
                from django.utils import timezone
                f.write(f"{timezone.now()}: {debug_info}\n")
        except:
            pass
            
        # Casos explícitos para evitar problemas
        if value is None:
            print(f"- Value is None, returning empty list")
            return []
            
        if value == "":
            print(f"- Value is empty string, returning empty list")
            return []
            
        # Si es string, intentar parsearlo como JSON
        if isinstance(value, str):
            try:
                import json
                parsed = json.loads(value)
                print(f"- Parsed JSON from string: {parsed}")
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError as e:
                print(f"- JSON parse error: {e}, returning empty list")
                return []
                
        # Si ya es list, retornarlo tal como está
        if isinstance(value, list):
            print(f"- Value is list with {len(value)} items, returning as-is")
            return value
            
        # Para cualquier otro tipo, convertir a lista vacía
        print(f"- Unexpected type {type(value)}, returning empty list")
        return []


class AnalysisRecordListSerializer(serializers.ModelSerializer):
    """
    Serializer optimizado para listados de registros de análisis.
    Incluye solo los campos esenciales para mejorar el rendimiento.
    """
    user_username = serializers.CharField(source='user.username', read_only=True)
    media_file_url = serializers.SerializerMethodField()
    
    # Campos específicos que el frontend espera
    detection_boxes_length = serializers.SerializerMethodField()
    detections_count = serializers.SerializerMethodField()
    
    class Meta:
        model = AnalysisRecord
        fields = [
            "id",
            "user_username",
            "media_type", 
            "source_type",
            "media_file_url",
            "total_lemons_count",
            "detection_confidence",
            "created_at",
            "detection_boxes_length",
            "detections_count", 
            "annotated_image"
        ]
    
    def get_media_file_url(self, obj):
        """Retorna la URL del archivo de media principal."""
        media_file = obj.media_file
        if media_file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(media_file.url)
            return media_file.url
        return None
    
    def get_detection_boxes_length(self, obj):
        """Retorna la longitud del array de detection_boxes en analysis_metadata."""
        if obj.analysis_metadata and isinstance(obj.analysis_metadata, dict):
            detection_boxes = obj.analysis_metadata.get('detection_boxes', [])
            return len(detection_boxes) if detection_boxes else 0
        return 0
    
    def get_detections_count(self, obj):
        """Retorna el número de detecciones encontradas."""
        if obj.detected_lemons and isinstance(obj.detected_lemons, list):
            return len(obj.detected_lemons)
        return obj.total_lemons_count  # Fallback al conteo total


class AnalysisStatsSerializer(serializers.Serializer):
    """
    Serializer para estadísticas de análisis del usuario.
    Útil para el dashboard futuro.
    """
    total_analyses = serializers.IntegerField()
    total_lemons_detected = serializers.IntegerField()
    total_images = serializers.IntegerField()
    avg_lemons_per_analysis = serializers.FloatField()
    last_analysis_date = serializers.DateTimeField()
    ripeness_totals = serializers.DictField()
    monthly_analysis_count = serializers.ListField()

class DetectionBoxSerializer(serializers.Serializer):
    class_name = serializers.CharField(required=True)
    confidence = serializers.FloatField(min_value=0, max_value=1, required=True)
    bbox = serializers.ListField(
        child=serializers.FloatField(), min_length=4, max_length=4, required=True
    )

class AnalysisMetadataSerializer(serializers.Serializer):
    processing_time = serializers.FloatField(min_value=0, required=True)
    confidence_avg = serializers.FloatField(min_value=0, max_value=1, required=True)
    detection_boxes = DetectionBoxSerializer(many=True, required=True)
    timestamp = serializers.DateTimeField(required=True)
    model_used = serializers.CharField(required=True)
    inference_time = serializers.FloatField(min_value=0, required=False)
    total_lemons_count = serializers.IntegerField(min_value=0, required=False)


# ========== SERIALIZERS PARA RESTABLECIMIENTO DE CONTRASEÑA ==========

class PasswordResetRequestSerializer(serializers.Serializer):
    """
    Serializer para solicitar restablecimiento de contraseña.
    Solo requiere el email del usuario.
    """
    email = serializers.EmailField(required=True)
    
    def validate_email(self, value):
        """Valida que el email exista en el sistema"""
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(
                "No existe un usuario registrado con este email."
            )
        return value
    
    def get_user(self):
        """Retorna el usuario asociado al email validado"""
        email = self.validated_data['email']
        return User.objects.get(email=email)


class PasswordResetConfirmSerializer(serializers.Serializer):
    """
    Serializer para confirmar restablecimiento de contraseña con token.
    Requiere el token y la nueva contraseña.
    """
    token = serializers.CharField(required=True, max_length=64)
    new_password = serializers.CharField(required=True, min_length=6, max_length=128)
    confirm_password = serializers.CharField(required=True, min_length=6, max_length=128)
    
    def validate_token(self, value):
        """Valida que el token exista y sea válido"""
        from .models import PasswordResetToken
        
        try:
            token_obj = PasswordResetToken.objects.get(token=value)
            if not token_obj.is_valid():
                raise serializers.ValidationError(
                    "El token ha expirado o ya ha sido usado. Solicite un nuevo restablecimiento."
                )
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError(
                "Token inválido. Verifique el enlace o solicite un nuevo restablecimiento."
            )
        
        return value
    
    def validate(self, attrs):
        """Valida que las contraseñas coincidan"""
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({
                'confirm_password': 'Las contraseñas no coinciden.'
            })
        return attrs
    
    def get_token_object(self):
        """Retorna el objeto token asociado"""
        from .models import PasswordResetToken
        return PasswordResetToken.objects.get(token=self.validated_data['token'])
    
    def save(self):
        """Actualiza la contraseña del usuario y marca el token como usado"""
        token_obj = self.get_token_object()
        user = token_obj.user
        
        # Actualizar contraseña
        user.set_password(self.validated_data['new_password'])
        user.save()
        
        # Marcar token como usado
        token_obj.mark_as_used()
        
        return user


class PasswordChangeSerializer(serializers.Serializer):
    """
    Serializer para cambiar contraseña cuando el usuario está autenticado.
    
    **Flujo de Uso**:
    1. Usuario logueado con password_change_required=True
    2. Frontend muestra pantalla de cambio forzado
    3. Usuario envía contraseña actual + nueva
    4. Backend valida y actualiza
    5. Flag password_change_required se marca False automáticamente
    
    Fields:
        current_password (CharField): Contraseña actual (para verificación) - REQUERIDO
        new_password (CharField): Nueva contraseña (min 6, max 128 caracteres) - REQUERIDO
        confirm_password (CharField): Confirmación de nueva contraseña - OPCIONAL
            Si se omite, se asume que el frontend ya validó la contraseña
    
    Validations:
        - current_password: Debe coincidir con hash actual en BD
        - new_password: Mínimo 6 caracteres (Django validations adicionales en settings)
        - confirm_password: Si se provee, debe ser idéntica a new_password
    
    **SOPORTE QA**: Acepta ambos esquemas:
        1. Con confirmación: {current_password, new_password, confirm_password}
        2. Sin confirmación: {current_password, new_password} (frontend validó previamente)
    
    Side Effects:
        - Actualiza User.password con hash bcrypt/PBKDF2
        - Actualiza UserProfile.password_change_required = False
        - Invalida sesiones anteriores (user.set_password lo hace automáticamente)
    
    Security:
        - Requiere autenticación (IsAuthenticated permission)
        - Rate limited a 3/minuto en la vista
        - Contraseña nunca en logs ni response
    
    Example:
        >>> serializer = PasswordChangeSerializer(
        ...     data={
        ...         "current_password": "OldPass123",
        ...         "new_password": "NewSecurePass123!",
        ...         "confirm_password": "NewSecurePass123!"
        ...     },
        ...     user=request.user
        ... )
        >>> if serializer.is_valid():
        ...     user = serializer.save()  # Password actualizada + flag en False
    """
    current_password = serializers.CharField(required=True, write_only=True)
    new_password = serializers.CharField(required=True, min_length=6, max_length=128, write_only=True)
    confirm_password = serializers.CharField(required=False, min_length=6, max_length=128, write_only=True, allow_blank=True)
    
    def __init__(self, *args, **kwargs):
        """
        Constructor que recibe el usuario autenticado desde la vista.
        
        Args:
            user (User): Usuario que quiere cambiar su contraseña (desde request.user)
        """
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
    
    def validate_current_password(self, value):
        """
        Valida que la contraseña actual sea correcta.
        
        Args:
            value (str): Contraseña actual proporcionada por el usuario
        
        Returns:
            str: La misma contraseña si es válida
        
        Raises:
            ValidationError: Si la contraseña actual es incorrecta
        """
        if not self.user or not self.user.check_password(value):
            raise serializers.ValidationError('La contraseña actual es incorrecta.')
        return value
    
    def validate(self, attrs):
        """
        Valida que las contraseñas nuevas coincidan (si confirm_password está presente).
        
        **SOPORTE QA**: Acepta confirm_password opcional para compatibilidad con frontend.
        Si no se provee, se asume validación en frontend y se registra en logs para auditoría.
        
        Args:
            attrs (dict): Diccionario con contraseñas
        
        Returns:
            dict: attrs validado
        
        Raises:
            ValidationError: Si confirm_password se provee y no coincide con new_password
        """
        import logging
        logger = logging.getLogger('users.password')
        
        confirm_password = attrs.get('confirm_password', '').strip()
        
        # Si confirm_password está presente y no vacío, validar que coincida
        if confirm_password:
            if attrs['new_password'] != confirm_password:
                raise serializers.ValidationError({
                    'confirm_password': 'Las contraseñas no coinciden.'
                })
        else:
            # Log de advertencia para auditoría (QA pidió registro)
            user_email = self.user.email if self.user else 'unknown'
            logger.warning(
                f"⚠️ Password change sin confirm_password | User: {user_email} | "
                f"Frontend validó previamente (compatibilidad QA)"
            )
        
        return attrs
    
    def save(self):
        """
        Actualiza la contraseña del usuario y marca password_change_required=False.
        
        **IMPORTANTE**: Este método tiene side effects:
        - User.password se actualiza con hash
        - UserProfile.password_change_required se marca False
        - Sesiones anteriores del usuario se invalidan automáticamente
        
        Returns:
            User: Usuario con contraseña actualizada
        """
        # Actualizar contraseña (Django hashea automáticamente)
        self.user.set_password(self.validated_data['new_password'])
        self.user.save()
        
        # Marcar que ya no requiere cambio de contraseña
        if hasattr(self.user, 'profile'):
            self.user.profile.password_change_required = False
            self.user.profile.save()
        
        return self.user


# ========== SERIALIZERS PARA API KEYS ==========

class WorkerAPIKeySerializer(serializers.ModelSerializer):
    """
    Serializer para WorkerAPIKey.
    Muestra la key en texto plano SOLO en la creación (una vez).
    En listados, solo muestra el prefijo para identificación.
    """
    # Campo extra para retornar la key en texto plano solo al crear
    key = serializers.CharField(read_only=True)
    user_username = serializers.CharField(source='user.username', read_only=True)

    class Meta:
        model = WorkerAPIKey
        fields = [
            'id',
            'user',
            'user_username',
            'name',
            'key',  # Solo se llena al crear
            'key_prefix',
            'created_at',
            'last_used_at',
            'is_active'
        ]
        read_only_fields = ['id', 'key_prefix', 'created_at', 'last_used_at', 'key']

    def create(self, validated_data):
        """
        Crea una nueva API key.
        Retorna la instancia con el campo 'key' temporal que contiene la key en texto plano.
        """
        user = validated_data.get('user')
        name = validated_data.get('name')

        # Crear la API key usando el método del modelo
        api_key_obj, plain_key = WorkerAPIKey.create_key(user=user, name=name)

        # Agregar el plain_key como atributo temporal para que se serialice
        api_key_obj.key = plain_key

        return api_key_obj

    def to_representation(self, instance):
        """
        Personaliza la representación del serializer.
        Solo muestra 'key' si existe (al crear), de lo contrario la omite.
        """
        representation = super().to_representation(instance)

        # Si no hay 'key' temporal (en listados), removerla del response
        if not hasattr(instance, 'key'):
            representation.pop('key', None)

        return representation
    
class WorkerAPIKeyListSerializer(serializers.ModelSerializer):
    """
    Serializer optimizado para listados de API keys.
    NO incluye la key completa, solo el prefijo para identificación.
    """
    user_username = serializers.CharField(source='user.username', read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = WorkerAPIKey
        fields = [
            'id',
            'user_username',
            'name',
            'key_prefix',
            'created_at',
            'last_used_at',
            'is_active',
            'status'
        ]

    def get_status(self, obj):
        """Retorna el estado de la API key en formato legible"""
        if not obj.is_active:
            return "Inactiva"
        elif obj.last_used_at:
            from django.utils import timezone
            days_since_use = (timezone.now() - obj.last_used_at).days
            if days_since_use == 0:
                return "Activa (usada hoy)"
            elif days_since_use == 1:
                return "Activa (usada ayer)"
            else:
                return f"Activa (usada hace {days_since_use} días)"
        else:
            return "Activa (nunca usada)"


# ========== SERIALIZERS PARA WORKERS MANAGEMENT ==========

class WorkerSerializer(serializers.ModelSerializer):
    api_key = serializers.SerializerMethodField()
    total_detections = serializers.SerializerMethodField()
    total_detections_today = serializers.SerializerMethodField()
    last_detection = serializers.SerializerMethodField()
    created_at = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'first_name',
            'last_name',
            'email',
            'is_active',
            'date_joined',
            'created_at',
            'api_key',
            'total_detections',
            'total_detections_today',
            'last_detection',
        ]
        read_only_fields = ['id', 'date_joined', 'created_at']

        
    def get_created_at(self, obj):
    # Devuelve el valor de date_joined (alias profesional para created_at)
        return obj.date_joined

    def get_api_key(self, obj):
        """Obtiene la API key activa del worker (solo prefijo)"""
        from django.utils import timezone
        # Obtener la API key activa más reciente
        api_key = obj.api_keys.filter(is_active=True).order_by('-created_at').first()
        if api_key:
            # Retornar el formato completo AGR-WORKER-XXXX... para que el frontend lo vea
            return api_key.key_prefix + "..."
        return None

    def get_total_detections(self, obj):
        """Cuenta total de análisis realizados por este worker"""
        return obj.analysis_records.count()

    def get_total_detections_today(self, obj):
        from django.utils import timezone
        # Usa la hora LOCAL del servidor y filtra por el día real local.
        today = timezone.localtime(timezone.now()).date()
        return obj.analysis_records.filter(created_at__date=today).count()


    def get_last_detection(self, obj):
        """Fecha y hora del último análisis"""
        last_record = obj.analysis_records.order_by('-created_at').first()
        if last_record:
            return last_record.created_at.isoformat()
        return None


class WorkerCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para crear nuevos workers.
    Automáticamente genera password temporal, API key, y envía email con credenciales.
    """
    api_key = serializers.CharField(read_only=True)
    password_change_required = serializers.BooleanField(read_only=True)
    email_sent = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'first_name',
            'last_name',
            'email',
            'api_key',
            'is_active',
            'date_joined',
            'password_change_required',
            'email_sent',
        ]
        read_only_fields = ['id', 'date_joined', 'api_key', 'is_active', 'password_change_required', 'email_sent']
        extra_kwargs = {
            'email': {'required': True, 'allow_blank': False},
            'first_name': {'required': True, 'allow_blank': False},
        }

    def validate_email(self, value):
        """Valida que el email sea único"""
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Ya existe un usuario con este email.")
        return value
    
    def validate_username(self, value):
        """Valida que el username sea único"""
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Este nombre de usuario ya está en uso.")
        return value

    def create(self, validated_data):
        """
        Crea un worker con password temporal, API key, y envía email con credenciales.
        Asigna automáticamente la organization del admin que lo crea.
        """
        from .models import UserProfile, generate_temp_password
        from .email_utils import send_worker_credentials_email
        import logging
        
        logger = logging.getLogger(__name__)
        
        # Obtener el usuario autenticado (admin) del context
        request = self.context.get('request')
        admin_user = request.user if request else None
        
        # Generar password temporal
        temp_password = generate_temp_password()
        logger.info(f"🔄 Creando worker con email: {validated_data['email']}")
        
        # Crear usuario CON password temporal
        user = User.objects.create_user(
            username=validated_data.get('username', validated_data['email'].split('@')[0]),
            first_name=validated_data['first_name'],
            last_name=validated_data.get('last_name', ''),
            email=validated_data['email'],
            password=temp_password,  # Password temporal hasheado
            is_staff=False,  # Workers NO son staff
            is_active=True,
        )
        logger.info(f"✅ Usuario worker creado: {user.username} (ID: {user.id})")

        # Asignar organization, role=worker, y password_change_required al UserProfile
        if admin_user and hasattr(admin_user, 'profile'):
            user.profile.organization = admin_user.profile.organization
            user.profile.created_by = admin_user
            user.profile.role = 'worker'
            user.profile.password_change_required = True
            user.profile.save()
            org_name = user.profile.organization.name if user.profile.organization else 'Sin organización'
            logger.info(f"✅ UserProfile configurado: role=worker, org={org_name}")

        # Generar API key
        api_key_name = f"Worker-{user.username}"
        api_key_obj, plain_key = WorkerAPIKey.create_key(user=user, name=api_key_name)
        logger.info(f"✅ API Key generada: {plain_key[:20]}...")

        # Enviar email con credenciales
        logger.info(f"📧 Enviando email con credenciales a {user.email}")
        email_sent = send_worker_credentials_email(
            worker_email=user.email,
            first_name=user.first_name,
            temp_password=temp_password,  # Password en texto plano (solo para email)
            api_key=plain_key
        )
        
        if email_sent:
            logger.info(f"✅ Email enviado exitosamente a {user.email}")
        else:
            logger.error(f"❌ FALLO al enviar email a {user.email}")

        # Agregar atributos temporales para la respuesta
        user.api_key = plain_key
        user.password_change_required = True
        user.email_sent = email_sent

        return user

    def to_representation(self, instance):
        """
        Personaliza la representación para incluir la API key generada y otros campos.
        """
        representation = super().to_representation(instance)

        # API Key
        if hasattr(instance, 'api_key'):
            representation['api_key'] = instance.api_key
        else:
            # Para workers existentes, mostrar solo el prefijo
            api_key = instance.api_keys.filter(is_active=True).order_by('-created_at').first()
            if api_key:
                representation['api_key'] = api_key.key_prefix + "..."
            else:
                representation['api_key'] = None
        
        # Password change required
        if hasattr(instance, 'password_change_required'):
            representation['password_change_required'] = instance.password_change_required
        elif hasattr(instance, 'profile'):
            representation['password_change_required'] = instance.profile.password_change_required
        else:
            representation['password_change_required'] = False
        
        # Email sent
        if hasattr(instance, 'email_sent'):
            representation['email_sent'] = instance.email_sent
        else:
            representation['email_sent'] = None
        
        # Role
        if hasattr(instance, 'profile'):
            representation['role'] = instance.profile.role
        else:
            representation['role'] = 'worker'

        return representation


class WorkerListSerializer(serializers.ModelSerializer):
    """
    Serializer optimizado para listados de workers.
    Incluye estadísticas básicas.
    """
    api_key = serializers.SerializerMethodField()
    total_detections = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'first_name',
            'last_name',
            'is_active',
            'api_key',
            'total_detections',
        ]

    def get_api_key(self, obj):
        """Obtiene el prefijo de la API key activa"""
        api_key = obj.api_keys.filter(is_active=True).order_by('-created_at').first()
        if api_key:
            return api_key.key_prefix + "..."
        return None

    def get_total_detections(self, obj):
        """Cuenta total de análisis"""
        return obj.analysis_records.count()


# ========== ADMIN REQUEST SERIALIZER ==========

class AdminRequestSerializer(serializers.ModelSerializer):
    """
    Serializer para solicitudes de administradores.
    Solo permite creación (POST), no edición.
    """
    
    class Meta:
        model = AdminRequest
        fields = [
            'id',
            'first_name',
            'last_name',
            'email',
            'phone',
            'organization_name',
            'country',
            'region',
            'status',
            'created_at',
        ]
        read_only_fields = ['id', 'status', 'created_at']
    
    def validate_email(self, value):
        """Valida que el email no exista ni en AdminRequest ni en User"""
        email = value.lower().strip()
        
        # Verificar si ya existe una solicitud pendiente
        if AdminRequest.objects.filter(email=email, status='pending').exists():
            raise serializers.ValidationError(
                "Ya existe una solicitud pendiente con este email."
            )
        
        # Verificar si ya existe un usuario con este email
        if User.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                "Ya existe una cuenta con este email. Usa 'Recuperar Contraseña' si olvidaste tus credenciales."
            )
        
        return email
    
    def validate_phone(self, value):
        """Limpia y valida el teléfono"""
        if value:
            # Remover espacios y guiones
            value = value.replace(' ', '').replace('-', '')
        return value
    
    def validate(self, data):
        """Validaciones adicionales"""
        # Validar longitud de nombres
        if len(data.get('first_name', '')) < 2:
            raise serializers.ValidationError({
                'first_name': 'El nombre debe tener al menos 2 caracteres.'
            })
        
        if len(data.get('last_name', '')) < 2:
            raise serializers.ValidationError({
                'last_name': 'El apellido debe tener al menos 2 caracteres.'
            })
        
        if len(data.get('organization_name', '')) < 3:
            raise serializers.ValidationError({
                'organization_name': 'El nombre de la organización debe tener al menos 3 caracteres.'
            })
        
        return data
    
    