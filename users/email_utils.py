"""
Utilidades para envío de emails relacionados con AdminRequest.
"""
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging

# SendGrid HTTP API (evita bloqueo de puertos SMTP en Railway)
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

logger = logging.getLogger(__name__)


def send_email_sendgrid(to_email, subject, html_content, plain_content):
    """
    Envía email usando SendGrid HTTP API (no SMTP).
    Railway bloquea SMTP, pero HTTP API funciona.
    """
    if not settings.SENDGRID_API_KEY:
        logger.error(f"❌ SENDGRID_API_KEY NO configurada en settings - No se puede enviar email a {to_email}")
        return False
    
    if not SENDGRID_AVAILABLE:
        logger.error(f"❌ SendGrid library NO instalada - No se puede enviar email a {to_email}")
        return False
    
    try:
        logger.info(f"📤 Intentando enviar email a {to_email}: {subject}")
        
        message = Mail(
            from_email=Email(settings.DEFAULT_FROM_EMAIL, "AgriRipeness"),
            to_emails=To(to_email),
            subject=subject,
            plain_text_content=Content("text/plain", plain_content),
            html_content=Content("text/html", html_content)
        )
        
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        response = sg.send(message)
        
        if response.status_code in [200, 201, 202]:
            logger.info(f"✅ Email ENVIADO exitosamente a {to_email} - Status: {response.status_code}")
            return True
        else:
            logger.error(f"❌ SendGrid rechazó el email - Status {response.status_code}: {response.body}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Excepción enviando email a {to_email}: {str(e)}")
        import traceback
        logger.error(f"❌ Traceback: {traceback.format_exc()}")
        return False


def get_client_ip(request):
    """Obtiene la IP del cliente desde el request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def send_request_received_email(admin_request):
    """
    Envía email al solicitante confirmando que su solicitud fue recibida.
    """
    try:
        subject = 'Solicitud Recibida - AgriRipeness'
        
        context = {
            'first_name': admin_request.first_name,
            'organization_name': admin_request.organization_name,
            'email': admin_request.email,
            'created_at': admin_request.created_at.strftime('%d de %B, %Y'),
        }
        
        # Template HTML
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #4CAF50 0%, #8BC34A 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0;">AgriRipeness</h1>
                <h2 style="margin: 10px 0 0 0; font-weight: 300;">Solicitud Recibida</h2>
            </div>
            
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; color: #333;">Hola <strong>{context['first_name']}</strong>,</p>
                
                <p style="font-size: 15px; color: #555; line-height: 1.6;">
                    Hemos recibido tu solicitud de acceso a AgriRipeness.
                </p>
                
                <div style="background: white; border-left: 4px solid #4CAF50; padding: 20px; margin: 20px 0; border-radius: 5px;">
                    <strong style="color: #333;">Datos de tu solicitud:</strong>
                    <ul style="list-style: none; padding: 10px 0 0 0; margin: 0;">
                        <li style="padding: 5px 0; color: #555;">📍 <strong>Organización:</strong> {context['organization_name']}</li>
                        <li style="padding: 5px 0; color: #555;">📧 <strong>Email:</strong> {context['email']}</li>
                        <li style="padding: 5px 0; color: #555;">📅 <strong>Fecha:</strong> {context['created_at']}</li>
                    </ul>
                </div>
                
                <p style="font-size: 15px; color: #555; line-height: 1.6;">
                    Nuestro equipo revisará tu solicitud en las próximas <strong>24-48 horas</strong> 
                    y te contactaremos por este mismo medio.
                </p>
                
                <p style="font-size: 14px; color: #777; margin-top: 30px;">
                    ¡Gracias por tu interés!<br>
                    <strong>Equipo AgriRipeness</strong>
                </p>
            </div>
            
            <div style="text-align: center; padding: 20px; color: #999; font-size: 12px;">
                © 2025 AgriRipeness - Sistema de Análisis de Madurez de Cultivos
            </div>
        </body>
        </html>
        """
        
        # Texto plano (fallback)
        plain_message = f"""
        Hola {context['first_name']},
        
        Hemos recibido tu solicitud de acceso a AgriRipeness.
        
        Datos de tu solicitud:
        - Organización: {context['organization_name']}
        - Email: {context['email']}
        - Fecha: {context['created_at']}
        
        Nuestro equipo revisará tu solicitud en las próximas 24-48 horas 
        y te contactaremos por este mismo medio.
        
        ¡Gracias por tu interés!
        
        Equipo AgriRipeness
        """
        
        # Usar SendGrid HTTP API (SMTP bloqueado en Railway)
        return send_email_sendgrid(
            to_email=admin_request.email,
            subject=subject,
            html_content=html_message,
            plain_content=plain_message
        )
        
    except Exception as e:
        logger.error(f"Error enviando email de confirmación: {e}")
        return False


def send_superadmin_notification_email(admin_request):
    """
    Envía email al superadmin notificando de nueva solicitud.
    """
    try:
        # Obtener email del superadmin
        superadmin_email = settings.SUPERADMIN_EMAIL if hasattr(settings, 'SUPERADMIN_EMAIL') else None
        
        # Fallback: buscar superadmins en BD
        if not superadmin_email or '@' not in superadmin_email:
            from django.contrib.auth.models import User
            superadmins = User.objects.filter(
                is_superuser=True,
                is_active=True
            ).values_list('email', flat=True)
            if superadmins:
                superadmin_email = list(superadmins)[0]
            else:
                logger.warning("No hay email de superadmin configurado")
                return False
        
        subject = '🔔 Nueva Solicitud de Administrador - AgriRipeness'
        
        admin_url = f"{settings.FRONTEND_URL.replace('3000', '8000')}/admin/users/adminrequest/"
        if 'railway' in settings.FRONTEND_URL:
            admin_url = f"https://web-production-d9bec.up.railway.app/admin/users/adminrequest/"
        
        context = {
            'first_name': admin_request.first_name,
            'last_name': admin_request.last_name,
            'email': admin_request.email,
            'phone': admin_request.phone or 'No proporcionado',
            'organization_name': admin_request.organization_name,
            'country': admin_request.country,
            'region': admin_request.region,
            'created_at': admin_request.created_at.strftime('%d de %B, %Y - %H:%M'),
            'admin_url': admin_url,
        }
        
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #FF9800 0%, #FF5722 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0;">🔔 Nueva Solicitud</h1>
                <h2 style="margin: 10px 0 0 0; font-weight: 300;">Administrador - AgriRipeness</h2>
            </div>
            
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; color: #333;">Se ha recibido una nueva solicitud de acceso como administrador.</p>
                
                <div style="background: white; border-left: 4px solid #FF9800; padding: 20px; margin: 20px 0; border-radius: 5px;">
                    <strong style="color: #333; font-size: 16px;">Solicitante:</strong>
                    <ul style="list-style: none; padding: 10px 0 0 0; margin: 0;">
                        <li style="padding: 5px 0; color: #555;">👤 <strong>Nombre:</strong> {context['first_name']} {context['last_name']}</li>
                        <li style="padding: 5px 0; color: #555;">📧 <strong>Email:</strong> {context['email']}</li>
                        <li style="padding: 5px 0; color: #555;">📞 <strong>Teléfono:</strong> {context['phone']}</li>
                    </ul>
                </div>
                
                <div style="background: white; border-left: 4px solid #4CAF50; padding: 20px; margin: 20px 0; border-radius: 5px;">
                    <strong style="color: #333; font-size: 16px;">Organización:</strong>
                    <ul style="list-style: none; padding: 10px 0 0 0; margin: 0;">
                        <li style="padding: 5px 0; color: #555;">🏢 <strong>Nombre:</strong> {context['organization_name']}</li>
                        <li style="padding: 5px 0; color: #555;">🌍 <strong>País:</strong> {context['country']}</li>
                        <li style="padding: 5px 0; color: #555;">📍 <strong>Región:</strong> {context['region']}</li>
                    </ul>
                </div>
                
                <p style="font-size: 14px; color: #777;">
                    📅 <strong>Fecha:</strong> {context['created_at']}
                </p>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{context['admin_url']}" 
                       style="display: inline-block; background: #4CAF50; color: white; padding: 15px 30px; 
                              text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                        Revisar en Django Admin
                    </a>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        Nueva Solicitud de Administrador - AgriRipeness
        
        Se ha recibido una nueva solicitud:
        
        Solicitante:
        - Nombre: {context['first_name']} {context['last_name']}
        - Email: {context['email']}
        - Teléfono: {context['phone']}
        
        Organización:
        - Nombre: {context['organization_name']}
        - País: {context['country']}
        - Región: {context['region']}
        
        Fecha: {context['created_at']}
        
        Revisa la solicitud en Django Admin:
        {context['admin_url']}
        """
        
        # Usar SendGrid HTTP API (SMTP bloqueado en Railway)
        return send_email_sendgrid(
            to_email=superadmin_email,
            subject=subject,
            html_content=html_message,
            plain_content=plain_message
        )
        
    except Exception as e:
        logger.error(f"Error enviando email a superadmin: {e}")
        return False


def send_approval_email(admin_request, username, temp_password):
    """
    Envía email al solicitante notificando aprobación con credenciales.
    """
    import logging
    import traceback
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"📧 INICIANDO send_approval_email para {admin_request.email}")
        subject = '✅ ¡Solicitud Aprobada! - AgriRipeness'
        
        context = {
            'first_name': admin_request.first_name,
            'username': username,
            'temp_password': temp_password,
            'organization_name': admin_request.organization_name,
            'frontend_url': settings.FRONTEND_URL,
        }
        
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #4CAF50 0%, #8BC34A 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0;">🎉 ¡Felicidades!</h1>
                <h2 style="margin: 10px 0 0 0; font-weight: 300;">Tu solicitud ha sido aprobada</h2>
            </div>
            
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; color: #333;">Hola <strong>{context['first_name']}</strong>,</p>
                
                <p style="font-size: 15px; color: #555; line-height: 1.6;">
                    ¡Buenas noticias! Tu solicitud ha sido <strong style="color: #4CAF50;">aprobada</strong>.
                </p>
                
                <div style="background: #4CAF50; color: white; padding: 25px; margin: 25px 0; border-radius: 10px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                    <strong style="font-size: 18px; display: block; margin-bottom: 15px;">🔑 Credenciales de Acceso:</strong>
                    <div style="background: rgba(255,255,255,0.2); padding: 15px; border-radius: 5px; margin: 10px 0;">
                        <div style="margin: 8px 0;"><strong>Usuario:</strong> <span style="font-family: monospace; font-size: 16px;">{context['username']}</span></div>
                        <div style="margin: 8px 0;"><strong>Contraseña temporal:</strong> <span style="font-family: monospace; font-size: 16px;">{context['temp_password']}</span></div>
                    </div>
                </div>
                
                <div style="background: #FFF3CD; border-left: 4px solid #FFC107; padding: 15px; margin: 20px 0; border-radius: 5px;">
                    <strong style="color: #856404;">⚠️ IMPORTANTE:</strong>
                    <p style="color: #856404; margin: 10px 0 0 0;">
                        Debes <strong>cambiar tu contraseña</strong> en el primer inicio de sesión por seguridad.
                    </p>
                </div>
                
                <div style="background: white; border: 2px solid #e0e0e0; padding: 20px; margin: 20px 0; border-radius: 5px;">
                    <strong style="color: #333;">📋 Información de tu cuenta:</strong>
                    <ul style="list-style: none; padding: 10px 0 0 0; margin: 0;">
                        <li style="padding: 5px 0; color: #555;">🏢 <strong>Organización:</strong> {context['organization_name']}</li>
                        <li style="padding: 5px 0; color: #555;">👤 <strong>Rol:</strong> Administrador</li>
                    </ul>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{context['frontend_url']}" 
                       style="display: inline-block; background: #4CAF50; color: white; padding: 15px 40px; 
                              text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                        Acceder a la Aplicación
                    </a>
                </div>
                
                <p style="font-size: 14px; color: #777; margin-top: 30px; text-align: center;">
                    ¡Bienvenido a AgriRipeness!<br>
                    <strong>Equipo AgriRipeness</strong>
                </p>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        ¡Solicitud Aprobada! - AgriRipeness
        
        Hola {context['first_name']},
        
        ¡Buenas noticias! Tu solicitud ha sido aprobada.
        
        Credenciales de Acceso:
        - Usuario: {context['username']}
        - Contraseña temporal: {context['temp_password']}
        
        ⚠️ IMPORTANTE: Debes cambiar tu contraseña en el primer inicio de sesión.
        
        Información de tu cuenta:
        - Organización: {context['organization_name']}
        - Rol: Administrador
        
        Accede a la aplicación en: {context['frontend_url']}
        
        ¡Bienvenido a AgriRipeness!
        
        Equipo AgriRipeness
        """
        
        # Usar SendGrid HTTP API (SMTP bloqueado en Railway)
        logger.info(f"📤 Llamando a send_email_sendgrid para {admin_request.email}")
        result = send_email_sendgrid(
            to_email=admin_request.email,
            subject=subject,
            html_content=html_message,
            plain_content=plain_message
        )
        logger.info(f"📧 send_approval_email resultado: {result}")
        return result
        
    except Exception as e:
        logger.error(f"❌ ERROR CRÍTICO en send_approval_email: {e}")
        logger.error(f"❌ Traceback:\n{traceback.format_exc()}")
        return False


def send_worker_credentials_email(worker_email, first_name, temp_password, api_key):
    """
    Envía email al worker con sus credenciales de acceso.
    Incluye: email (username), password temporal, API key, e instrucciones.
    """
    import logging
    import traceback
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f"📧 INICIANDO send_worker_credentials_email para {worker_email}")
        subject = '🌱 Bienvenido a AgriRipeness - Tus Credenciales de Acceso'
        
        context = {
            'first_name': first_name,
            'email': worker_email,
            'temp_password': temp_password,
            'api_key': api_key,
            'frontend_url': settings.FRONTEND_URL,
        }
        
        html_message = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 0; }}
                .container {{ max-width: 600px; margin: 0 auto; }}
                .header {{ background: linear-gradient(135deg, #4CAF50 0%, #8BC34A 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
                .credentials {{ background: #4CAF50; color: white; padding: 25px; margin: 25px 0; border-radius: 10px; }}
                .credentials-item {{ background: rgba(255,255,255,0.2); padding: 15px; border-radius: 5px; margin: 10px 0; }}
                .api-key {{ background: #f5f5f5; color: #333; padding: 15px; margin: 20px 0; border-radius: 5px; border-left: 4px solid #4CAF50; word-break: break-all; font-family: monospace; }}
                .warning {{ background: #FFF3CD; border-left: 4px solid #FFC107; padding: 15px; margin: 20px 0; border-radius: 5px; }}
                .steps {{ background: white; border: 2px solid #e0e0e0; padding: 20px; margin: 20px 0; border-radius: 5px; }}
                .steps ol {{ padding-left: 20px; }}
                .steps li {{ padding: 5px 0; color: #555; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🌱 Bienvenido a AgriRipeness</h1>
                    <p style="margin: 10px 0 0 0; font-size: 16px;">Tu cuenta de trabajador ha sido creada</p>
                </div>
                
                <div class="content">
                    <p style="font-size: 16px; color: #333;">Hola <strong>{context['first_name']}</strong>,</p>
                    
                    <p style="font-size: 15px; color: #555; line-height: 1.6;">
                        Tu administrador ha creado una cuenta para ti en AgriRipeness. A continuación encontrarás tus credenciales de acceso.
                    </p>
                    
                    <div class="credentials">
                        <strong style="font-size: 18px; display: block; margin-bottom: 15px;">🔑 CREDENCIALES DE ACCESO</strong>
                        <div class="credentials-item">
                            <div style="margin: 8px 0;"><strong>Email:</strong> <span style="font-family: monospace; font-size: 16px;">{context['email']}</span></div>
                        </div>
                        <div class="credentials-item">
                            <div style="margin: 8px 0;"><strong>Contraseña temporal:</strong> <span style="font-family: monospace; font-size: 16px;">{context['temp_password']}</span></div>
                        </div>
                    </div>
                    
                    <div class="warning">
                        <strong style="color: #856404;">⚠️ IMPORTANTE:</strong>
                        <p style="color: #856404; margin: 10px 0 0 0;">
                            Debes <strong>cambiar tu contraseña</strong> en el primer inicio de sesión por seguridad.
                        </p>
                    </div>
                    
                    <div class="steps">
                        <strong style="color: #333; font-size: 16px;">📱 INSTRUCCIONES DE PRIMER ACCESO:</strong>
                        <ol style="list-style: decimal; padding-left: 20px; margin: 15px 0 0 0;">
                            <li>Descarga la app <strong>AgriRipeness</strong> en tu dispositivo móvil</li>
                            <li>Inicia sesión con tu <strong>email</strong> y <strong>contraseña temporal</strong></li>
                            <li>Deberás <strong>cambiar tu contraseña</strong> (obligatorio)</li>
                            <li>Configura tu <strong>PIN personal</strong> de 4-6 dígitos</li>
                            <li>¡Listo! Podrás ingresar solo con tu <strong>PIN</strong> en próximos accesos</li>
                        </ol>
                    </div>
                    
                    <div class="api-key">
                        <strong style="display: block; margin-bottom: 10px; color: #333;">🔑 API KEY (para análisis sin conexión):</strong>
                        <code style="font-size: 13px; word-break: break-all;">{context['api_key']}</code>
                        <p style="margin: 10px 0 0 0; font-size: 13px; color: #666;">
                            Usa esta clave si necesitas realizar análisis de frutos sin conexión a internet. 
                            Podrás encontrarla también en tu perfil dentro de la aplicación.
                        </p>
                    </div>
                    
                    <div style="text-align: center; margin: 30px 0;">
                        <p style="font-size: 14px; color: #666;">
                            <strong>🔒 Seguridad:</strong> No compartas estas credenciales con nadie.
                        </p>
                    </div>
                    
                    <p style="font-size: 14px; color: #777; margin-top: 30px; text-align: center;">
                        Si tienes problemas para acceder, contacta a tu administrador.<br><br>
                        <strong>Equipo AgriRipeness</strong>
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        Bienvenido a AgriRipeness - Tus Credenciales de Acceso
        
        Hola {context['first_name']},
        
        Tu cuenta de trabajador ha sido creada exitosamente.
        
        CREDENCIALES DE ACCESO:
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        Email: {context['email']}
        Contraseña temporal: {context['temp_password']}
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        ⚠️ IMPORTANTE: Debes cambiar tu contraseña en el primer inicio de sesión.
        
        INSTRUCCIONES DE PRIMER ACCESO:
        1. Descarga la app AgriRipeness
        2. Inicia sesión con tu email y contraseña temporal
        3. Deberás cambiar tu contraseña (obligatorio)
        4. Configura tu PIN personal de 4-6 dígitos
        5. ¡Listo! Podrás ingresar solo con tu PIN
        
        API KEY (para análisis sin conexión):
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        {context['api_key']}
        ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
        
        Usa esta clave si necesitas realizar análisis sin internet.
        
        🔒 SEGURIDAD: No compartas estas credenciales con nadie.
        
        Si tienes problemas, contacta a tu administrador.
        
        Saludos,
        Equipo AgriRipeness
        """
        
        # Usar SendGrid HTTP API
        logger.info(f"📤 Llamando a send_email_sendgrid para {worker_email}")
        result = send_email_sendgrid(
            to_email=worker_email,
            subject=subject,
            html_content=html_message,
            plain_content=plain_message
        )
        logger.info(f"📧 send_worker_credentials_email resultado: {result}")
        return result
        
    except Exception as e:
        logger.error(f"❌ ERROR CRÍTICO en send_worker_credentials_email: {e}")
        logger.error(f"❌ Traceback:\n{traceback.format_exc()}")
        return False


def send_rejection_email(admin_request):
    """
    Envía email al solicitante notificando rechazo.
    """
    try:
        subject = 'Solicitud Revisada - AgriRipeness'
        
        context = {
            'first_name': admin_request.first_name,
            'rejection_reason': admin_request.rejection_reason or 'No se proporcionó una razón específica.',
        }
        
        html_message = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(135deg, #757575 0%, #616161 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0;">
                <h1 style="margin: 0;">AgriRipeness</h1>
                <h2 style="margin: 10px 0 0 0; font-weight: 300;">Solicitud Revisada</h2>
            </div>
            
            <div style="background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px;">
                <p style="font-size: 16px; color: #333;">Hola <strong>{context['first_name']}</strong>,</p>
                
                <p style="font-size: 15px; color: #555; line-height: 1.6;">
                    Hemos revisado tu solicitud de acceso a AgriRipeness.
                </p>
                
                <div style="background: white; border-left: 4px solid #757575; padding: 20px; margin: 20px 0; border-radius: 5px;">
                    <strong style="color: #333;">Razón:</strong>
                    <p style="color: #555; margin: 10px 0 0 0; line-height: 1.6;">
                        {context['rejection_reason']}
                    </p>
                </div>
                
                <p style="font-size: 15px; color: #555; line-height: 1.6;">
                    Si tienes preguntas o deseas más información, responde a este email 
                    y estaremos encantados de ayudarte.
                </p>
                
                <p style="font-size: 14px; color: #777; margin-top: 30px;">
                    Saludos,<br>
                    <strong>Equipo AgriRipeness</strong>
                </p>
            </div>
        </body>
        </html>
        """
        
        plain_message = f"""
        Solicitud Revisada - AgriRipeness
        
        Hola {context['first_name']},
        
        Hemos revisado tu solicitud de acceso a AgriRipeness.
        
        Razón:
        {context['rejection_reason']}
        
        Si tienes preguntas o deseas más información, responde a este email 
        y estaremos encantados de ayudarte.
        
        Saludos,
        Equipo AgriRipeness
        """
        
        # Usar SendGrid HTTP API (SMTP bloqueado en Railway)
        return send_email_sendgrid(
            to_email=admin_request.email,
            subject=subject,
            html_content=html_message,
            plain_content=plain_message
        )
        
    except Exception as e:
        logger.error(f"Error enviando email de rechazo: {e}")
        return False
