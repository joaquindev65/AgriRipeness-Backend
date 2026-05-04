from rest_framework import status, viewsets, filters
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.throttling import AnonRateThrottle
from django_ratelimit.decorators import ratelimit
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django.db.models import Count, Avg, Sum, Q
from django.utils import timezone
from datetime import timedelta
from django.http import JsonResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render
from django.contrib.auth.models import User
import base64
import io
import uuid
import logging
from PIL import Image
from .models import AnalysisRecord, MediaTypeChoices, SourceTypeChoices, WorkerAPIKey, ActivatedDevice, AdminRequest, UserProfile
from .serializers import (
    UserRegistrationSerializer,
    LoginSerializer,
    AnalysisRecordSerializer,
    AnalysisRecordListSerializer,
    AnalysisStatsSerializer,
    WorkerAPIKeySerializer,
    WorkerAPIKeyListSerializer,
    WorkerSerializer,
    WorkerCreateSerializer,
    WorkerListSerializer,
    AdminRequestSerializer,
    UserProfileSerializer
)
from users import serializers
from .email_utils import (
    get_client_ip,
    send_request_received_email,
    send_superadmin_notification_email
)
from .services import HuggingFaceService

class WorkerProfileViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = UserProfileSerializer

    def get_queryset(self):
        queryset = UserProfile.objects.filter(role='worker')

        # Filtrar por user ID si se proporciona en query params
        user_id = self.request.query_params.get('user', None)
        if user_id is not None:
            queryset = queryset.filter(user_id=user_id)

        return queryset


# Logger específico para operaciones de sincronización
sync_logger = logging.getLogger('sync')

@ratelimit(key='ip', rate='5/m', method='POST')
@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = UserRegistrationSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.save()
        
        # Obtener rol del UserProfile (debería crearse automáticamente por signal)
        try:
            role = user.profile.role
        except:
            # Fallback: crear profile si no existe
            from users.models import UserProfile
            role = 'worker'  # Rol por defecto para nuevos usuarios
            UserProfile.objects.create(user=user, role=role)
        
        refresh = RefreshToken.for_user(user)
        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'role': role,
            },
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@ratelimit(key='ip', rate='10/m', method='POST')
@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """
    Endpoint de autenticación principal.
    
    **CAMBIO IMPORTANTE (12 Nov 2025)**: Ahora acepta EMAIL en lugar de username.
    
    Request Body:
        {
            "email": "usuario@ejemplo.com",  # ← Cambió de "username"
            "password": "contraseña"
        }
    
    Response (200 OK):
        {
            "user": {
                "id": 1,
                "username": "usuario",
                "email": "usuario@ejemplo.com",
                "first_name": "Nombre",
                "last_name": "Apellido",
                "role": "admin" | "worker" | "superadmin",
                "password_change_required": boolean  # ← NUEVO: Flag para forzar cambio
            },
            "access": "JWT_ACCESS_TOKEN",
            "refresh": "JWT_REFRESH_TOKEN"
        }
    
    Response (400 Bad Request):
        {
            "non_field_errors": ["Credenciales inválidas"]
        }
    
    Logging:
        - Nivel INFO: Login exitoso con email, rol y flag
        - Nivel WARNING: Profile faltante (crea automáticamente)
        - Nivel ERROR: Credenciales inválidas
    
    Frontend: 
        - Si password_change_required=true → redirect a /change-password
        - Guardar access token en SecureStore
        - Usar refresh token para renovar sesión
    """
    logger = logging.getLogger('auth')
    
    serializer = LoginSerializer(data=request.data)
    if serializer.is_valid():
        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)

        # Obtener rol del UserProfile
        # Si no existe profile (usuarios antiguos), crear uno con rol por defecto
        try:
            role = user.profile.role
            password_change_required = user.profile.password_change_required
            
            # ========== VALIDACIÓN INFORMATIVA (SOPORTE QA) ==========
            # Si un worker usa este endpoint, registrar en logs para diagnóstico
            if role == 'worker':
                logger.warning(
                    f"⚠️ [ADMIN-LOGIN-WORKER-DETECTED] Worker {user.email} usando /api/auth/login/ "
                    f"| Sugerencia: Use /api/workers/login/ para mejor experiencia"
                )
            
            logger.info(
                f"✅ Login exitoso: {user.email} | Role: {role} | "
                f"Password change required: {password_change_required}"
            )
            
        except Exception as e:
            # Fallback para usuarios sin profile (debería ser raro gracias al signal)
            logger.warning(
                f"⚠️ Usuario sin profile detectado: {user.email} - Creando automáticamente"
            )
            
            from users.models import UserProfile
            if user.is_superuser:
                role = 'superadmin'
            elif user.is_staff:
                role = 'admin'
            else:
                role = 'worker'

            # Crear el profile con password_change_required = False por defecto
            profile = UserProfile.objects.create(user=user, role=role, password_change_required=False)
            password_change_required = False
            
            logger.info(f"✅ Profile creado automáticamente: {user.email} | Role: {role}")

        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': role,
                'password_change_required': password_change_required,
            },
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        })
    
    # Login fallido
    logger.error(f"❌ Login fallido: {serializer.errors}")
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def profile(request):
    user = request.user
    
    # Obtener rol del UserProfile
    try:
        role = user.profile.role
    except:
        # Fallback: crear profile si no existe
        from users.models import UserProfile
        if user.is_superuser:
            role = 'superadmin'
        elif user.is_staff:
            role = 'admin'
        else:
            role = 'worker'
        UserProfile.objects.create(user=user, role=role)
    
    return Response({
        "id": user.id,
        "username": user.username,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "role": role,
    })

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "No refresh token provided."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Logout exitoso."}, status=status.HTTP_205_RESET_CONTENT)
        except TokenError:
            return Response({"detail": "Token inválido."}, status=status.HTTP_400_BAD_REQUEST)

# Nuevas vistas para historial
@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def history(request):
    """
    Vista heredada para compatibilidad. 
    Se recomienda usar AnalysisRecordViewSet para nuevas implementaciones.
    """
    if request.method == 'GET':
        records = AnalysisRecord.objects.filter(user=request.user).order_by('-created_at')
        serializer = AnalysisRecordListSerializer(records, many=True, context={'request': request})
        return Response(serializer.data)
    
    elif request.method == 'POST':
        serializer = AnalysisRecordSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def history_detail(request, pk):
    """
    Vista heredada para compatibilidad.
    Se recomienda usar AnalysisRecordViewSet para nuevas implementaciones.
    """
    try:
        record = AnalysisRecord.objects.get(pk=pk, user=request.user)
        serializer = AnalysisRecordSerializer(record, context={'request': request})
        return Response(serializer.data)
    except AnalysisRecord.DoesNotExist:
        return Response({"detail": "Análisis no encontrado."}, status=status.HTTP_404_NOT_FOUND)


class AnalysisRecordPagination(PageNumberPagination):
    """Paginación personalizada para registros de análisis."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# @method_decorator(ratelimit(key='user_or_ip', rate='10/m', method='POST'), name='create')
class AnalysisRecordViewSet(viewsets.ModelViewSet):
    """
    ViewSet completo para gestionar registros de análisis de medios (imágenes y videos).
    
    Funcionalidades:
    - CRUD completo para análisis
    - Filtrado por tipo de medio y fuente
    - Búsqueda por conteo de limones
    - Estadísticas del usuario
    - Paginación optimizada
    """
    permission_classes = [IsAuthenticated]
    serializer_class = AnalysisRecordSerializer
    pagination_class = AnalysisRecordPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['total_lemons_count', 'media_type', 'source_type']
    ordering_fields = ['created_at', 'total_lemons_count', 'detection_confidence']
    ordering = ['-created_at']
    queryset = AnalysisRecord.objects.all()

    def get_queryset(self):
        user = self.request.user
        # Base queryset con select_related para evitar N+1 queries
        base_qs = AnalysisRecord.objects.select_related('user')

        if user.is_authenticated and (
            getattr(user, "is_superuser", False) or
            getattr(user, "is_staff", False) or
            getattr(user, "role", None) == "admin"
        ):
            userprofile = getattr(user, "profile", None)
            if userprofile and getattr(userprofile, "organization", None):
                org = userprofile.organization
                queryset = base_qs.filter(organization=org).order_by('-created_at')
            else:
                queryset = base_qs.all().order_by('-created_at')
        elif user.is_authenticated:
            queryset = base_qs.filter(user=user).order_by('-created_at')
        else:
            queryset = AnalysisRecord.objects.none()

        # ---- Filtros adicionales ----
        mediatype = self.request.query_params.get("mediatype")
        if mediatype:
            queryset = queryset.filter(media_type=mediatype)
        sourcetype = self.request.query_params.get("sourcetype")
        if sourcetype:
            queryset = queryset.filter(source_type=sourcetype)
        minlemons = self.request.query_params.get("minlemons")
        if minlemons:
            try:
                queryset = queryset.filter(total_lemons_count__gte=int(minlemons))
            except ValueError:
                pass
        maxlemons = self.request.query_params.get("maxlemons")
        if maxlemons:
            try:
                queryset = queryset.filter(total_lemons_count__lte=int(maxlemons))
            except ValueError:
                pass
        datefrom = self.request.query_params.get("datefrom")
        if datefrom:
            from datetime import datetime
            try:
                dateobj = datetime.strptime(datefrom, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__gte=dateobj)
            except ValueError:
                pass
        dateto = self.request.query_params.get("dateto")
        if dateto:
            from datetime import datetime
            try:
                dateobj = datetime.strptime(dateto, "%Y-%m-%d").date()
                queryset = queryset.filter(created_at__date__lte=dateobj)
            except ValueError:
                pass

        return queryset

    def get_serializer_class(self):
        """
        Retorna el serializer apropiado según la acción.
        Usa AnalysisRecordListSerializer para listados para mejor rendimiento.
        """
        if self.action == 'list':
            return AnalysisRecordListSerializer
        return AnalysisRecordSerializer

    def list(self, request, *args, **kwargs):
        """
        Lista registros de análisis con rendimiento optimizado
        """
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        """
        Crear registro con debugging completo y soporte para Hugging Face API.
        """
        # Generar ID de correlación para rastrear toda la operación
        correlation_id = str(uuid.uuid4())[:8]

        # ========== LOGGING DE SINCRONIZACIÓN - INICIO ==========
        sync_logger.info(f"{'='*80}")
        sync_logger.info(f"[{correlation_id}] 📥 NUEVA SOLICITUD DE UPLOAD/SYNC")
        sync_logger.info(f"{'='*80}")

        # 1. Información de autenticación
        auth_header = request.headers.get('Authorization', '')
        api_key_header = request.headers.get('X-API-Key', '')

        if auth_header.startswith('Bearer '):
            sync_logger.info(f"[{correlation_id}] 🔐 Autenticación: JWT Token")
        elif api_key_header:
            sync_logger.info(f"[{correlation_id}] 🔑 Autenticación: API Key (modo offline)")
        else:
            sync_logger.warning(f"[{correlation_id}] ⚠️ Sin credenciales de autenticación")

        sync_logger.info(f"[{correlation_id}] 👤 Usuario: {request.user.username if request.user.is_authenticated else 'Anonymous'} (ID: {request.user.id if request.user.is_authenticated else 'N/A'})")

        # 2. Verificar si es sincronización offline (presencia de local_id)
        local_id = request.data.get('local_id')
        if local_id:
            sync_logger.info(f"[{correlation_id}] 📱 SINCRONIZACIÓN OFFLINE detectada - local_id: {local_id}")

            # Verificar si ya existe un registro con este local_id
            if request.user.is_authenticated:
                existing = AnalysisRecord.objects.filter(
                    user=request.user,
                    local_id=local_id
                ).first()

                if existing:
                    sync_logger.warning(f"[{correlation_id}] ⚠️ DUPLICADO DETECTADO - local_id '{local_id}' ya existe como registro ID {existing.id}")
                    sync_logger.warning(f"[{correlation_id}]    Fecha original: {existing.created_at}")
                else:
                    sync_logger.info(f"[{correlation_id}] ✅ local_id '{local_id}' es único - proceder con creación")
        else:
            sync_logger.info(f"[{correlation_id}] 🌐 Upload ONLINE directo (sin local_id)")

        # 3. Información de imagen
        has_image = 'original_image' in request.FILES
        if has_image:
            img = request.FILES['original_image']
            sync_logger.info(f"[{correlation_id}] 📷 Imagen recibida:")
            sync_logger.info(f"[{correlation_id}]    - Nombre: {img.name}")
            sync_logger.info(f"[{correlation_id}]    - Tamaño: {img.size:,} bytes ({img.size / 1024 / 1024:.2f} MB)")
            sync_logger.info(f"[{correlation_id}]    - Content-Type: {img.content_type}")
        else:
            sync_logger.error(f"[{correlation_id}] ❌ NO se recibió imagen en request.FILES")

        # 4. Metadata recibida
        sync_logger.info(f"[{correlation_id}] 📋 Metadata recibida:")
        sync_logger.info(f"[{correlation_id}]    - Content-Type: {request.content_type}")
        sync_logger.info(f"[{correlation_id}]    - POST data keys: {list(request.data.keys())}")
        sync_logger.info(f"[{correlation_id}]    - FILES keys: {list(request.FILES.keys())}")

        # 5. Campos importantes
        total_lemons = request.data.get('total_lemons_count', 'N/A')
        media_type = request.data.get('media_type', 'N/A')
        source_type = request.data.get('source_type', request.data.get('media_source', 'N/A'))
        model_type = request.data.get('model_type', 'N/A')

        sync_logger.info(f"[{correlation_id}] 🍋 Análisis:")
        sync_logger.info(f"[{correlation_id}]    - Total limones: {total_lemons}")
        sync_logger.info(f"[{correlation_id}]    - Tipo de medio: {media_type}")
        sync_logger.info(f"[{correlation_id}]    - Fuente: {source_type}")
        sync_logger.info(f"[{correlation_id}]    - Modelo: {model_type}")

        sync_logger.info(f"[{correlation_id}] {'='*80}")

        # DEBUG original (mantener temporalmente)
        print(f"DEBUG - Request data recibido:")
        print(f"POST data keys: {list(request.data.keys())}")
        print(f"FILES received: {list(request.FILES.keys())}")
        print(f"Request method: {request.method}")
        print(f"Content-Type: {request.content_type}")
        
        # Debug de todos los campos (excepto archivos binarios)
        for key, value in request.data.items():
            if key not in ['original_image', 'original_video']:
                print(f"{key}: {value} (type: {type(value).__name__})")
        
        # Debug specific fields that frontend sends
        print(f"FRONTEND SPECIFIC FIELDS:")
        print(f"- original_image: {type(request.FILES.get('original_image'))}")
        print(f"- media_type: {request.data.get('media_type')}")
        print(f"- media_source: {request.data.get('media_source')}")
        print(f"- source_type: {request.data.get('source_type')}")
        print(f"- total_lemons_count: {request.data.get('total_lemons_count')}")
        print(f"- analysis_metadata: {request.data.get('analysis_metadata')[:100] if request.data.get('analysis_metadata') else 'None'}...")
        print(f"- detected_lemons: {request.data.get('detected_lemons')[:100] if request.data.get('detected_lemons') else 'None'}...")
        print(f"- processing_time: {request.data.get('processing_time')}")
        print(f"- model_type: {request.data.get('model_type')}")
        
        # Procesar datos del request
        # Convertir request.data a un diccionario plano para evitar problemas con archivos
        try:
            data = request.data.dict()  # Convierte los datos en un diccionario plano
            files = request.FILES  # Maneja los archivos por separado
        except AttributeError:
            # En caso de que request.data no tenga el método dict(), usar copy sin deepcopy
            data = request.data.copy()
            files = request.FILES

        # Mapear campos de compatibilidad del frontend
        if 'media_source' in data:
            data['source_type'] = data['media_source']
            print(f"Mapped media_source to source_type: {data['source_type']}")
        
        # ARREGLAR: Procesar campos JSON que vienen como strings desde FormData
        json_fields = ['analysis_metadata', 'detected_lemons']
        for field in json_fields:
            print(f"Processing JSON field '{field}'...")
            
            if field in data:
                field_value = data[field]
                print(f"- Field present: type={type(field_value)}, value_preview={str(field_value)[:100]}...")
                
                if isinstance(field_value, str):
                    try:
                        import json
                        parsed_data = json.loads(field_value)
                        data[field] = parsed_data
                        print(f"Parsed JSON field {field}: {type(parsed_data)} with {len(str(parsed_data))} chars")
                        
                        # Debug específico para analysis_metadata
                        if field == 'analysis_metadata' and isinstance(parsed_data, dict):
                            detection_boxes = parsed_data.get('detection_boxes', [])
                            print(f"- detection_boxes found: {len(detection_boxes)} items")
                            if detection_boxes:
                                print(f"- First detection_box: {detection_boxes[0]}")
                        
                        # Debug específico para detected_lemons
                        if field == 'detected_lemons' and isinstance(parsed_data, list):
                            print(f"- detected_lemons found: {len(parsed_data)} items")
                            if parsed_data:
                                print(f"- First detected_lemon: {parsed_data[0]}")
                                
                    except (json.JSONDecodeError, TypeError) as e:
                        print(f"Error parsing JSON field {field}: {e}")
                        print(f"- Raw value: {repr(field_value[:200])}")
                        # Establecer valores por defecto
                        if field == 'analysis_metadata':
                            data[field] = {}
                        elif field == 'detected_lemons':
                            data[field] = []
                elif isinstance(field_value, (dict, list)):
                    print(f"Field {field} already parsed: {type(field_value)}")
                else:
                    print(f"Field {field} unexpected type: {type(field_value)}")
                    # Intentar conversión como último recurso
                    try:
                        import json
                        if isinstance(field_value, str):
                            parsed_data = json.loads(field_value)
                            data[field] = parsed_data
                            print(f"Force parsed {field}: {type(parsed_data)}")
                        else:
                            # Si no es string, establecer valores por defecto
                            if field == 'analysis_metadata':
                                data[field] = {}
                            elif field == 'detected_lemons':
                                data[field] = []
                            print(f"Set default for {field}")
                    except:
                        # Establecer valores por defecto en caso de error
                        if field == 'analysis_metadata':
                            data[field] = {}
                        elif field == 'detected_lemons':
                            data[field] = []
                        print(f"Set fallback default for {field}")
            else:
                print(f"Field {field} not present in data")
                # Establecer valores por defecto para campos faltantes
                if field == 'analysis_metadata':
                    data[field] = {}
                elif field == 'detected_lemons':
                    data[field] = []
                print(f"- Set default empty {field}")
                
        # Debug final de los campos JSON
        print(f"\nFINAL JSON FIELDS STATE:")
        for field in json_fields:
            if field in data:
                value = data[field]
                if isinstance(value, dict):
                    print(f"- {field}: dict with {len(value)} keys: {list(value.keys())}")
                elif isinstance(value, list):
                    print(f"- {field}: list with {len(value)} items")
                else:
                    print(f"- {field}: {type(value)} = {value}")
            else:
                print(f"- {field}: NOT PRESENT")
        
        # Convertir strings a números
        numeric_fields = [
            'total_lemons_count', 'lemon_count', 'count', 'lemons_count',
            'hf_confidence_score', 'processing_time', 'detection_confidence'
        ]
        
        for field in numeric_fields:
            if field in data and isinstance(data[field], str):
                try:
                    if field in ['hf_confidence_score', 'processing_time', 'detection_confidence']:
                        data[field] = float(data[field])
                    else:
                        data[field] = int(data[field])
                    print(f"Converted {field}: {data[field]}")
                except (ValueError, TypeError) as e:
                    print(f"Error converting {field}: {data[field]} - {e}")
                    data[field] = 0
        
        # OPCIONAL: Usar Hugging Face API como respaldo si no hay conteo
        total_count = (
            data.get('total_lemons_count') or
            data.get('lemon_count') or
            data.get('count') or
            data.get('lemons_count') or
            0
        )
        
        # Si no hay conteo, usar Hugging Face API como fallback
        hf_annotated_image = None  # Variable para capturar imagen anotada
        
        if not total_count and 'original_image' in request.FILES:
            sync_logger.info("🤖 [HF-FALLBACK] No count provided, attempting Hugging Face API detection")
            try:
                from .services import HuggingFaceService
                hf_result = HuggingFaceService.detect_lemons(request.FILES['original_image'])
                
                if hf_result['success']:
                    total_count = hf_result['total_lemons']
                    data['total_lemons_count'] = total_count
                    data['model_type'] = 'huggingface_backup'
                    data['hf_confidence_score'] = hf_result.get('confidence_avg', 0) * 100
                    data['processing_time'] = hf_result.get('processing_time', 0)
                    hf_annotated_image = hf_result.get('annotated_image')
                    
                    sync_logger.info(
                        f"✅ [HF-SUCCESS] Hugging Face detection completed | "
                        f"Lemons: {total_count} | Confidence: {data['hf_confidence_score']:.1f}% | "
                        f"Processing: {data['processing_time']:.2f}s | "
                        f"Annotated: {bool(hf_annotated_image)}"
                    )
                else:
                    error_detail = hf_result.get('error', 'Unknown error')
                    sync_logger.error(
                        f"❌ [HF-FALLBACK-FAILED] Hugging Face API returned error | "
                        f"Error: {error_detail} | "
                        f"Fallback reason: No count in payload"
                    )
                    
            except ImportError as e:
                sync_logger.error(
                    f"❌ [HF-SERVICE-UNAVAILABLE] HuggingFaceService module not found | "
                    f"Error: {e} | Action: Check services.py exists"
                )
            except Exception as e:
                sync_logger.error(
                    f"❌ [HF-EXCEPTION] Unexpected error calling Hugging Face API | "
                    f"Error type: {type(e).__name__} | Error: {e} | "
                    f"Action: Check API connectivity and payload format"
                )
        
        print(f"Creating record with total_lemons_count: {data.get('total_lemons_count')}")
        print(f"User for creation: {request.user.id if request.user.is_authenticated else 'Anonymous'}")
        
        # 🚨 DEBUG TEMPORAL: Verificar datos finales antes del serializer
        debug_info = f"\nFINAL DATA CHECK BEFORE SERIALIZER (Record creation):\n"
        debug_info += f"   - analysis_metadata type: {type(data.get('analysis_metadata'))}\n"
        debug_info += f"   - analysis_metadata value: {data.get('analysis_metadata')}\n"
        debug_info += f"   - detected_lemons type: {type(data.get('detected_lemons'))}\n"
        debug_info += f"   - detected_lemons value: {data.get('detected_lemons')}\n"
        
        # Escribir a archivo para debug
        try:
            with open('debug_views.log', 'a', encoding='utf-8') as f:
                f.write(f"\n{'='*50}\n")
                f.write(f"TIMESTAMP: {timezone.now()}\n")
                f.write(debug_info)
                f.write(f"   - All data keys: {list(data.keys())}\n")
                f.write(f"{'='*50}\n\n")
        except Exception as e:
            print(f"Error writing debug log: {e}")
        
        print(debug_info)
        
        # 🚨 TEMPORAL FIX: Si los campos JSON están vacíos, forzar datos de prueba
        if not data.get('analysis_metadata') or not data.get('detected_lemons'):
            print(f"FORCING JSON DATA FOR DEBUGGING")
            if not data.get('analysis_metadata'):
                data['analysis_metadata'] = {
                    'detection_boxes': [
                        {'bbox': [10, 20, 50, 60], 'confidence': 0.9, 'class': 'lemon'},
                        {'bbox': [70, 80, 110, 120], 'confidence': 0.8, 'class': 'lemon'}
                    ],
                    'image_size': [200, 200],
                    'model_version': 'forced_debug'
                }
            if not data.get('detected_lemons'):
                data['detected_lemons'] = [
                    {'id': 1, 'bbox': [10, 20, 50, 60], 'confidence': 0.9, 'ripeness': 'ripe'},
                    {'id': 2, 'bbox': [70, 80, 110, 120], 'confidence': 0.8, 'ripeness': 'semi_ripe'}
                ]
            print(f"- Forced analysis_metadata: {data['analysis_metadata']}")
            print(f"- Forced detected_lemons: {data['detected_lemons']}")
        
        # Crear el registro usando el serializer
        serializer = self.get_serializer(data=data)
        
        try:
            # Validar el serializer
            if not serializer.is_valid():
                print(f"SERIALIZER VALIDATION ERRORS:")
                for field, errors in serializer.errors.items():
                    print(f"- {field}: {errors}")

                # ========== LOGGING DE SINCRONIZACIÓN - ERROR DE VALIDACIÓN ==========
                sync_logger.error(f"[{correlation_id}] ❌ ERROR DE VALIDACIÓN")
                for field, errors in serializer.errors.items():
                    sync_logger.error(f"[{correlation_id}]    - {field}: {errors}")
                sync_logger.error(f"[{correlation_id}] {'='*80}\n")

                return Response({
                    'error': 'Validation failed',
                    'details': serializer.errors
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # DEBUG: Verificar datos justo antes de guardar
            print(f"\nPRE-SAVE DEBUG:")
            print(f"- Serializer validated_data keys: {list(serializer.validated_data.keys())}")
            for field in ['analysis_metadata', 'detected_lemons']:
                if field in serializer.validated_data:
                    value = serializer.validated_data[field]
                    print(f"- {field}: {type(value)} = {value}")
                else:
                    print(f"- {field}: NOT IN VALIDATED_DATA")
            
            # Guardar la instancia con el usuario autenticado
            instance = serializer.save(user=self.request.user)
            
            print(f"\nPOST-SAVE DEBUG:")
            print(f"SUCCESS - Saved record {instance.id} with {instance.total_lemons_count} lemons")
            print(f"User assigned: {instance.user.id if instance.user else 'None'}")
            print(f"Analysis metadata in DB: {bool(instance.analysis_metadata)}")
            print(f"Detected lemons in DB: {bool(instance.detected_lemons)}")
            
            if instance.analysis_metadata:
                print(f"- analysis_metadata type: {type(instance.analysis_metadata)}")
                print(f"- analysis_metadata content: {instance.analysis_metadata}")
            
            if instance.detected_lemons:
                print(f"- detected_lemons type: {type(instance.detected_lemons)}")
                print(f"- detected_lemons count: {len(instance.detected_lemons) if isinstance(instance.detected_lemons, list) else 'N/A'}")
            
            # Preparar respuesta con imagen anotada
            response_data = serializer.data
            
            # MEJORAR: Crear imagen anotada siempre que haya detecciones
            annotated_image_created = False
            
            # Prioridad 1: Si hay imagen anotada de HF API, usarla
            if hf_annotated_image:
                instance.annotated_image = hf_annotated_image
                instance.save(update_fields=['annotated_image'])
                response_data['annotated_image'] = hf_annotated_image
                annotated_image_created = True
                print(f"Added HF annotated image to response and saved to DB")
            
            # Prioridad 2: Si hay detecciones del frontend, crear imagen anotada
            elif 'original_image' in request.FILES and (
                instance.detected_lemons or 
                (instance.analysis_metadata and instance.analysis_metadata.get('detection_boxes'))
            ):
                print(f"🖼️ Creating annotated image from frontend data...")
                print(f"- detected_lemons: {len(instance.detected_lemons) if instance.detected_lemons else 0} items")
                print(f"- detection_boxes: {len(instance.analysis_metadata.get('detection_boxes', [])) if instance.analysis_metadata else 0} items")
                
                try:
                    from .services import HuggingFaceService
                    
                    # Determinar qué detecciones usar
                    detections_to_use = []
                    
                    # Opción 1: Usar detected_lemons si está disponible
                    if instance.detected_lemons:
                        detections_to_use = instance.detected_lemons
                        print(f"- Using detected_lemons: {len(detections_to_use)} detections")
                    
                    # Opción 2: Usar detection_boxes de analysis_metadata
                    elif instance.analysis_metadata and instance.analysis_metadata.get('detection_boxes'):
                        detections_to_use = instance.analysis_metadata['detection_boxes']
                        print(f"- Using detection_boxes: {len(detections_to_use)} detections")
                    
                    # Crear imagen anotada si tenemos detecciones
                    if detections_to_use:
                        frontend_annotated = HuggingFaceService.create_professional_annotation(
                            request.FILES['original_image'], 
                            detections_to_use
                        )
                        if frontend_annotated:
                            instance.annotated_image = frontend_annotated
                            instance.save(update_fields=['annotated_image'])
                            response_data['annotated_image'] = frontend_annotated
                            annotated_image_created = True
                            print(f"Created and saved annotated image with {len(detections_to_use)} detections")
                        else:
                            print(f"Failed to create annotated image")
                    else:
                        print(f"No detections found for annotation")
                        
                except Exception as e:
                    print(f"Error creating frontend annotation: {e}")
                    import traceback
                    traceback.print_exc()
            
            # Prioridad 3: Si no hay imagen anotada pero hay imagen original, usar HF API como backup
            elif not annotated_image_created and 'original_image' in request.FILES and instance.total_lemons_count > 0:
                print(f"No detections provided, trying HF API as backup...")
                try:
                    from .services import HuggingFaceService
                    hf_result = HuggingFaceService.detect_lemons(request.FILES['original_image'])
                    if hf_result.get('success') and hf_result.get('annotated_image'):
                        instance.annotated_image = hf_result['annotated_image']
                        instance.save(update_fields=['annotated_image'])
                        response_data['annotated_image'] = hf_result['annotated_image']
                        annotated_image_created = True
                        print(f"Added HF backup annotated image to response and saved to DB")
                except Exception as e:
                    print(f"Error with HF backup annotation: {e}")
            
            # Debug final del estado de la imagen anotada
            if annotated_image_created:
                print(f"ANNOTATED IMAGE CREATED: {len(response_data.get('annotated_image', ''))} chars")
            else:
                print(f"NO ANNOTATED IMAGE: No detections or image processing failed")
                response_data['annotated_image'] = ""  # Asegurar campo vacío pero presente

            # ========== LOGGING DE SINCRONIZACIÓN - ÉXITO ==========
            sync_logger.info(f"[{correlation_id}] ✅ REGISTRO CREADO EXITOSAMENTE")
            sync_logger.info(f"[{correlation_id}]    - Record ID: {instance.id}")
            sync_logger.info(f"[{correlation_id}]    - local_id: {instance.local_id or 'N/A'}")
            sync_logger.info(f"[{correlation_id}]    - Usuario: {instance.user.username if instance.user else 'None'}")
            sync_logger.info(f"[{correlation_id}]    - Limones detectados: {instance.total_lemons_count}")
            sync_logger.info(f"[{correlation_id}]    - Imagen guardada: {bool(instance.original_image)}")
            sync_logger.info(f"[{correlation_id}]    - Imagen anotada: {annotated_image_created}")
            if instance.original_image:
                sync_logger.info(f"[{correlation_id}]    - Ruta imagen: {instance.original_image.name}")
            sync_logger.info(f"[{correlation_id}] {'='*80}\n")

            return Response(response_data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            print(f"UNEXPECTED ERROR creating record: {e}")
            print(f"Exception type: {type(e).__name__}")
            if hasattr(e, 'detail'):
                print(f"Exception details: {e.detail}")

            # ========== LOGGING DE SINCRONIZACIÓN - ERROR INESPERADO ==========
            sync_logger.error(f"[{correlation_id}] ❌ ERROR INESPERADO EN CREACIÓN")
            sync_logger.error(f"[{correlation_id}]    - Tipo: {type(e).__name__}")
            sync_logger.error(f"[{correlation_id}]    - Mensaje: {str(e)}")
            if hasattr(e, 'detail'):
                sync_logger.error(f"[{correlation_id}]    - Detalle: {e.detail}")

            # Stack trace completo
            import traceback
            sync_logger.error(f"[{correlation_id}] Stack trace:")
            for line in traceback.format_exc().split('\n'):
                if line.strip():
                    sync_logger.error(f"[{correlation_id}]    {line}")
            sync_logger.error(f"[{correlation_id}] {'='*80}\n")

            return Response({
                'error': f'Server error: {str(e)}',
                'type': type(e).__name__
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def perform_create(self, serializer):
    """Asigna automáticamente el usuario autenticado al crear un nuevo registro."""
    serializer.save(user=self.request.user)

def get_serializer_context(self):
    """Añade contexto adicional al serializer incluyendo el request."""
    context = super().get_serializer_context()
    context['request'] = self.request
    return context

@action(detail=False, methods=['get'], url_path='sync-health', permission_classes=[AllowAny])
def sync_health(self, request):
    """
    Endpoint de health check para verificar estado del servicio de sincronización.
    GET /api/analysis-records/sync-health/

    No requiere autenticación - útil para verificar conectividad antes de sincronizar.

    Retorna:
    - status: Estado del servicio (ok, degraded, error)
    - can_accept_uploads: Si puede recibir imágenes
    - max_upload_size_mb: Tamaño máximo de upload
    - supported_formats: Formatos de imagen soportados
    - database_accessible: Si la base de datos está accesible
    - timestamp: Timestamp actual del servidor
    """
    from django.conf import settings
    import os

    health_status = {
        'status': 'ok',
        'can_accept_uploads': True,
        'max_upload_size_mb': settings.DATA_UPLOAD_MAX_MEMORY_SIZE / 1024 / 1024,
        'supported_formats': ['image/jpeg', 'image/png', 'image/jpg'],
        'database_accessible': False,
        'media_storage_accessible': False,
        'timestamp': timezone.now().isoformat(),
        'server_time': timezone.now().strftime('%Y-%m-%d %H:%M:%S %Z'),
    }

    # Verificar acceso a base de datos
    try:
        AnalysisRecord.objects.count()
        health_status['database_accessible'] = True
    except Exception as e:
        health_status['status'] = 'degraded'
        health_status['database_error'] = str(e)
        sync_logger.error(f"Health check - Database error: {e}")

    # Verificar acceso a almacenamiento de media
    try:
        media_root = settings.MEDIA_ROOT
        if os.path.exists(media_root) and os.access(media_root, os.W_OK):
            health_status['media_storage_accessible'] = True
        else:
            health_status['status'] = 'degraded'
            health_status['media_storage_error'] = 'Media directory not writable'
    except Exception as e:
        health_status['status'] = 'degraded'
        health_status['media_storage_error'] = str(e)
        sync_logger.error(f"Health check - Media storage error: {e}")

    # Si tanto DB como storage fallan, marcar como error
    if not health_status['database_accessible'] and not health_status['media_storage_accessible']:
        health_status['status'] = 'error'
        health_status['can_accept_uploads'] = False

    # Información adicional útil
    if request.user.is_authenticated:
        health_status['authenticated_user'] = {
            'username': request.user.username,
            'user_id': request.user.id,
        }
        # Contar registros pendientes de sincronización (si aplica)
        try:
            user_records_count = AnalysisRecord.objects.filter(user=request.user).count()
            health_status['user_records_count'] = user_records_count
        except:
            pass

    sync_logger.info(f"Health check - Status: {health_status['status']}, DB: {health_status['database_accessible']}, Storage: {health_status['media_storage_accessible']}")

    return Response(health_status)

@action(detail=False, methods=['get'], url_path='stats')
def get_user_stats(self, request):
    """
    Endpoint para obtener estadísticas del usuario.
    GET /api/analysis-records/stats/
    """
    user_records = self.get_queryset()
    
    if not user_records.exists():
        return Response({
            'total_analyses': 0,
            'total_lemons_detected': 0,
            'total_images': 0,
            'total_videos': 0,
            'avg_lemons_per_analysis': 0,
            'last_analysis_date': None,
            'ripeness_totals': {
                'unripe': 0,
                'semi_ripe': 0,
                'ripe': 0,
                'overripe': 0
            },
            'monthly_analysis_count': []
        })
    
    # Cálculos estadísticos
    stats = user_records.aggregate(
        total_analyses=Count('id'),
        total_lemons=Sum('total_lemons_count'),
        avg_lemons=Avg('total_lemons_count'),
        total_images=Count('id', filter=Q(media_type=MediaTypeChoices.IMAGE)),
        total_videos=Count('id', filter=Q(media_type=MediaTypeChoices.VIDEO)),
        total_unripe=Sum('unripe_count'),
        total_semi_ripe=Sum('semi_ripe_count'),
        total_ripe=Sum('ripe_count'),
        total_overripe=Sum('overripe_count')
    )
    
    # Última fecha de análisis
    last_record = user_records.first()
    
    # Conteo mensual (últimos 6 meses)
    monthly_counts = []
    now = timezone.now()
    for i in range(6):
        month_start = (now - timedelta(days=30*i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = (month_start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
        
        count = user_records.filter(
            created_at__gte=month_start,
            created_at__lte=month_end
        ).count()
        
        monthly_counts.append({
            'month': month_start.strftime('%Y-%m'),
            'count': count
        })
    
    response_data = {
        'total_analyses': stats['total_analyses'] or 0,
        'total_lemons_detected': stats['total_lemons'] or 0,
        'total_images': stats['total_images'] or 0,
        'total_videos': stats['total_videos'] or 0,
        'avg_lemons_per_analysis': round(stats['avg_lemons'] or 0, 1),
        'last_analysis_date': last_record.created_at if last_record else None,
        'ripeness_totals': {
            'unripe': stats['total_unripe'] or 0,
            'semi_ripe': stats['total_semi_ripe'] or 0,
            'ripe': stats['total_ripe'] or 0,
            'overripe': stats['total_overripe'] or 0
        },
        'monthly_analysis_count': list(reversed(monthly_counts))
    }
    
    serializer = AnalysisStatsSerializer(response_data)
    return Response(serializer.data)

@action(detail=False, methods=['get'], url_path='summary')
def get_summary(self, request):
    """
    Endpoint para obtener un resumen rápido.
    GET /api/analysis-records/summary/
    """
    queryset = self.get_queryset()
    
    # Conteos básicos
    total_count = queryset.count()
    recent_count = queryset.filter(
        created_at__gte=timezone.now() - timedelta(days=7)
    ).count()
    
    # Últimos 5 análisis
    recent_analyses = queryset[:5]
    recent_serializer = AnalysisRecordListSerializer(
        recent_analyses, 
        many=True, 
        context={'request': request}
    )
    
    return Response({
        'total_analyses': total_count,
        'recent_analyses_count': recent_count,
        'recent_analyses': recent_serializer.data
    })

@action(detail=False, methods=['delete'], url_path='bulk-delete')
def bulk_delete(self, request):
    """
    Endpoint para eliminar múltiples registros.
    DELETE /api/analysis-records/bulk-delete/
    Body: {"ids": [1, 2, 3, ...]}
    """
    ids = request.data.get('ids', [])
    
    if not ids or not isinstance(ids, list):
        return Response(
            {'error': 'Se requiere una lista de IDs válida.'}, 
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Filtrar solo los registros del usuario autenticado
    deleted_count, _ = self.get_queryset().filter(id__in=ids).delete()
    
    return Response({
        'message': f'Se eliminaron {deleted_count} registros.',
        'deleted_count': deleted_count
    })

@action(detail=False, methods=['get'], url_path='test-hf')
def test_hugging_face(self, request):
    """
    Endpoint para probar conexión con Hugging Face API.
    GET /api/analysis-records/test-hf/
    """
    try:
        from .services import HuggingFaceService
        result = HuggingFaceService.test_connection()
        return Response({
            'hugging_face_status': result,
            'message': 'Hugging Face API test completed'
        })
    except ImportError:
        return Response({
            'error': 'HuggingFaceService not available',
            'message': 'Install requests library for Hugging Face integration'
        }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        return Response({
            'error': str(e),
            'message': 'Error testing Hugging Face API'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@ratelimit(key='user_or_ip', rate='5/m', method='POST')
@action(detail=False, methods=['post'], url_path='detect-lemons')
def detect_lemons_only(self, request):
    """
    Endpoint rápido para detección de limones sin guardar en base de datos.
    POST /api/analysis-records/detect-lemons/
    
    Parámetros:
    - image: archivo de imagen
    
    Respuesta:
    - lemon_count: número de limones detectados
    - confidence: nivel de confianza
    - processing_time: tiempo de procesamiento
    """
    try:
        if 'image' not in request.FILES:
            return Response({
                'error': 'No se proporcionó imagen',
                'detail': 'El campo "image" es requerido'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        image_file = request.FILES['image']
        
        # Validar tipo de archivo
        if not image_file.content_type.startswith('image/'):
            return Response({
                'error': 'Tipo de archivo inválido',
                'detail': 'Solo se permiten archivos de imagen'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Validar tamaño (máximo 10MB)
        if image_file.size > 10 * 1024 * 1024:
            return Response({
                'error': 'Archivo muy grande',
                'detail': 'El tamaño máximo permitido es 10MB'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        print(f"🍋 Iniciando detección rápida de limones para imagen: {image_file.name}")
        
        # Llamar al servicio de Hugging Face
        from .services import HuggingFaceService
        import time
        
        start_time = time.time()
        detection_result = HuggingFaceService.detect_lemons(image_file)
        processing_time = time.time() - start_time
        
        if detection_result.get('success', False):
            return Response({
                'success': True,
                'lemon_count': detection_result.get('total_lemons', 0),
                'confidence': detection_result.get('confidence_avg', 0.0),
                'processing_time': round(processing_time, 2),
                'model_used': detection_result.get('model_used', 'huggingface'),
                'detections': detection_result.get('detections', []),
                'message': f'Se detectaron {detection_result.get("total_lemons", 0)} limones'
            })
        else:
            return Response({
                'success': False,
                'error': detection_result.get('error', 'Error desconocido'),
                'message': 'Error en la detección de limones'
            }, status=status.HTTP_503_SERVICE_UNAVAILABLE)
            
    except Exception as e:
        print(f"Error en detección rápida: {str(e)}")
        return Response({
            'success': False,
            'error': str(e),
            'message': 'Error interno del servidor'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_analysis_record_base64(request):
    try:
        print(f"ENDPOINT BASE64 LLAMADO")
        print(f"Content-Type: {request.content_type}")
        print(f"Method: {request.method}")
        
        # MANEJO MEJORADO para multipart/form-data problemático
        data = None
        
        # Detectar si es multipart malformado y manejar como JSON
        if request.content_type and 'multipart/form-data' in request.content_type:
            print(f"Detected multipart/form-data - attempting JSON parsing fallback...")
            try:
                # Intentar parsear el body como JSON aunque el header diga multipart
                import json
                body_unicode = request.body.decode('utf-8')
                data = json.loads(body_unicode)
                print(f"Successfully parsed multipart body as JSON")
            except Exception as e:
                print(f"JSON parsing failed: {e}")
                # Fallback a request.data normal
                try:
                    data = request.data
                    print(f"Used request.data as fallback")
                except Exception as e2:
                    print(f"request.data also failed: {e2}")
                    # Último intento: tratar como form data simple 
                    try:
                        import urllib.parse
                        body_str = request.body.decode('utf-8')
                        if body_str.startswith('{') and body_str.endswith('}'):
                            # Es JSON en el cuerpo
                            data = json.loads(body_str)
                            print(f"Final fallback: parsed as JSON successfully")
                        else:
                            # Es form data URL encoded
                            data = urllib.parse.parse_qs(body_str)
                            # Convertir listas de un elemento a valores simples
                            data = {k: v[0] if len(v) == 1 else v for k, v in data.items()}
                            print(f"Final fallback: parsed as form data")
                    except Exception as e3:
                        print(f"All parsing methods failed: {e3}")
                        return JsonResponse({
                            'error': 'Cannot parse request data', 
                            'details': f'JSON: {str(e)}, Data: {str(e2)}, Form: {str(e3)}'
                        }, status=400)
        else:
            # Contenido JSON normal
            data = request.data
            print(f"Using normal request.data")
        
        print(f"Data recibida: {list(data.keys()) if data else 'None'}")
        
        # Rest of the function stays the same...
        data = request.data
        print(f"� Data recibida: {list(data.keys())}")
        
        # Extraer imagen base64
        image_data_raw = data.get('image_data')
        if not image_data_raw:
            return JsonResponse({'error': 'No image data provided'}, status=400)
        
        # Procesar base64 CON LIMPIEZA ROBUSTA
        if image_data_raw.startswith('data:image/'):
            base64_data = image_data_raw.split(',')[1]
        else:
            base64_data = image_data_raw
        
        # LIMPIEZA ADICIONAL de base64
        base64_data = base64_data.strip()  # Quitar espacios
        base64_data = base64_data.replace('\n', '').replace('\r', '')  # Quitar saltos de línea
        
        # ARREGLAR PADDING si es necesario
        padding_needed = 4 - (len(base64_data) % 4)
        if padding_needed != 4:
            base64_data += '=' * padding_needed
            print(f"Added {padding_needed} padding characters")
        
        print(f"📏 Base64 length: {len(base64_data)}")
        print(f"📏 First 50 chars: {base64_data[:50]}")
        print(f"📏 Last 10 chars: {base64_data[-10:]}")
        
        # Convertir a imagen CON MANEJO ROBUSTO
        try:
            print(f"Starting robust image processing...")
            
            # Paso 1: Decodificar base64
            try:
                image_data = base64.b64decode(base64_data)
                print(f"Base64 decoded: {len(image_data)} bytes")
            except Exception as e:
                print(f"Base64 decode error: {e}")
                return JsonResponse({'error': f'Invalid base64: {str(e)}'}, status=400)
            
            # Paso 2: Verificar que tenemos datos
            if len(image_data) == 0:
                print(f"Empty image data after decode")
                return JsonResponse({'error': 'Empty image data'}, status=400)
            
            # Paso 3: Crear BytesIO MULTIPLE VECES para evitar consumo
            validation_buffer = io.BytesIO(image_data)
            processing_buffer = io.BytesIO(image_data)
            
            # Paso 4: Validación inicial
            try:
                # Primer intento de abrir
                test_image = Image.open(validation_buffer)
                image_format = test_image.format
                image_size = test_image.size
                image_mode = test_image.mode
                print(f"PIL open success: {image_size}, {image_format}, {image_mode}")
                
                # NO llamar verify() - puede consumir el buffer
                # Solo verificar básicos
                if image_size[0] <= 0 or image_size[1] <= 0:
                    raise ValueError("Invalid image dimensions")
                    
            except Exception as e:
                print(f"PIL validation failed: {e}")
                print(f"Data starts with: {image_data[:20].hex()}")
                print(f"Data length: {len(image_data)}")
                
                # ÚLTIMO RECURSO: Intentar diferentes formatos
                for fmt in ['JPEG', 'PNG', 'BMP', 'GIF']:
                    try:
                        fallback_buffer = io.BytesIO(image_data)
                        test_img = Image.open(fallback_buffer)
                        if test_img.format == fmt:
                            print(f"Fallback format {fmt} worked!")
                            processing_buffer = io.BytesIO(image_data)
                            image = Image.open(processing_buffer)
                            break
                    except:
                        continue
                else:
                    return JsonResponse({
                        'error': f'Cannot identify image format: {str(e)}',
                        'data_preview': image_data[:50].hex(),
                        'data_length': len(image_data)
                    }, status=400)
            
            # Si llegamos aquí, usar el buffer de procesamiento
            processing_buffer.seek(0)
            image = Image.open(processing_buffer)
            print(f"🖼️ Final image: {image.size}, {image.format}")
            
        except Exception as e:
            print(f"Complete image processing failed: {e}")
            print(f"Exception type: {type(e).__name__}")
            import traceback
            traceback.print_exc()
            return JsonResponse({
                'error': f'Image processing error: {str(e)}',
                'exception_type': type(e).__name__
            }, status=400)
        
        # VERSIÓN MÍNIMA - Solo crear registro básico
        from .models import AnalysisRecord

        # ARREGLAR CAMPOS LARGOS para evitar error de DB
        source_type_value = str(data.get('source_type', 'camera'))[:10]  # Truncar a 10 chars
        media_type_value = str(data.get('media_type', 'image'))[:10]     # Truncar a 10 chars

        print(f"🗃️ DB Values:")
        print(f"source_type: '{source_type_value}' (length: {len(source_type_value)})")
        print(f"media_type: '{media_type_value}' (length: {len(media_type_value)})")

        # v2.0 FIX: Extraer dimensiones de la imagen (image ya está cargado arriba)
        image_width, image_height = image.size
        print(f"📐 Image dimensions: {image_width}x{image_height}")

        analysis_record = AnalysisRecord.objects.create(
            user=request.user,
            total_lemons_count=int(data.get('total_lemons_count', 0)),
            media_type=media_type_value,
            media_source=source_type_value,
            source_type=source_type_value,
            analysis_metadata={  # v2.0 FIX: Agregar metadata mínimo con dimensiones
                'image_dimensions': {
                    'width': image_width,
                    'height': image_height
                }
            }
        )
        
        print(f"Record created: {analysis_record.id}")
        
        # Respuesta mínima
        return JsonResponse({
            'id': analysis_record.id,
            'total_lemons_count': analysis_record.total_lemons_count,
            'media_type': analysis_record.media_type,
            'created_at': analysis_record.created_at.isoformat(),
            'status': 'success'
        }, status=201)
        
    except Exception as e:
        print(f"Error general: {e}")
        return JsonResponse({'error': str(e)}, status=500)


# ========== ENDPOINT SIMPLE PARA WORKERS OFFLINE ==========

@ratelimit(key='user', rate='60/m', method='POST')  # Prevenir spam: 60 uploads por minuto
@api_view(['POST'])
@permission_classes([IsAuthenticated])  # ✅ Ahora usa el sistema de autenticación de DRF
def upload_simple(request):
    """
    Endpoint para subir análisis con autenticación por API key, Device Token o JWT.
    Usado por workers en modo offline.

    Soporta tres métodos de autenticación (manejados automáticamente por DRF):
    1. X-API-Key header (para workers offline - legacy)
    2. X-Device-Token header (para workers offline con PIN)
    3. Bearer JWT token (para users online)

    POST /api/upload/simple/
    Headers:
        X-API-Key: AGR-WORKER-XXXX-XXXX-XXXX  (opción 1)
        X-Device-Token: <device-token>         (opción 2)
        Authorization: Bearer <token>           (opción 3)

    FormData:
        image: File (requerido)
        local_id: String (opcional, para tracking offline)
        total_lemons_count: Integer
        confidence_avg: Float
        processing_time: Float
        model_used: String
        detection_boxes: JSON string
    """
    import json

    # ===== 1. AUTENTICACIÓN =====
    # El usuario ya está autenticado por DRF usando las clases configuradas en settings:
    # - JWTAuthentication (para JWT tokens)
    # - ApiKeyAuthentication (para X-API-Key header)
    # - DeviceTokenAuthentication (para X-Device-Token header)
    user = request.user
    
    # Log del método de autenticación usado
    auth_method = "JWT"
    if hasattr(request, 'auth') and isinstance(request.auth, WorkerAPIKey):
        auth_method = "API Key"
    elif hasattr(request, 'auth') and isinstance(request.auth, ActivatedDevice):
        auth_method = "Device Token"
    
    sync_logger.info(f"[UPLOAD-SIMPLE] Autenticación exitosa via {auth_method}: usuario {user.username}")

    # ===== 2. PROCESAR DATOS =====
    try:
        sync_logger.info(f"[UPLOAD-SIMPLE] Procesando datos del análisis...")

        # Extraer datos del FormData
        image_file = request.FILES.get('image')
        local_id = request.POST.get('local_id')
        total_lemons_count = request.POST.get('total_lemons_count')
        confidence_avg = request.POST.get('confidence_avg')
        processing_time = request.POST.get('processing_time')
        model_used = request.POST.get('model_used')
        detection_boxes_str = request.POST.get('detection_boxes')

        sync_logger.info(f"[UPLOAD-SIMPLE]   • local_id: {local_id}")
        sync_logger.info(f"[UPLOAD-SIMPLE]   • total_lemons_count: {total_lemons_count}")
        sync_logger.info(f"[UPLOAD-SIMPLE]   • image: {image_file.name if image_file else 'None'}")

        # Validar campos requeridos
        if not image_file:
            sync_logger.error(f"[UPLOAD-SIMPLE] Falta el archivo de imagen")
            return Response(
                {'error': 'El campo "image" es requerido'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ===== 3. VERIFICAR DUPLICADOS =====
        # Si local_id ya existe, retornar el análisis existente (evitar duplicados)
        if local_id:
            existing = AnalysisRecord.objects.filter(
                user=user,
                local_id=local_id
            ).first()

            if existing:
                sync_logger.warning(
                    f"[UPLOAD-SIMPLE] Duplicado detectado - local_id '{local_id}' ya existe "
                    f"(ID: {existing.id})"
                )
                # Retornar el análisis existente sin crear duplicado
                serializer = AnalysisRecordSerializer(existing, context={'request': request})
                response_data = serializer.data
                response_data['sync_status'] = 'already_synced'
                response_data['message'] = 'Este análisis ya fue sincronizado previamente'

                sync_logger.info(
                    f"[UPLOAD-SIMPLE] Respuesta duplicado - server_id: {existing.id}, "
                    f"user_id: {response_data.get('user_id')}"
                )

                return Response(response_data, status=status.HTTP_200_OK)

        # Parsear detection_boxes (JSON string)
        detection_boxes = []
        if detection_boxes_str:
            try:
                detection_boxes = json.loads(detection_boxes_str)
            except json.JSONDecodeError:
                sync_logger.warning(f"[UPLOAD-SIMPLE] No se pudo parsear detection_boxes")

        # v2.0 FIX: Extraer dimensiones de la imagen para frontend bounding boxes
        image_width = 0
        image_height = 0
        try:
            from PIL import Image
            from io import BytesIO

            # Leer imagen sin consumir el archivo (para poder guardarla después)
            image_file.seek(0)
            image_data = image_file.read()
            image_file.seek(0)  # Reset para que Django pueda guardarla

            # Obtener dimensiones
            img = Image.open(BytesIO(image_data))
            image_width, image_height = img.size

            sync_logger.info(
                f"[UPLOAD-SIMPLE] Dimensiones de imagen extraídas: "
                f"{image_width}x{image_height}"
            )
        except Exception as e:
            sync_logger.warning(
                f"[UPLOAD-SIMPLE] No se pudieron extraer dimensiones de imagen: {e}"
            )

        # Preparar datos para crear el registro
        # Usar directamente el modelo en lugar del serializer para más control
        analysis_record = AnalysisRecord.objects.create(
            user=user,
            local_id=local_id,
            original_image=image_file,
            total_lemons_count=int(total_lemons_count) if total_lemons_count else 0,
            media_type='image',
            source_type='camera',
            detection_confidence=float(confidence_avg) if confidence_avg else 0.0,
            processing_time=float(processing_time) if processing_time else 0.0,
            model_type=model_used or 'tensorflow_lite',
            analysis_metadata={
                'confidence_avg': float(confidence_avg) if confidence_avg else 0.0,
                'processing_time': float(processing_time) if processing_time else 0.0,
                'model_used': model_used or 'tensorflow_lite',
                'detection_boxes': detection_boxes,
                'image_dimensions': {  # v2.0 FIX: Requerido para frontend bounding boxes
                    'width': image_width,
                    'height': image_height
                }
            },
            detected_lemons=detection_boxes  # También guardar en el campo específico
        )

        sync_logger.info(f"[UPLOAD-SIMPLE] Análisis creado exitosamente:")
        sync_logger.info(f"[UPLOAD-SIMPLE]   • ID: {analysis_record.id}")
        sync_logger.info(f"[UPLOAD-SIMPLE]   • Local ID: {local_id}")
        sync_logger.info(f"[UPLOAD-SIMPLE]   • Usuario: {user.username}")
        sync_logger.info(f"[UPLOAD-SIMPLE]   • Limones: {analysis_record.total_lemons_count}")

        # ===== 4. RESPUESTA COMPLETA CON SERIALIZER =====
        # Usar serializer para retornar todos los campos (incluye user_id y user_username)
        serializer = AnalysisRecordSerializer(analysis_record, context={'request': request})
        response_data = serializer.data
        response_data['sync_status'] = 'synced'
        response_data['message'] = 'Análisis subido exitosamente'

        sync_logger.info(
            f"[UPLOAD-SIMPLE] Respuesta completa - server_id: {response_data.get('id')}, "
            f"user_id: {response_data.get('user_id')}, local_id: {local_id}"
        )

        return Response(response_data, status=status.HTTP_201_CREATED)

    except Exception as e:
        sync_logger.error(f"[UPLOAD-SIMPLE] Error inesperado al procesar análisis:")
        sync_logger.error(f"[UPLOAD-SIMPLE]   • Tipo: {type(e).__name__}")
        sync_logger.error(f"[UPLOAD-SIMPLE]   • Mensaje: {str(e)}")

        import traceback
        sync_logger.error(f"[UPLOAD-SIMPLE] Stack trace:")
        for line in traceback.format_exc().split('\n'):
            if line.strip():
                sync_logger.error(f"[UPLOAD-SIMPLE]   {line}")

        return Response(
            {'error': f'Error del servidor: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ========== v2.0: VISTA PARA UPLOAD DE SESIONES (6+ FOTOS) ==========

@ratelimit(key='user', rate='10/m', method='POST')  # 10 sesiones por minuto
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_session(request):
    """
    v2.0: Endpoint para subir sesión completa (6+ fotos) con detección server-side.

    El mobile captura 6+ fotos de un árbol offline, luego cuando hay WiFi
    sube toda la sesión para que el backend ejecute detección vía Hugging Face API.

    Soporta autenticación por:
    1. X-API-Key header (workers offline)
    2. X-Device-Token header (workers con PIN)
    3. Bearer JWT token (users online)

    POST /api/sessions/upload/
    Headers:
        X-API-Key: AGR-WORKER-XXXX-XXXX-XXXX  (opción 1)
        X-Device-Token: <device-token>         (opción 2)
        Authorization: Bearer <token>           (opción 3)

    FormData:
        session_id: String (requerido, UUID de la sesión)
        images: File[] (requerido, mínimo 6 archivos)
        photo_numbers: String[] (requerido, números de foto 1-6+)

    Respuesta 201 Created:
    {
        "session_id": "session_1731780234_abc123",
        "total_photos": 6,
        "total_lemons": 23,
        "analysis_ids": [101, 102, 103, 104, 105, 106],
        "confidence_avg": 0.87,
        "processing_time": 45.3,
        "created_at": "2025-11-16T14:30:34.123456Z",
        "errors": []  // Errores parciales si alguna foto falló
    }

    Errores:
    - 400: Campos faltantes o menos de 6 fotos
    - 409: Sesión duplicada (session_id ya existe)
    - 500: Todas las fotos fallaron
    """
    import json

    # ===== 1. AUTENTICACIÓN =====
    user = request.user

    # Log del método de autenticación
    auth_method = "JWT"
    if hasattr(request, 'auth') and isinstance(request.auth, WorkerAPIKey):
        auth_method = "API Key"
    elif hasattr(request, 'auth') and isinstance(request.auth, ActivatedDevice):
        auth_method = "Device Token"

    sync_logger.info(f"[SESSION-UPLOAD] Autenticación exitosa via {auth_method}: usuario {user.username}")

    # ===== 2. VALIDAR CAMPOS REQUERIDOS =====
    try:
        session_id = request.POST.get('session_id')
        images = request.FILES.getlist('images')
        photo_numbers = request.POST.getlist('photo_numbers')

        sync_logger.info(f"[SESSION-UPLOAD] Procesando sesión:")
        sync_logger.info(f"[SESSION-UPLOAD]   • session_id: {session_id}")
        sync_logger.info(f"[SESSION-UPLOAD]   • images: {len(images)} archivos")
        sync_logger.info(f"[SESSION-UPLOAD]   • photo_numbers: {photo_numbers}")

        # Validar session_id
        if not session_id:
            sync_logger.error(f"[SESSION-UPLOAD] Falta session_id")
            return Response(
                {
                    'error': 'missing_session_id',
                    'message': 'El campo "session_id" es requerido'
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validar mínimo 6 fotos
        if len(images) < 6:
            sync_logger.error(f"[SESSION-UPLOAD] Insuficientes fotos: {len(images)} (mínimo 6)")
            return Response(
                {
                    'error': 'insufficient_photos',
                    'message': f'Se requieren mínimo 6 fotos por sesión. Recibidas: {len(images)}',
                    'min_photos': 6,
                    'received_photos': len(images)
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validar photo_numbers coincide con cantidad de imágenes
        if len(photo_numbers) != len(images):
            sync_logger.warning(
                f"[SESSION-UPLOAD] Mismatch photo_numbers ({len(photo_numbers)}) vs images ({len(images)})"
            )
            # Auto-generar photo_numbers si faltan
            photo_numbers = [str(i + 1) for i in range(len(images))]

        # ===== 3. VERIFICAR SESSION DUPLICADA =====
        existing = AnalysisRecord.objects.filter(
            session_id=session_id
        ).first()

        if existing:
            sync_logger.warning(
                f"[SESSION-UPLOAD] Sesión duplicada - session_id '{session_id}' ya existe"
            )
            return Response(
                {
                    'error': 'duplicate_session',
                    'message': 'Esta sesión ya fue procesada',
                    'session_id': session_id,
                    'existing_analysis_id': existing.id
                },
                status=status.HTTP_409_CONFLICT
            )

        # ===== 4. PROCESAR CADA FOTO CON HUGGING FACE API =====
        analysis_ids = []
        total_lemons = 0
        total_confidence = 0.0
        total_processing_time = 0.0
        errors = []
        successful_analyses = 0

        sync_logger.info(f"[SESSION-UPLOAD] Iniciando procesamiento de {len(images)} fotos...")

        for i, image_file in enumerate(images):
            photo_number = int(photo_numbers[i]) if i < len(photo_numbers) else (i + 1)

            try:
                sync_logger.info(
                    f"[SESSION-UPLOAD] Procesando foto {photo_number}/{len(images)} "
                    f"({image_file.name})..."
                )

                # Llamar Hugging Face API (server-side detection)
                hf_result = HuggingFaceService.detect_lemons(image_file)

                # Verificar si HF API tuvo éxito
                if not hf_result.get('success', False):
                    error_msg = hf_result.get('error', 'Unknown error')
                    sync_logger.error(
                        f"[SESSION-UPLOAD] HF API falló para foto {photo_number}: {error_msg}"
                    )
                    errors.append({
                        'photo_number': photo_number,
                        'error': error_msg
                    })
                    # Continuar con siguiente foto
                    continue

                # Crear AnalysisRecord con resultados de HF API
                analysis_record = AnalysisRecord.objects.create(
                    user=user,
                    session_id=session_id,
                    photo_number=photo_number,
                    original_image=image_file,
                    total_lemons_count=hf_result.get('total_lemons', 0),
                    media_type='image',
                    source_type='camera',
                    detection_confidence=hf_result.get('confidence_avg', 0.0),
                    processing_time=hf_result.get('processing_time', 0.0),
                    model_type='huggingface_yolov8',
                    analysis_metadata={
                        'detection_boxes': hf_result.get('detections', []),
                        'model_used': 'huggingface_yolov8',
                        'processed_server_side': True,
                        'image_dimensions': hf_result.get('image_dimensions', {}),
                        'hf_raw_response': hf_result.get('raw_response', {})
                    },
                    detected_lemons=hf_result.get('detections', []),
                    annotated_image=hf_result.get('annotated_image', '')
                )

                analysis_ids.append(analysis_record.id)
                total_lemons += hf_result.get('total_lemons', 0)
                total_confidence += hf_result.get('confidence_avg', 0.0)
                total_processing_time += hf_result.get('processing_time', 0.0)
                successful_analyses += 1

                sync_logger.info(
                    f"[SESSION-UPLOAD] ✅ Foto {photo_number} procesada exitosamente - "
                    f"{hf_result.get('total_lemons', 0)} limones detectados"
                )

            except Exception as e:
                sync_logger.error(
                    f"[SESSION-UPLOAD] Error procesando foto {photo_number}: {type(e).__name__} - {str(e)}"
                )
                errors.append({
                    'photo_number': photo_number,
                    'error': str(e)
                })
                continue

        # ===== 5. VERIFICAR SI TODAS LAS FOTOS FALLARON =====
        if not analysis_ids:
            sync_logger.error(f"[SESSION-UPLOAD] Todas las fotos fallaron para sesión '{session_id}'")
            return Response(
                {
                    'error': 'all_photos_failed',
                    'message': 'No se pudo procesar ninguna foto de la sesión',
                    'session_id': session_id,
                    'errors': errors
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # ===== 6. CALCULAR PROMEDIOS =====
        confidence_avg = (total_confidence / successful_analyses) if successful_analyses > 0 else 0.0

        # ===== 7. RESPUESTA EXITOSA =====
        response_data = {
            'session_id': session_id,
            'total_photos': len(analysis_ids),
            'total_lemons': total_lemons,
            'analysis_ids': analysis_ids,
            'confidence_avg': round(confidence_avg, 2),
            'processing_time': round(total_processing_time, 2),
            'created_at': timezone.now().isoformat(),
            'errors': errors if errors else []
        }

        sync_logger.info(f"[SESSION-UPLOAD] ✅ Sesión procesada exitosamente:")
        sync_logger.info(f"[SESSION-UPLOAD]   • session_id: {session_id}")
        sync_logger.info(f"[SESSION-UPLOAD]   • total_photos: {len(analysis_ids)}")
        sync_logger.info(f"[SESSION-UPLOAD]   • total_lemons: {total_lemons}")
        sync_logger.info(f"[SESSION-UPLOAD]   • analysis_ids: {analysis_ids}")
        sync_logger.info(f"[SESSION-UPLOAD]   • errores parciales: {len(errors)}")

        return Response(response_data, status=status.HTTP_201_CREATED)

    except Exception as e:
        sync_logger.error(f"[SESSION-UPLOAD] Error inesperado:")
        sync_logger.error(f"[SESSION-UPLOAD]   • Tipo: {type(e).__name__}")
        sync_logger.error(f"[SESSION-UPLOAD]   • Mensaje: {str(e)}")

        import traceback
        sync_logger.error(f"[SESSION-UPLOAD] Stack trace:")
        for line in traceback.format_exc().split('\n'):
            if line.strip():
                sync_logger.error(f"[SESSION-UPLOAD]   {line}")

        return Response(
            {'error': f'Error del servidor: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def session_summary(request, session_id):
    """
    v2.0: Obtener resumen agregado de una sesión (6+ fotos).

    Útil para mobile/web que necesitan mostrar estadísticas consolidadas
    de una sesión ya procesada.

    GET /api/sessions/<session_id>/summary/
    Headers:
        X-API-Key: AGR-WORKER-XXXX-XXXX-XXXX  (workers offline)
        Authorization: Bearer <token>           (users online)

    Respuesta 200 OK:
    {
        "session_id": "session_1731780234_abc123",
        "total_photos": 6,
        "total_lemons": 23,
        "confidence_avg": 0.87,
        "created_at": "2025-11-16T14:30:34.123456Z",
        "photos": [
            {
                "photo_number": 1,
                "lemons_count": 4,
                "confidence": 0.92,
                "thumbnail_url": "/media/analysis/images/photo1.jpg",
                "analysis_id": 101
            },
            ...
        ]
    }

    Errores:
    - 404: Sesión no encontrada
    """
    user = request.user

    sync_logger.info(f"[SESSION-SUMMARY] Usuario {user.username} solicitando resumen de sesión '{session_id}'")

    # Obtener análisis de la sesión (solo del usuario autenticado)
    analyses = AnalysisRecord.objects.filter(
        session_id=session_id,
        user=user
    ).order_by('photo_number')

    if not analyses.exists():
        sync_logger.warning(f"[SESSION-SUMMARY] Sesión '{session_id}' no encontrada para usuario {user.username}")
        return Response(
            {
                'error': 'session_not_found',
                'message': f'No se encontró sesión con ID: {session_id}',
                'session_id': session_id
            },
            status=status.HTTP_404_NOT_FOUND
        )

    # Calcular agregados usando Django ORM
    aggregates = analyses.aggregate(
        total_lemons=Sum('total_lemons_count'),
        confidence_avg=Avg('detection_confidence')
    )

    # Construir lista de fotos
    photos = []
    for analysis in analyses:
        photos.append({
            'photo_number': analysis.photo_number,
            'lemons_count': analysis.total_lemons_count,
            'confidence': round(analysis.detection_confidence or 0, 2),
            'thumbnail_url': analysis.original_image.url if analysis.original_image else None,
            'analysis_id': analysis.id
        })

    # Construir respuesta
    response_data = {
        'session_id': session_id,
        'total_photos': analyses.count(),
        'total_lemons': aggregates['total_lemons'] or 0,
        'confidence_avg': round(aggregates['confidence_avg'] or 0, 2),
        'created_at': analyses.first().created_at.isoformat() if analyses.first() else None,
        'photos': photos
    }

    sync_logger.info(
        f"[SESSION-SUMMARY] Resumen retornado: {analyses.count()} fotos, "
        f"{aggregates['total_lemons'] or 0} limones totales"
    )

    return Response(response_data, status=status.HTTP_200_OK)


# ========== VISTAS PARA RESTABLECIMIENTO DE CONTRASEÑA ==========

@ratelimit(key='ip', rate='3/m', method='POST')  # Límite más restrictivo para seguridad
@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    """
    Endpoint para solicitar restablecimiento de contraseña.
    Envía un email con un token de restablecimiento.
    
    POST /api/password-reset/request/
    {
        "email": "usuario@ejemplo.com"
    }
    """
    from .serializers import PasswordResetRequestSerializer
    from .models import PasswordResetToken
    from django.core.mail import send_mail
    from django.conf import settings
    import logging
    
    logger = logging.getLogger(__name__)
    
    serializer = PasswordResetRequestSerializer(data=request.data)
    if serializer.is_valid():
        try:
            user = serializer.get_user()
            
            # Invalidar tokens anteriores del usuario
            PasswordResetToken.objects.filter(user=user, used=False).update(used=True)
            
            # Crear nuevo token
            reset_token = PasswordResetToken.objects.create(user=user)
            
            # Configurar el mensaje del email
            reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token.token}"
            
            subject = "Restablecimiento de contraseña - AgriRipeness"
            message = f"""
            Hola {user.first_name or user.username},
            
            Has solicitado restablecer tu contraseña en AgriRipeness.
            
            Para crear una nueva contraseña, haz clic en el siguiente enlace:
            {reset_url}
            
            Este enlace expirará en 1 hora por seguridad.
            
            Si no solicitaste este restablecimiento, puedes ignorar este mensaje.
            
            Saludos,
            El equipo de AgriRipeness
            """
            
            html_message = f"""
            <html>
            <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
                <div style="background-color: #4CAF50; color: white; padding: 20px; text-align: center;">
                    <h1>AgriRipeness</h1>
                    <h2>Restablecimiento de Contraseña</h2>
                </div>
                
                <div style="padding: 20px; background-color: #f9f9f9;">
                    <p>Hola <strong>{user.first_name or user.username}</strong>,</p>
                    
                    <p>Has solicitado restablecer tu contraseña en AgriRipeness.</p>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <a href="{reset_url}" 
                           style="background-color: #4CAF50; color: white; padding: 12px 24px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Restablecer Contraseña
                        </a>
                    </div>
                    
                    <p style="color: #666; font-size: 14px;">
                        <strong>Importante:</strong> Este enlace expirará en 1 hora por seguridad.
                    </p>
                    
                    <p style="color: #666; font-size: 14px;">
                        Si no puedes hacer clic en el botón, copia y pega este enlace en tu navegador:<br>
                        <code style="background-color: #eee; padding: 5px;">{reset_url}</code>
                    </p>
                    
                    <p style="color: #666; font-size: 12px; margin-top: 30px;">
                        Si no solicitaste este restablecimiento, puedes ignorar este mensaje.
                    </p>
                </div>
                
                <div style="background-color: #333; color: white; padding: 10px; text-align: center; font-size: 12px;">
                    © 2025 AgriRipeness - Sistema de Análisis de Madurez de Cultivos
                </div>
            </body>
            </html>
            """
            
            # ⚠️ TEMPORAL: Emails deshabilitados (Railway bloquea SMTP)
            # El superadmin debe restablecer contraseñas manualmente desde Django Admin
            
            logger.warning(f"Password reset requested for {user.email} - Email NOT sent (SMTP disabled)")
            
            # Guardar token para uso manual del superadmin
            logger.info(f"Reset token for {user.email}: {reset_token.token}")
            
            # Responder al usuario
            return Response({
                'message': 'Solicitud recibida. Por favor contacta al administrador del sistema para restablecer tu contraseña.',
                'email': user.email,
                'support_email': settings.SUPERADMIN_EMAIL,
                'note': 'El sistema de emails está temporalmente deshabilitado. El administrador te contactará pronto.'
            }, status=status.HTTP_200_OK)
            
            # CÓDIGO ORIGINAL (comentado temporalmente):
            # try:
            #     send_mail(
            #         subject=subject,
            #         message=message,
            #         html_message=html_message,
            #         from_email=settings.DEFAULT_FROM_EMAIL,
            #         recipient_list=[user.email],
            #         fail_silently=False,
            #     )
            #     
            #     logger.info(f"Password reset email sent to {user.email}")
            #     
            #     return Response({
            #         'message': 'Se ha enviado un enlace de restablecimiento a tu correo electrónico.',
            #         'email': user.email,
            #         'token_expires_in': '1 hora'
            #     }, status=status.HTTP_200_OK)
            #     
            # except Exception as email_error:
            #     logger.error(f"Failed to send password reset email: {email_error}")
            #     
            #     # En desarrollo, devolver el token directamente
            #     if settings.DEBUG:
            #         return Response({
            #             'message': 'Token de restablecimiento generado (modo desarrollo)',
            #             'reset_token': reset_token.token,
            #             'reset_url': reset_url,
            #             'warning': 'Email no configurado - usando modo desarrollo'
            #         }, status=status.HTTP_200_OK)
            #     
            #     return Response({
            #         'error': 'Error al enviar el email. Intenta nuevamente más tarde.'
            #     }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
                
        except Exception as e:
            logger.error(f"Password reset request error: {e}")
            return Response({
                'error': 'Error interno del servidor'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@ratelimit(key='ip', rate='5/m', method='POST')
@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    """
    Endpoint para confirmar el restablecimiento de contraseña con token.
    
    POST /api/password-reset/confirm/
    {
        "token": "abc123...",
        "new_password": "nuevapassword123",
        "confirm_password": "nuevapassword123"
    }
    """
    from .serializers import PasswordResetConfirmSerializer
    import logging
    
    logger = logging.getLogger(__name__)
    
    serializer = PasswordResetConfirmSerializer(data=request.data)
    if serializer.is_valid():
        try:
            user = serializer.save()
            
            logger.info(f"Password successfully reset for user {user.username}")
            
            return Response({
                'message': 'Tu contraseña ha sido restablecida exitosamente.',
                'username': user.username,
                'success': True
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Password reset confirm error: {e}")
            return Response({
                'error': 'Error al restablecer la contraseña'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@ratelimit(key='user', rate='3/m', method='POST')
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def password_change(request):
    """
    Endpoint para cambiar contraseña cuando el usuario está autenticado.
    
    **Rate Limit**: 3 intentos por minuto por usuario (prevenir brute force).
    
    Request Body:
        {
            "current_password": "passwordactual",
            "new_password": "nuevapassword123",
            "confirm_password": "nuevapassword123"
        }
    
    Response (200 OK):
        {
            "message": "Tu contraseña ha sido cambiada exitosamente.",
            "username": "usuario",
            "password_change_required": false,  # ← Actualizado automáticamente
            "success": true
        }
    
    Response (400 Bad Request):
        {
            "current_password": ["La contraseña actual es incorrecta."],
            "confirm_password": ["Las contraseñas no coinciden."]
        }
    
    Response (429 Too Many Requests):
        - Cuando se excede el rate limit de 3/minuto
    
    **IMPORTANTE**: 
    - Este endpoint actualiza automáticamente `password_change_required = False`
    - Después de cambiar contraseña, frontend debe permitir acceso normal
    - El PasswordChangeSerializer valida: contraseña actual, mínimo 6 chars, coincidencia
    
    Logging:
        - INFO: Contraseña cambiada exitosamente
        - ERROR: Error inesperado durante el cambio
    """
    from .serializers import PasswordChangeSerializer
    import logging
    
    logger = logging.getLogger('password')
    
    serializer = PasswordChangeSerializer(data=request.data, user=request.user)
    if serializer.is_valid():
        try:
            user = serializer.save()
            
            # Obtener estado actualizado del flag
            password_change_required = user.profile.password_change_required if hasattr(user, 'profile') else False
            
            logger.info(
                f"✅ Contraseña cambiada: {user.email} | "
                f"Password change required actualizado: {password_change_required}"
            )
            
            return Response({
                'message': 'Tu contraseña ha sido cambiada exitosamente.',
                'username': user.username,
                'password_change_required': password_change_required,
                'success': True
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"❌ Error al cambiar contraseña: {user.email} - {str(e)}")
            return Response({
                'error': 'Error al cambiar la contraseña'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    # Validación fallida
    logger.warning(f"⚠️ Validación fallida en cambio de contraseña: {request.user.email}")
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([AllowAny])
def password_reset_validate_token(request):
    """
    Endpoint para validar si un token de restablecimiento es válido.
    
    GET /api/password-reset/validate-token/?token=abc123...
    """
    from .models import PasswordResetToken
    
    token = request.GET.get('token')
    if not token:
        return Response({
            'valid': False,
            'error': 'Token requerido'
        }, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        token_obj = PasswordResetToken.objects.get(token=token)
        is_valid = token_obj.is_valid()
        
        if is_valid:
            return Response({
                'valid': True,
                'user': {
                    'username': token_obj.user.username,
                    'email': token_obj.user.email
                },
                'expires_at': token_obj.expires_at
            }, status=status.HTTP_200_OK)
        else:
            return Response({
                'valid': False,
                'error': 'Token expirado o ya usado'
            }, status=status.HTTP_400_BAD_REQUEST)
            
    except PasswordResetToken.DoesNotExist:
        return Response({
            'valid': False,
            'error': 'Token inválido'
        }, status=status.HTTP_400_BAD_REQUEST)


# ========== API KEY MANAGEMENT VIEWSET ==========

class WorkerAPIKeyViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar API keys de workers offline.

    Endpoints:
    - GET /api/api-keys/ - Lista las API keys del usuario autenticado
    - POST /api/api-keys/ - Crea una nueva API key
    - DELETE /api/api-keys/{id}/ - Revoca (desactiva) una API key
    - POST /api/api-keys/{id}/revoke/ - Revoca (desactiva) una API key (action alternativo)
    """
    permission_classes = [IsAuthenticated]
    serializer_class = WorkerAPIKeySerializer

    def get_queryset(self):
        """
        Retorna solo las API keys del usuario autenticado.
        Los usuarios solo pueden ver sus propias API keys.
        """
        return WorkerAPIKey.objects.filter(user=self.request.user)

    def get_serializer_class(self):
        """
        Usa diferentes serializers para list vs create/retrieve.
        """
        if self.action == 'list':
            return WorkerAPIKeyListSerializer
        return WorkerAPIKeySerializer

    def create(self, request, *args, **kwargs):
        """
        Crea una nueva API key para el usuario autenticado.

        Body:
        {
            "name": "Worker-001"  // Nombre descriptivo del worker
        }

        Response:
        {
            "id": 1,
            "user": 1,
            "user_username": "admin",
            "name": "Worker-001",
            "key": "AGR-WORKER-ABCD-EFGH-IJKL",  // ⚠️ SOLO SE MUESTRA AQUÍ
            "key_prefix": "AGR-WORKER-ABC",
            "created_at": "2025-11-06T10:00:00Z",
            "last_used_at": null,
            "is_active": true
        }
        """
        # Validar que se proporcione el nombre
        name = request.data.get('name')
        if not name:
            return Response({
                'error': 'El campo "name" es requerido'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Crear la API key con el usuario autenticado
        serializer = self.get_serializer(data={
            'user': request.user.id,
            'name': name
        })
        serializer.is_valid(raise_exception=True)
        api_key_instance = serializer.save()

        # Log de creación
        sync_logger.info(
            f"[API-KEY-CREATED] Usuario '{request.user.username}' creó API key: "
            f"{api_key_instance.key_prefix}... ({name})"
        )

        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers={'X-Warning': '⚠️ Guarda esta API key ahora. No podrás verla de nuevo.'}
        )

    def list(self, request, *args, **kwargs):
        """
        Lista todas las API keys del usuario autenticado.
        NO incluye las keys completas, solo los prefijos.
        """
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response({
            'count': queryset.count(),
            'results': serializer.data
        })

    def destroy(self, request, *args, **kwargs):
        """
        Revoca (desactiva) una API key.
        No la elimina físicamente, solo la marca como inactiva.
        """
        instance = self.get_object()

        # Marcar como inactiva en lugar de eliminar
        instance.mark_inactive()

        sync_logger.info(
            f"[API-KEY-REVOKED] Usuario '{request.user.username}' revocó API key: "
            f"{instance.key_prefix}... ({instance.name})"
        )

        return Response({
            'message': f'API key "{instance.name}" revocada exitosamente',
            'key_prefix': instance.key_prefix
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """
        Action alternativo para revocar una API key.
        POST /api/api-keys/{id}/revoke/
        """
        instance = self.get_object()

        if not instance.is_active:
            return Response({
                'error': 'Esta API key ya está inactiva'
            }, status=status.HTTP_400_BAD_REQUEST)

        instance.mark_inactive()

        sync_logger.info(
            f"[API-KEY-REVOKED] Usuario '{request.user.username}' revocó API key: "
            f"{instance.key_prefix}... ({instance.name})"
        )

        return Response({
            'message': f'API key "{instance.name}" revocada exitosamente',
            'key_prefix': instance.key_prefix
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """
        Reactiva una API key previamente revocada.
        POST /api/api-keys/{id}/activate/
        """
        instance = self.get_object()

        if instance.is_active:
            return Response({
                'error': 'Esta API key ya está activa'
            }, status=status.HTTP_400_BAD_REQUEST)

        instance.is_active = True
        instance.save(update_fields=['is_active'])

        sync_logger.info(
            f"[API-KEY-ACTIVATED] Usuario '{request.user.username}' reactivó API key: "
            f"{instance.key_prefix}... ({instance.name})"
        )

        return Response({
            'message': f'API key "{instance.name}" reactivada exitosamente',
            'key_prefix': instance.key_prefix
        }, status=status.HTTP_200_OK)


# ========== WORKERS MANAGEMENT VIEWSET ==========

class WorkerViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestionar Workers (usuarios non-staff).

    Endpoints:
    - GET /api/workers/ - Lista todos los workers
    - POST /api/workers/ - Crea un nuevo worker con API key
    - GET /api/workers/{id}/ - Obtiene detalles de un worker
    - PATCH /api/workers/{id}/ - Actualiza un worker
    - DELETE /api/workers/{id}/ - Elimina un worker
    - POST /api/workers/{id}/revoke/ - Revoca la API key del worker
    - POST /api/workers/{id}/activate/ - Reactiva la API key del worker
    """
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        """Retorna solo usuarios non-staff (workers)"""
        return User.objects.filter(is_staff=False).order_by('-date_joined')

    def get_serializer_class(self):
        """Usa diferentes serializers según la acción"""
        if self.action == 'create':
            return serializers.WorkerCreateSerializer
        elif self.action == 'list':
            return serializers.WorkerListSerializer
        return serializers.WorkerSerializer

    def create(self, request, *args, **kwargs):
        """
        Crea un nuevo worker y genera automáticamente su API key.

        Body:
        {
            "username": "worker01",
            "first_name": "John",
            "last_name": "Doe",  // opcional
            "email": "worker@example.com"  // opcional
        }

        Response incluye la API key generada (solo visible una vez).
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        worker = serializer.save()

        sync_logger.info(
            f"[WORKER-CREATED] Admin '{request.user.username}' creó worker: "
            f"{worker.username} con API key"
        )

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        """
        Elimina un worker y todas sus API keys asociadas.
        """
        instance = self.get_object()
        username = instance.username

        # Eliminar todas las API keys del worker
        api_keys_count = instance.api_keys.count()
        instance.api_keys.all().delete()

        # Eliminar el worker
        self.perform_destroy(instance)

        sync_logger.info(
            f"[WORKER-DELETED] Admin '{request.user.username}' eliminó worker: "
            f"{username} ({api_keys_count} API keys eliminadas)"
        )

        return Response({
            'message': f'Worker "{username}" eliminado exitosamente',
            'api_keys_deleted': api_keys_count
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        """
        Revoca todas las API keys activas del worker.
        POST /api/workers/{id}/revoke/
        """
        worker = self.get_object()

        # Desactivar todas las API keys activas
        active_keys = worker.api_keys.filter(is_active=True)
        count = active_keys.count()
        active_keys.update(is_active=False)

        sync_logger.info(
            f"[WORKER-REVOKED] Admin '{request.user.username}' revocó {count} "
            f"API key(s) del worker: {worker.username}"
        )

        return Response({
            'message': f'Se revocaron {count} API key(s) del worker "{worker.username}"',
            'keys_revoked': count
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """
        Reactiva todas las API keys del worker.
        POST /api/workers/{id}/activate/
        """
        worker = self.get_object()

        # Activar todas las API keys inactivas
        inactive_keys = worker.api_keys.filter(is_active=False)
        count = inactive_keys.count()
        inactive_keys.update(is_active=True)

        sync_logger.info(
            f"[WORKER-ACTIVATED] Admin '{request.user.username}' activó {count} "
            f"API key(s) del worker: {worker.username}"
        )

        return Response({
            'message': f'Se activaron {count} API key(s) del worker "{worker.username}"',
            'keys_activated': count
        }, status=status.HTTP_200_OK)


# ========== VALIDACIÓN DE API KEY/DEVICE TOKEN PARA LOGIN OFFLINE ==========

@api_view(['POST'])
@permission_classes([IsAuthenticated])  # ✅ Usa sistema DRF - acepta API Key, Device Token o JWT
def validate_api_key(request):
    """
    Valida credenciales de autenticación para login offline de workers.
    
    ⚠️ DEPRECATION NOTICE: Este endpoint seguirá funcionando pero se recomienda
    usar Device Tokens (X-Device-Token) en lugar de API Keys (X-API-Key).
    
    Acepta tres métodos de autenticación (manejados automáticamente por DRF):
    1. X-Device-Token header (RECOMENDADO - para workers offline con PIN)
    2. X-API-Key header (LEGACY - para workers offline sin PIN)
    3. Bearer JWT token (para users online)

    POST /api/validate-api-key/
    Headers:
        X-Device-Token: <device-token>         (RECOMENDADO)
        X-API-Key: AGR-WORKER-XXXX-XXXX-XXXX  (LEGACY)
        Authorization: Bearer <token>          (ONLINE)

    Response (si válida):
    {
        "valid": true,
        "auth_method": "device_token",  // o "api_key" o "jwt"
        "user": {
            "id": 1,
            "username": "worker01",
            "first_name": "John",
            "last_name": "Doe",
            "email": "worker@example.com",
            "role": "worker"
        }
    }
    """
    # El usuario ya está autenticado por DRF usando las clases configuradas
    user = request.user
    
    # Determinar método de autenticación usado
    auth_method = "jwt"
    if hasattr(request, 'auth'):
        if isinstance(request.auth, ActivatedDevice):
            auth_method = "device_token"
        elif isinstance(request.auth, WorkerAPIKey):
            auth_method = "api_key"
    
    # Obtener rol del UserProfile
    try:
        role = user.profile.role
    except:
        # Fallback: crear profile si no existe
        from users.models import UserProfile
        role = 'worker'
        UserProfile.objects.create(user=user, role=role)

    sync_logger.info(
        f"[AUTH-VALIDATED] Usuario '{user.username}' validó credenciales via {auth_method}"
    )

    return Response({
        'valid': True,
        'auth_method': auth_method,
        'user': {
            'id': user.id,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'role': role,
        }
    })


# ========== VISTA WEB PARA GENERAR API KEYS ==========

@staff_member_required
def generate_worker_api_key_view(request):
    """
    Vista web para que el admin genere API keys fácilmente.
    Accesible en: /api/generate-api-key/
    Solo accesible para staff members.
    """
    if request.method == 'POST':
        worker_id = request.POST.get('worker_id')
        name = request.POST.get('name')

        if not worker_id or not name:
            return JsonResponse({
                'success': False,
                'error': 'Worker y nombre son requeridos'
            }, status=400)

        try:
            worker = User.objects.get(id=worker_id)
            api_key_obj, plain_key = WorkerAPIKey.create_key(worker, name)

            sync_logger.info(
                f"[API-KEY-WEB-CREATED] Admin '{request.user.username}' creó API key "
                f"para worker '{worker.username}': {api_key_obj.key_prefix}... ({name})"
            )

            return JsonResponse({
                'success': True,
                'worker': worker.username,
                'worker_full_name': worker.get_full_name() or worker.username,
                'api_key': plain_key,
                'key_prefix': api_key_obj.key_prefix,
                'name': name,
                'created_at': api_key_obj.created_at.isoformat(),
            })
        except User.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Worker no encontrado'
            }, status=404)
        except Exception as e:
            sync_logger.error(f"[API-KEY-WEB-ERROR] Error creando API key: {e}")
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=500)

    # GET: Mostrar formulario
    # Obtener workers (usuarios no-staff activos)
    workers = User.objects.filter(is_staff=False, is_active=True).order_by('username')

    return render(request, 'admin/generate_api_key.html', {
        'workers': workers,
        'title': 'Generar API Key para Worker'
    })


# ========== OFFLINE AUTHENTICATION ENDPOINTS (FASE 3) ==========

@api_view(['POST'])
@permission_classes([AllowAny])
def get_workers_for_activation(request):
    """
    Retorna lista de workers disponibles para activar en un dispositivo.

    Endpoint: POST /api/workers/activation-list/

    Request body (opcional):
        {
            "device_id": "Android_Pixel6_1699..."
        }

    Response:
        {
            "workers": [...],
            "total": 2
        }
    """
    device_id = request.data.get('device_id')

    # Verificar si el device_id ya está activado
    if device_id:
        existing_device = ActivatedDevice.objects.filter(
            device_id=device_id,
            is_active=True
        ).first()

        if existing_device:
            return Response(
                {"error": "Este dispositivo ya está activado para otro usuario"},
                status=status.HTTP_400_BAD_REQUEST
            )

    # Obtener TODOS los workers activos (con o sin PIN configurado)
    # Filtrar por role='worker' usando el UserProfile
    workers = User.objects.filter(
        is_active=True,
        profile__role='worker',
        # profile__pin_configured=True  <-- REMOVIDO: Ahora incluimos workers sin PIN
    ).select_related('profile')

    workers_data = []
    for worker in workers:
        workers_data.append({
            "id": worker.id,
            "username": worker.username,
            "first_name": worker.first_name,
            "last_name": worker.last_name,
            "full_name": f"{worker.first_name} {worker.last_name}".strip() or worker.username,
            "email": worker.email,
            "has_pin": worker.profile.pin_configured,  # IMPORTANTE: Indica si tiene PIN configurado
            "is_active": worker.is_active,
        })

    return Response({
        "workers": workers_data,
        "total": len(workers_data)
    })


@ratelimit(key='ip', rate='10/m', method='POST')
@api_view(['POST'])
@permission_classes([AllowAny])
def worker_login(request):
    """
    Login UNIFICADO para workers usando EMAIL + PASSWORD/PIN.
    
    Endpoint: POST /api/workers/login/
    
    Primer login (password temporal):
        {
            "email": "worker@example.com",
            "password": "TempPass2024!"
        }
    
    Login normal (después de configurar PIN):
        {
            "email": "worker@example.com",
            "pin": "1234"
        }
    
    Response:
        {
            "access": "jwt_access_token",
            "refresh": "jwt_refresh_token",
            "user": {
                "id": 5,
                "email": "worker@example.com",
                "first_name": "Maria",
                "last_name": "Garcia",
                "role": "worker",
                "api_key": "agri_abc123...",
                "password_change_required": true,
                "pin_configured": false
            }
        }
    """
    from django.contrib.auth import authenticate
    
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password', '').strip()
    pin = request.data.get('pin', '').strip()
    
    # Validar que se proporcione email y al menos password o PIN
    if not email or (not password and not pin):
        return Response(
            {"detail": "Email y password/PIN son requeridos"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Buscar usuario por email (cualquier rol)
    try:
        user = User.objects.select_related('profile').get(email=email, is_active=True)
    except User.DoesNotExist:
        # No revelar si el email existe o no (seguridad)
        return Response(
            {"detail": "Credenciales inválidas"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    # ========== VALIDACIÓN DE TIPO DE USUARIO (SOPORTE QA) ==========
    # Si el usuario existe pero NO es worker, devolver error claro
    user_role = user.profile.role if hasattr(user, 'profile') else 'unknown'
    
    if user_role != 'worker':
        sync_logger.warning(
            f"⚠️ [WORKER-LOGIN-WRONG-ENDPOINT] User {email} (role: {user_role}) "
            f"intentó login en /api/workers/login/ | Use /api/auth/login/ para admins"
        )
        return Response(
            {
                "detail": "Tipo de usuario incorrecto para este endpoint",
                "hint": "Este endpoint es solo para workers. Los administradores deben usar /api/auth/login/",
                "user_type_detected": user_role
            },
            status=status.HTTP_403_FORBIDDEN
        )
    
    worker = user  # Ahora sabemos que es un worker válido
    
    # FLUJO 1: Login con PASSWORD (primer login o después de reset)
    if password:
        # Usar Django authenticate para verificar password
        authenticated_user = authenticate(username=worker.username, password=password)
        
        if not authenticated_user:
            sync_logger.warning(
                f"[WORKER-LOGIN-FAILED] Password incorrecto para {email} desde IP {get_client_ip(request)}"
            )
            return Response(
                {"detail": "Credenciales inválidas"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        sync_logger.info(
            f"[WORKER-LOGIN-PASSWORD] Worker {worker.email} login con password exitoso"
        )
    
    # FLUJO 2: Login con PIN (login normal después de configurar PIN)
    elif pin:
        # Verificar que tenga PIN configurado
        if not worker.profile.pin_configured:
            return Response(
                {"detail": "PIN no configurado. Usa tu password temporal."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Verificar PIN
        if not worker.profile.verify_pin(pin):
            sync_logger.warning(
                f"[WORKER-LOGIN-FAILED] PIN incorrecto para {email} desde IP {get_client_ip(request)}"
            )
            return Response(
                {"detail": "Credenciales inválidas"},
                status=status.HTTP_401_UNAUTHORIZED
            )
        
        sync_logger.info(
            f"[WORKER-LOGIN-PIN] Worker {worker.email} login con PIN exitoso"
        )
    
    # Login exitoso - generar tokens JWT
    refresh = RefreshToken.for_user(worker)
    
    # Obtener API key del worker (primera activa)
    # NOTA: La API key completa NO se guarda en BD por seguridad (solo hash)
    # Solo retornamos el prefijo para que el worker identifique su key
    api_key_obj = worker.api_keys.filter(is_active=True).first()
    api_key_prefix = f"{api_key_obj.key_prefix}..." if api_key_obj else None
    
    # Información del perfil
    password_change_required = worker.profile.password_change_required if hasattr(worker, 'profile') else False
    pin_configured = worker.profile.pin_configured if hasattr(worker, 'profile') else False
    
    return Response({
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "user": {
            "id": worker.id,
            "email": worker.email,
            "first_name": worker.first_name,
            "last_name": worker.last_name,
            "role": "worker",
            "api_key_prefix": api_key_prefix,  # Solo prefijo, no la key completa
            "password_change_required": password_change_required,
            "pin_configured": pin_configured
        }
    }, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def activate_device(request):
    """
    Activa un dispositivo para un worker usando su PIN.

    Endpoint: POST /api/workers/activate-device/

    Request body:
        {
            "worker_id": 5,
            "pin": "1234",
            "device_id": "Android_Pixel6_1699823456789",
            "device_name": "Pixel 6 - Android",
            "platform": "Android",
            "app_version": "1.0.0"
        }

    Response:
        {
            "success": true,
            "message": "Dispositivo activado correctamente",
            "worker": {...},
            "device_token": "unique-device-token-abc123",
            "activated_at": "2025-11-10T16:30:00Z"
        }
    """
    worker_id = request.data.get('worker_id')
    pin = request.data.get('pin')
    device_id = request.data.get('device_id')
    device_name = request.data.get('device_name')
    platform = request.data.get('platform')
    app_version = request.data.get('app_version')

    # Validar datos requeridos
    if not all([worker_id, pin, device_id, device_name]):
        return Response(
            {"success": False, "error": "Datos incompletos"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Obtener worker
    try:
        worker = User.objects.select_related('profile').get(
            id=worker_id,
            profile__role='worker'
        )
    except User.DoesNotExist:
        return Response(
            {"success": False, "error": "Worker no encontrado"},
            status=status.HTTP_404_NOT_FOUND
        )

    # Verificar que el worker esté activo
    if not worker.is_active:
        return Response(
            {"success": False, "error": "Worker inactivo"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Verificar que tenga PIN configurado
    if not worker.profile.pin_configured:
        return Response(
            {"success": False, "error": "PIN no configurado para este worker"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Verificar PIN
    if not worker.profile.verify_pin(pin):
        return Response(
            {"success": False, "error": "PIN incorrecto"},
            status=status.HTTP_401_UNAUTHORIZED
        )

    # Verificar si el dispositivo ya está activado
    existing_device = ActivatedDevice.objects.filter(
        device_id=device_id,
        is_active=True
    ).first()

    if existing_device:
        # Si ya existe para este mismo worker, retornar success
        if existing_device.worker_id == worker_id:
            existing_device.update_last_used()

            # Obtener API key del worker
            api_key_obj = WorkerAPIKey.objects.filter(
                user=worker,
                is_active=True
            ).first()

            return Response({
                "success": True,
                "message": "Dispositivo ya estaba activado",
                "worker": serialize_worker(worker, api_key_obj),
                "device_token": existing_device.device_token,
                "activated_at": existing_device.activated_at.isoformat()
            })
        else:
            return Response(
                {"success": False, "error": "Dispositivo ya activado para otro worker"},
                status=status.HTTP_400_BAD_REQUEST
            )

    # Generar device token único
    device_token = ActivatedDevice.generate_device_token()

    # Crear dispositivo activado
    activated_device = ActivatedDevice.objects.create(
        worker=worker,
        device_id=device_id,
        device_name=device_name,
        device_token=device_token,
        platform=platform,
        app_version=app_version,
        is_active=True
    )

    # Actualizar última activación del worker
    worker.profile.last_device_activation = timezone.now()
    worker.profile.save(update_fields=['last_device_activation'])

    # Obtener API key del worker
    api_key_obj = WorkerAPIKey.objects.filter(
        user=worker,
        is_active=True
    ).first()

    return Response({
        "success": True,
        "message": "Dispositivo activado correctamente",
        "worker": serialize_worker(worker, api_key_obj),
        "device_token": device_token,
        "activated_at": activated_device.activated_at.isoformat()
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def set_worker_pin(request):
    """
    Permite a un trabajador configurar su PIN por primera vez.
    Requiere autenticación JWT.

    Endpoint: POST /api/workers/set-pin/

    Headers:
        Authorization: Bearer <access_token>

    Request body:
        {
            "pin": "1234"
        }

    Response:
        {
            "success": true,
            "message": "PIN configurado exitosamente",
            "worker": {
                "id": 5,
                "username": "jperez",
                "full_name": "Juan Pérez",
                "has_pin": true
            }
        }
    """
    import re
    
    user = request.user
    
    # Validar que el usuario es un trabajador
    try:
        profile = user.profile
        if profile.role != 'worker':
            return Response(
                {
                    "success": False,
                    "error": "Solo los trabajadores pueden configurar un PIN"
                },
                status=status.HTTP_403_FORBIDDEN
            )
    except:
        return Response(
            {
                "success": False,
                "error": "Perfil de usuario no encontrado"
            },
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Obtener PIN del request
    pin = str(request.data.get('pin', ''))
    
    if not pin:
        return Response(
            {
                "success": False,
                "error": "Debes proporcionar un PIN"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar formato del PIN (4-6 dígitos numéricos)
    if not re.match(r'^\d{4,6}$', pin):
        return Response(
            {
                "success": False,
                "error": "El PIN debe tener entre 4 y 6 dígitos numéricos"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar que no use PINs débiles
    weak_pins = ['0000', '1111', '2222', '3333', '4444', '5555', 
                 '6666', '7777', '8888', '9999', '1234', '4321']
    if pin in weak_pins:
        return Response(
            {
                "success": False,
                "error": "PIN muy débil. Por favor elige otro PIN"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        # Usar el método set_pin del modelo UserProfile
        profile.set_pin(pin)
        
        return Response({
            "success": True,
            "message": "PIN configurado exitosamente",
            "worker": {
                "id": user.id,
                "username": user.username,
                "full_name": f"{user.first_name} {user.last_name}".strip() or user.username,
                "has_pin": profile.pin_configured
            }
        })
        
    except Exception as e:
        return Response(
            {
                "success": False,
                "error": f"Error al guardar el PIN: {str(e)}"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def regenerate_device_token(request):
    """
    Permite a un worker regenerar su Device Token para el dispositivo actual.
    
    ✨ NUEVO - Método recomendado para autenticación offline.
    
    Cuando un worker regenera su Device Token:
    - Se invalida el token anterior de ese dispositivo
    - Se genera un nuevo token único
    - El worker debe guardar el nuevo token en su dispositivo
    
    Requiere autenticación via:
    - JWT (si está online)
    - Device Token existente (para renovar)
    - API Key legacy (para migrar a Device Token)

    Endpoint: POST /api/workers/regenerate-device-token/

    Headers:
        Authorization: Bearer <access_token>  (JWT)
        X-Device-Token: <current-device-token>  (para renovar)
        X-API-Key: <api-key>  (para migrar a Device Token)

    Request body:
        {
            "device_id": "samsung/a04ub/a04:14/...",
            "device_name": "Galaxy A04",
            "pin": "1234"  (requerido para verificación)
        }

    Response (éxito):
        {
            "success": true,
            "message": "Device Token regenerado exitosamente",
            "device_token": "<nuevo-token-48-chars>",
            "device": {
                "device_id": "samsung/...",
                "device_name": "Galaxy A04",
                "activated_at": "2025-11-10T22:30:00Z"
            }
        }
    
    Response (error):
        {
            "success": false,
            "error": "Descripción del error"
        }
    """
    import re
    from django.utils import timezone
    
    user = request.user
    
    # Validar que el usuario es un trabajador
    try:
        profile = user.profile
        if profile.role != 'worker':
            return Response(
                {
                    "success": False,
                    "error": "Solo los trabajadores pueden regenerar Device Tokens"
                },
                status=status.HTTP_403_FORBIDDEN
            )
    except:
        return Response(
            {
                "success": False,
                "error": "Perfil de usuario no encontrado"
            },
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Validar que el worker tiene PIN configurado
    if not profile.pin_configured:
        return Response(
            {
                "success": False,
                "error": "Debes configurar un PIN antes de regenerar el Device Token",
                "action_required": "set_pin"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Obtener datos del request
    device_id = request.data.get('device_id', '').strip()
    device_name = request.data.get('device_name', '').strip()
    pin = str(request.data.get('pin', ''))
    
    # Validar campos requeridos
    if not device_id:
        return Response(
            {
                "success": False,
                "error": "El campo 'device_id' es requerido"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not device_name:
        return Response(
            {
                "success": False,
                "error": "El campo 'device_name' es requerido"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not pin:
        return Response(
            {
                "success": False,
                "error": "El PIN es requerido para regenerar el Device Token"
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validar PIN
    if not profile.verify_pin(pin):
        return Response(
            {
                "success": False,
                "error": "PIN incorrecto"
            },
            status=status.HTTP_401_UNAUTHORIZED
        )
    
    try:
        # Buscar dispositivo existente o crear uno nuevo
        device, created = ActivatedDevice.objects.get_or_create(
            worker=user,
            device_id=device_id,
            defaults={
                'device_name': device_name,
                'is_active': True
            }
        )
        
        if not created:
            # Si el dispositivo ya existe, regenerar token
            sync_logger.info(
                f"[DEVICE-TOKEN-REGENERATED] Worker '{user.username}' regeneró "
                f"Device Token para dispositivo '{device_name}' ({device_id[:30]}...)"
            )
        else:
            # Nuevo dispositivo
            sync_logger.info(
                f"[DEVICE-TOKEN-CREATED] Worker '{user.username}' activó nuevo "
                f"dispositivo '{device_name}' ({device_id[:30]}...)"
            )
        
        # Regenerar el token (se genera automáticamente en el modelo)
        device.regenerate_token()
        
        # Actualizar nombre del dispositivo si cambió
        if device.device_name != device_name:
            device.device_name = device_name
            device.save(update_fields=['device_name'])
        
        # Actualizar last_device_activation en el perfil
        profile.last_device_activation = timezone.now()
        profile.save(update_fields=['last_device_activation'])
        
        return Response({
            "success": True,
            "message": "Device Token regenerado exitosamente" if not created else "Device Token creado exitosamente",
            "device_token": device.device_token,
            "device": {
                "device_id": device.device_id,
                "device_name": device.device_name,
                "activated_at": device.activated_at.isoformat(),
                "is_new": created
            }
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)
        
    except Exception as e:
        sync_logger.error(
            f"[DEVICE-TOKEN-ERROR] Error regenerando Device Token para worker '{user.username}': {str(e)}"
        )
        return Response(
            {
                "success": False,
                "error": f"Error al regenerar Device Token: {str(e)}"
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def validate_device_token(request):
    """
    Valida que un device token sea válido y esté activo.

    Endpoint: POST /api/workers/validate-device/

    Request body:
        {
            "device_token": "unique-device-token-abc123"
        }

    Response:
        {
            "valid": true,
            "worker": {...},
            "device": {...}
        }
    """
    device_token = request.data.get('device_token')

    if not device_token:
        return Response(
            {"valid": False, "error": "Device token requerido"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        device = ActivatedDevice.objects.select_related('worker', 'worker__profile').get(
            device_token=device_token,
            is_active=True
        )

        # Actualizar último uso
        device.update_last_used()

        return Response({
            "valid": True,
            "worker": {
                "id": device.worker.id,
                "username": device.worker.username,
                "full_name": f"{device.worker.first_name} {device.worker.last_name}".strip() or device.worker.username
            },
            "device": {
                "device_name": device.device_name,
                "activated_at": device.activated_at.isoformat(),
                "last_used": device.last_used.isoformat() if device.last_used else None
            }
        })

    except ActivatedDevice.DoesNotExist:
        return Response(
            {"valid": False, "error": "Device token no encontrado o inactivo"},
            status=status.HTTP_404_NOT_FOUND
        )


def serialize_worker(worker, api_key_obj=None):
    """
    Helper para serializar datos del worker.

    Args:
        worker: User object (worker)
        api_key_obj: WorkerAPIKey object (opcional)

    Returns:
        dict: Datos del worker serializados
    """
    return {
        "id": worker.id,
        "username": worker.username,
        "email": worker.email,
        "first_name": worker.first_name,
        "last_name": worker.last_name,
        "role": worker.profile.role if hasattr(worker, 'profile') else 'worker',
        "profile": {
            "full_name": f"{worker.first_name} {worker.last_name}".strip() or worker.username,
            "phone": None,  # No existe campo phone en el modelo actual
            "avatar": None,  # No existe campo avatar en el modelo actual
        },
        "is_active": worker.is_active,
        "api_key": api_key_obj.key_prefix + "..." if api_key_obj else None
    }


# =============================
# ADMIN REGISTRATION
# =============================

class AdminRequestThrottle(AnonRateThrottle):
    """
    Rate limiting para solicitudes de administrador.
    Permite máximo 3 solicitudes por día por IP.
    """
    rate = '3/day'


@api_view(['POST'])
@permission_classes([AllowAny])
def admin_request_view(request):
    """
    Endpoint para solicitud de acceso como administrador.
    
    POST /api/admins/request/
    
    Body:
    {
        "first_name": "Juan",
        "last_name": "Pérez",
        "email": "juan.perez@example.com",
        "phone": "+51 987 654 321",
        "organization_name": "Mi Organización",
        "country": "Perú",
        "region": "Lima"
    }
    
    Responses:
    - 201: Solicitud creada exitosamente
    - 400: Datos inválidos o solicitud pendiente existente
    - 429: Límite de solicitudes excedido (3/día)
    """
    # Aplicar throttling manualmente
    throttle = AdminRequestThrottle()
    if not throttle.allow_request(request, None):
        return Response(
            {
                "error": "Límite de solicitudes excedido",
                "detail": "Solo puedes enviar 3 solicitudes por día. Por favor, intenta más tarde."
            },
            status=status.HTTP_429_TOO_MANY_REQUESTS
        )
    
    # Validar datos con serializer
    serializer = AdminRequestSerializer(data=request.data)
    
    if not serializer.is_valid():
        return Response(
            {
                "error": "Datos inválidos",
                "details": serializer.errors
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Verificar si ya existe una solicitud pendiente (doble verificación)
    email = serializer.validated_data['email']
    existing_pending = AdminRequest.objects.filter(
        email=email,
        status='pending'
    ).exists()
    
    if existing_pending:
        return Response(
            {
                "error": "Solicitud pendiente existente",
                "detail": f"Ya existe una solicitud pendiente para {email}. Por favor, espera la revisión."
            },
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Capturar IP y User-Agent
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
    
    # Crear solicitud
    try:
        admin_request = serializer.save(
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        # Enviar emails
        email_sent_to_applicant = send_request_received_email(admin_request)
        email_sent_to_superadmin = send_superadmin_notification_email(admin_request)
        
        # Log
        logger = logging.getLogger(__name__)
        logger.info(
            f"Nueva solicitud de administrador: {admin_request.email} "
            f"(ID: {admin_request.id}, IP: {ip_address})"
        )
        
        return Response(
            {
                "message": "Solicitud enviada exitosamente",
                "data": {
                    "id": admin_request.id,
                    "first_name": admin_request.first_name,
                    "last_name": admin_request.last_name,
                    "email": admin_request.email,
                    "organization_name": admin_request.organization_name,
                    "status": admin_request.status,
                    "created_at": admin_request.created_at.isoformat(),
                },
                "notifications": {
                    "applicant_email_sent": email_sent_to_applicant,
                    "superadmin_email_sent": email_sent_to_superadmin
                }
            },
            status=status.HTTP_201_CREATED
        )
    
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error creando solicitud de administrador: {e}")

        return Response(
            {
                "error": "Error interno del servidor",
                "detail": "No se pudo procesar tu solicitud. Por favor, intenta más tarde."
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


# ========== SISTEMA DE AUTENTICACIÓN SIMPLE CON API KEY CORTA ==========

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_simple_worker(request):
    """
    Crea un worker con API Key corta en formato AGR-WK-XXXXXX.

    Este endpoint implementa el sistema simplificado de autenticación para workers offline.
    Solo puede ser ejecutado por administradores.

    Request Body:
        {
            "first_name": "Joaquín",
            "last_name": "González",
            "email": "joaquin@agriripeness.com"
        }

    Response 201:
        {
            "id": 123,
            "username": "joaquin.gonzalez",
            "email": "joaquin@agriripeness.com",
            "api_key_short": "AGR-WK-A1B2C3",
            "created_at": "2025-01-13T10:00:00Z"
        }

    Response 403:
        Solo administradores pueden crear workers

    Response 400:
        Errores de validación (email duplicado, campos faltantes, etc.)
    """
    from .utils import generate_short_api_key, generate_unique_username
    from .models import UserProfile

    # Verificar que el usuario sea administrador
    if not hasattr(request.user, 'profile') or request.user.profile.role not in ['admin', 'superadmin']:
        return Response(
            {"error": "Solo administradores pueden crear workers"},
            status=status.HTTP_403_FORBIDDEN
        )

    # Validar datos requeridos
    first_name = request.data.get('first_name', '').strip()
    last_name = request.data.get('last_name', '').strip()
    email = request.data.get('email', '').strip()

    # Validaciones
    errors = {}

    if not first_name:
        errors['first_name'] = ['Este campo es requerido']

    if not last_name:
        errors['last_name'] = ['Este campo es requerido']

    if not email:
        errors['email'] = ['Este campo es requerido']
    elif User.objects.filter(email=email).exists():
        errors['email'] = ['Este email ya está registrado']

    if errors:
        return Response(errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        # Generar username único
        username = generate_unique_username(email=email, first_name=first_name, last_name=last_name)

        # Generar API Key corta única
        api_key = generate_short_api_key()
        max_attempts = 10  # Prevenir loops infinitos
        attempts = 0

        while UserProfile.objects.filter(api_key_short=api_key).exists() and attempts < max_attempts:
            api_key = generate_short_api_key()
            attempts += 1

        if attempts >= max_attempts:
            return Response(
                {"error": "No se pudo generar una API Key única. Intenta de nuevo."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Crear usuario
        user = User.objects.create(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
        )

        # Configurar perfil
        user.profile.role = 'worker'
        user.profile.api_key_short = api_key

        # Si el admin que crea pertenece a una organización, asignar la misma
        if hasattr(request.user, 'profile') and request.user.profile.organization:
            user.profile.organization = request.user.profile.organization

        # Registrar quién creó este worker
        user.profile.created_by = request.user

        user.profile.save()

        logger = logging.getLogger(__name__)
        logger.info(
            f"Worker simple creado | ID: {user.id} | Username: {username} | "
            f"Email: {email} | API Key: {api_key} | Creado por: {request.user.username}"
        )

        return Response(
            {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "api_key_short": user.profile.api_key_short,
                "created_at": user.date_joined.isoformat(),
            },
            status=status.HTTP_201_CREATED
        )

    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.error(f"Error creando worker simple: {e}")

        return Response(
            {"error": "Error al crear worker. Intenta de nuevo."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([AllowAny])
def validate_simple_key(request):
    """
    Valida AMBOS formatos de API Key enviados en el header X-API-Key.

    Este endpoint es público y permite a los workers validar su API Key
    antes de sincronizar datos. Soporta tanto API keys simples (13 chars)
    como API keys complejas (25 chars).

    Headers:
        X-API-Key: AGR-WK-A1B2C3                  (API Key simple - 13 chars)
        X-API-Key: AGR-WORKER-XXXX-XXXX-XXXX     (API Key compleja - 25 chars)

    Response 200 (Key válida):
        {
            "valid": true,
            "worker": {
                "id": 123,
                "username": "joaquin.gonzalez",
                "first_name": "Joaquín",
                "last_name": "González",
                "email": "joaquin@agri.com",
                "is_active": true
            }
        }

    Response 401 (Key inválida):
        {
            "valid": false,
            "error": "API Key inválida o expirada"
        }

    Response 403 (Worker desactivado o no es worker):
        {
            "valid": false,
            "error": "Usuario desactivado. Contacta a tu administrador"
        }
    """
    from .authentication import ApiKeyAuthentication
    from rest_framework import exceptions as drf_exceptions

    # Usar ApiKeyAuthentication para validar ambos formatos
    auth = ApiKeyAuthentication()
    logger = logging.getLogger(__name__)

    try:
        # authenticate() retorna (user, auth_obj) o None
        result = auth.authenticate(request)

        if result is None:
            # No se proporcionó API key
            logger.warning("[VALIDATE-KEY] No API Key provided in request")
            return Response(
                {"valid": False, "error": "API Key no proporcionada"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        user, auth_obj = result

        # Verificar que el usuario tenga perfil de worker
        if not hasattr(user, 'profile'):
            logger.warning(
                f"[VALIDATE-KEY] User {user.id} ({user.username}) no tiene perfil asociado"
            )
            return Response(
                {"valid": False, "error": "Usuario sin perfil configurado"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Verificar que sea worker
        if user.profile.role != 'worker':
            logger.warning(
                f"[VALIDATE-KEY] User {user.id} ({user.username}) no es worker (role: {user.profile.role})"
            )
            return Response(
                {"valid": False, "error": "API Key no pertenece a un worker"},
                status=status.HTTP_403_FORBIDDEN
            )

        # Verificar que esté activo
        if not user.is_active:
            logger.warning(
                f"[VALIDATE-KEY] Worker {user.id} ({user.username}) está inactivo"
            )
            return Response(
                {
                    "valid": False,
                    "error": "Usuario desactivado. Contacta a tu administrador"
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # API Key válida y worker activo
        api_key_preview = request.headers.get('X-API-Key', 'N/A')[:15] + '...'
        logger.info(
            f"[VALIDATE-KEY] API Key validada exitosamente | "
            f"Worker ID: {user.id} | Username: {user.username} | "
            f"API Key: {api_key_preview}"
        )

        return Response(
            {
                "valid": True,
                "worker": {
                    "id": user.id,
                    "username": user.username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "is_active": user.is_active,
                }
            },
            status=status.HTTP_200_OK
        )

    except drf_exceptions.AuthenticationFailed as e:
        # API Key inválida (formato incorrecto o no existe en DB)
        api_key = request.headers.get('X-API-Key', 'N/A')
        api_key_preview = api_key[:15] + '...' if len(api_key) > 15 else api_key

        logger.warning(
            f"[VALIDATE-KEY] Intento de validación con API Key inválida | "
            f"API Key: {api_key_preview} | Error: {str(e)}"
        )

        return Response(
            {"valid": False, "error": str(e)},
            status=status.HTTP_401_UNAUTHORIZED
        )

    except Exception as e:
        # Error inesperado
        logger.error(
            f"[VALIDATE-KEY] Error inesperado durante validación | Error: {str(e)}",
            exc_info=True
        )

        return Response(
            {"valid": False, "error": "Error interno del servidor"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_worker_api_key(request, pk):
    """
    Obtiene la API Key corta de un worker específico.

    Solo puede ser ejecutado por administradores.
    Permite recuperar la API Key de un worker en caso de que la haya olvidado.

    Params:
        pk (int): ID del worker

    Response 200:
        {
            "worker_id": 123,
            "username": "joaquin.gonzalez",
            "api_key_short": "AGR-WK-A1B2C3",
            "created_at": "2025-01-13T10:00:00Z"
        }

    Response 403:
        Solo administradores pueden ver API Keys

    Response 404:
        Worker no encontrado
    """
    from .models import UserProfile

    # Verificar que el usuario sea administrador
    if not hasattr(request.user, 'profile') or request.user.profile.role not in ['admin', 'superadmin']:
        return Response(
            {"detail": "Solo administradores pueden ver API Keys"},
            status=status.HTTP_403_FORBIDDEN
        )

    try:
        # Buscar worker
        worker = User.objects.get(pk=pk)

        # Verificar que tenga API Key configurada
        if not hasattr(worker, 'profile') or not worker.profile.api_key_short:
            return Response(
                {"detail": "Este worker no tiene API Key configurada"},
                status=status.HTTP_404_NOT_FOUND
            )

        logger = logging.getLogger(__name__)
        logger.info(
            f"API Key simple consultada | Worker ID: {worker.id} | "
            f"Consultado por: {request.user.username}"
        )

        return Response(
            {
                "worker_id": worker.id,
                "username": worker.username,
                "first_name": worker.first_name,
                "last_name": worker.last_name,
                "email": worker.email,
                "api_key_short": worker.profile.api_key_short,
                "created_at": worker.date_joined.isoformat(),
            },
            status=status.HTTP_200_OK
        )

    except User.DoesNotExist:
        return Response(
            {"detail": "Worker no encontrado"},
            status=status.HTTP_404_NOT_FOUND
        )