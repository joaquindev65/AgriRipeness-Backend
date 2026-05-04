"""
Servicios para integración con APIs externas
"""
import requests
import json
import hashlib
import base64
import time
from io import BytesIO
from django.conf import settings
from django.core.cache import cache
from typing import Dict, Any
import logging

# Logger para HuggingFace service
sync_logger = logging.getLogger('sync')

# Imports para anotaciones de imagen
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print(f"PIL not available. Install: uv add Pillow")


class HuggingFaceService:
    """Servicio para interactuar con Hugging Face API de detección de limones"""

    API_URL = "https://joaquinnn65-lemon-detection-api.hf.space"
    TIMEOUT = 60  # v2.0: Aumentado de 30s a 60s (HF Space en CPU es lento)
    MAX_RETRIES = 2  # v2.0: Reintentar hasta 2 veces en caso de timeout/error
    
    @classmethod
    def create_professional_annotation(cls, image_file, detections) -> str:
        """
        Crear imagen anotada con bounding boxes profesionales
        
        Args:
            image_file: Archivo de imagen original
            detections: Lista de detecciones con bounding boxes
            
        Returns:
            str: Imagen anotada en formato base64
        """
        if not PIL_AVAILABLE:
            print(f"Cannot create annotations without PIL")
            return ""
        
        try:
            # Resetear puntero del archivo
            image_file.seek(0)
            
            # Abrir imagen original
            image = Image.open(image_file).convert('RGB')
            draw = ImageDraw.Draw(image)
            
            # Estilos profesionales
            box_color = (50, 205, 50)  # Verde lima
            text_color = (255, 255, 255)  # Blanco
            text_bg_color = (0, 0, 0, 200)  # Negro semi-transparente
            
            # Cargar fuente (fallback a default si no está disponible)
            try:
                font = ImageFont.truetype("arial.ttf", 16)
                small_font = ImageFont.truetype("arial.ttf", 12)
            except:
                font = ImageFont.load_default()
                small_font = ImageFont.load_default()
            
            # Procesar cada detección
            for i, detection in enumerate(detections):
                # Extraer bounding box - adaptarse a diferentes formatos
                if 'bbox' in detection:
                    bbox = detection['bbox']  # [x1, y1, x2, y2]
                elif 'box' in detection:
                    bbox = detection['box']
                else:
                    # Formato alternativo con coordenadas separadas
                    bbox = [
                        detection.get('x1', detection.get('left', 0)),
                        detection.get('y1', detection.get('top', 0)),
                        detection.get('x2', detection.get('right', 100)),
                        detection.get('y2', detection.get('bottom', 100))
                    ]
                
                confidence = detection.get('confidence', detection.get('score', 0.5))
                
                # Dibujar bounding box
                draw.rectangle(bbox, outline=box_color, width=3)
                
                # Preparar texto del label
                label = f"Lemon #{i+1}"
                conf_text = f"{confidence:.1%}"
                
                # Calcular posición del texto
                text_x, text_y = bbox[0], max(0, bbox[1] - 35)
                
                # Dibujar fondo del texto
                full_text = f"{label} {conf_text}"
                text_bbox = draw.textbbox((text_x, text_y), full_text, font=font)
                # Expandir un poco el fondo
                padded_bbox = [
                    text_bbox[0] - 3, text_bbox[1] - 2,
                    text_bbox[2] + 3, text_bbox[3] + 2
                ]
                draw.rectangle(padded_bbox, fill=(0, 0, 0, 180))
                
                # Dibujar texto
                draw.text((text_x, text_y), full_text, fill=text_color, font=font)
                
                # Dibujar barra de confianza
                bar_width = 60
                bar_height = 4
                bar_x = bbox[0]
                bar_y = max(0, bbox[1] - 8)
                
                # Barra de fondo
                draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], 
                              fill=(100, 100, 100))
                
                # Barra de confianza
                conf_width = int(bar_width * confidence)
                draw.rectangle([bar_x, bar_y, bar_x + conf_width, bar_y + bar_height], 
                              fill=box_color)
            
            # Agregar información general
            img_width, img_height = image.size
            info_text = f"Detected: {len(detections)} lemons"
            info_x = img_width - 200
            info_y = img_height - 30
            
            # Fondo de la información
            info_bbox = draw.textbbox((info_x, info_y), info_text, font=font)
            padded_info_bbox = [
                info_bbox[0] - 5, info_bbox[1] - 3,
                info_bbox[2] + 5, info_bbox[3] + 3
            ]
            draw.rectangle(padded_info_bbox, fill=(0, 0, 0, 150))
            draw.text((info_x, info_y), info_text, fill=(255, 255, 255), font=font)
            
            # Convertir a base64
            buffer = BytesIO()
            image.save(buffer, format='JPEG', quality=95, optimize=True)
            img_base64 = base64.b64encode(buffer.getvalue()).decode()
            
            print(f"Created annotated image with {len(detections)} bounding boxes")
            return img_base64
            
        except Exception as e:
            print(f"Error creating annotation: {e}")
            return ""
    
    @classmethod
    def detect_lemons(cls, image_file) -> Dict[str, Any]:
        """
        v2.0: Detectar limones usando Hugging Face API con retry logic y caché

        Args:
            image_file: Archivo de imagen (UploadedFile de Django o file-like object)

        Returns:
            Dict con resultado de la detección incluyendo imagen anotada
            {
                'success': bool,
                'total_lemons': int,
                'detections': list,
                'confidence_avg': float,
                'processing_time': float,
                'model_used': str,
                'annotated_image': str (base64),
                'image_dimensions': dict
            }

        Raises:
            En caso de error completo después de retries, retorna dict con success=False
        """
        try:
            # Generar hash de la imagen para caché
            image_content = image_file.read()
            image_hash = hashlib.md5(image_content).hexdigest()
            cache_key = f"lemon_detection_{image_hash}"

            # Buscar en caché primero
            cached_result = cache.get(cache_key)
            if cached_result:
                sync_logger.info(f"✅ [HF-CACHE] Resultado obtenido de caché para hash: {image_hash[:8]}")
                return cached_result

            # Resetear el puntero del archivo después de leer para el hash
            image_file.seek(0)

            # v2.0: Retry logic con exponential backoff
            last_error = None
            for attempt in range(cls.MAX_RETRIES):
                try:
                    sync_logger.info(
                        f"🌐 [HF-API] Llamando Hugging Face API (intento {attempt + 1}/{cls.MAX_RETRIES})..."
                    )

                    # Resetear puntero del archivo en cada intento
                    image_file.seek(0)

                    response = requests.post(
                        f"{cls.API_URL}/detect",  # v2.0: Endpoint correcto es /detect, no /predict
                        files={'file': image_file},
                        timeout=cls.TIMEOUT
                    )

                    sync_logger.info(f"[HF-API] Response Status: {response.status_code}")

                    if response.ok:
                        result = response.json()

                        # v2.0: Procesar respuesta según formato REAL del API
                        # Formato esperado: {"success": true, "detections": [...], "image_dimensions": {"width": 320, "height": 320}, ...}
                        lemon_count = 0
                        confidence_score = 0.0
                        detections = []
                        image_width = 0
                        image_height = 0

                        if isinstance(result, dict):
                            # Extraer detecciones del array
                            detections = result.get('detections', [])

                            # Calcular total de limones desde la longitud del array
                            lemon_count = len(detections)

                            # Calcular promedio de confianza desde las detecciones
                            if detections and len(detections) > 0:
                                confidence_score = sum(d.get('confidence', 0.0) for d in detections) / len(detections)
                            else:
                                confidence_score = 0.0

                            # Extraer dimensiones de imagen del objeto anidado
                            image_dims = result.get('image_dimensions', {})
                            image_width = image_dims.get('width', 0)
                            image_height = image_dims.get('height', 0)

                            sync_logger.info(
                                f"[HF-PARSE] Parsed response: {lemon_count} lemons, "
                                f"avg confidence: {confidence_score:.2f}, "
                                f"dimensions: {image_width}x{image_height}"
                            )
                        elif isinstance(result, list) and len(result) > 0:
                            # Fallback: Si la respuesta es directamente un array de detecciones
                            lemon_count = len(result)
                            detections = result
                            if isinstance(result[0], dict):
                                confidence_score = sum(d.get('confidence', 0.0) for d in result) / len(result)

                        # v2.0: Usar imagen anotada del API si está disponible, sino crear localmente
                        annotated_image = ''
                        if isinstance(result, dict) and result.get('annotated_image'):
                            # HF API ya devuelve imagen anotada en base64
                            annotated_image = result.get('annotated_image', '')
                            sync_logger.info(f"[HF-API] Usando imagen anotada del API (base64: {len(annotated_image)} chars)")
                        else:
                            # Fallback: Crear imagen anotada localmente con bounding boxes
                            sync_logger.info(f"[HF-API] Creando imagen anotada localmente con {len(detections)} detecciones")
                            annotated_image = cls.create_professional_annotation(image_file, detections)

                        processed_result = {
                            'success': True,
                            'total_lemons': lemon_count,
                            'detections': detections,
                            'confidence_avg': confidence_score,
                            'processing_time': result.get('inference_time', 0) if isinstance(result, dict) else 0,
                            'model_used': result.get('model_used', 'huggingface_yolov8') if isinstance(result, dict) else 'huggingface_yolov8',
                            'annotated_image': annotated_image,
                            'image_dimensions': {
                                'width': image_width,
                                'height': image_height,
                            },
                            'raw_response': result
                        }

                        # Guardar en caché por 1 hora
                        cache.set(cache_key, processed_result, 3600)
                        sync_logger.info(f"✅ [HF-SUCCESS] Detección exitosa: {lemon_count} limones encontrados")

                        return processed_result
                    else:
                        error_msg = f'API error: {response.status_code}'
                        sync_logger.warning(f"⚠️ [HF-API] Error {response.status_code} en intento {attempt + 1}")
                        last_error = error_msg

                        # Si es error 5xx, reintentar. Si es 4xx, no reintentar
                        if response.status_code >= 500:
                            if attempt < cls.MAX_RETRIES - 1:
                                wait_time = 2 * (attempt + 1)  # Exponential backoff: 2s, 4s
                                sync_logger.info(f"[HF-RETRY] Esperando {wait_time}s antes de reintentar...")
                                time.sleep(wait_time)
                                continue
                        break

                except requests.Timeout:
                    sync_logger.warning(f"⚠️ [HF-TIMEOUT] Timeout en intento {attempt + 1}/{cls.MAX_RETRIES}")
                    last_error = "Timeout"

                    # Si es el último intento, break
                    if attempt == cls.MAX_RETRIES - 1:
                        sync_logger.error("❌ [HF-FALLBACK-FAILED] Max retries alcanzado. HF Space podría estar dormido.")
                        break

                    # Esperar antes de reintentar (HF Space podría estar despertando)
                    wait_time = 3 * (attempt + 1)  # 3s, 6s
                    sync_logger.info(f"[HF-RETRY] Esperando {wait_time}s antes de reintentar...")
                    time.sleep(wait_time)
                    continue

                except requests.RequestException as e:
                    sync_logger.error(f"❌ [HF-REQUEST-ERROR] Error de request en intento {attempt + 1}: {e}")
                    last_error = str(e)

                    # Si es el último intento, break
                    if attempt == cls.MAX_RETRIES - 1:
                        break

                    # Esperar antes de reintentar
                    time.sleep(2)
                    continue

            # Si todos los retries fallaron, retornar análisis vacío con error
            sync_logger.warning("⚠️ [HF-FALLBACK-LOCAL] Todos los retries fallaron. Retornando análisis vacío.")
            return {
                'success': False,
                'total_lemons': 0,
                'detections': [],
                'confidence_avg': 0.0,
                'processing_time': 0.0,
                'model_used': 'huggingface_yolov8',
                'annotated_image': '',
                'image_dimensions': {'width': 0, 'height': 0},
                'error': last_error or 'Unknown error after retries'
            }

        except json.JSONDecodeError as e:
            error_msg = f'JSON decode error: {str(e)}'
            sync_logger.error(f"❌ [HF-JSON-ERROR] {error_msg}")
            return {'success': False, 'error': error_msg, 'total_lemons': 0}

        except Exception as e:
            error_msg = f'Unexpected error: {str(e)}'
            sync_logger.error(f"❌ [HF-UNEXPECTED-ERROR] {error_msg}")
            return {'success': False, 'error': error_msg, 'total_lemons': 0}

    @classmethod
    def test_connection(cls) -> Dict[str, Any]:
        """
        Probar conexión con la API de Hugging Face
        
        Returns:
            Dict con resultado de la prueba
        """
        try:
            response = requests.get(f"{cls.API_URL}", timeout=10)
            return {
                'success': response.ok,
                'status_code': response.status_code,
                'message': 'API is reachable' if response.ok else f'API returned {response.status_code}'
            }
        except Exception as e:
            return {
                'success': False,
                'status_code': None,
                'message': f'Failed to reach API: {str(e)}'
            }