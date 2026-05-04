from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django.conf import settings
import os

class Command(BaseCommand):
    help = 'Diagnostica y prueba la configuración de email'

    def handle(self, *args, **options):
        self.stdout.write("🔍 DIAGNÓSTICO DE EMAIL")
        self.stdout.write("=" * 50)
        
        # Verificar configuración actual
        self.stdout.write(f"\n⚙️  Configuración actual:")
        self.stdout.write(f"   DEBUG: {settings.DEBUG}")
        self.stdout.write(f"   EMAIL_BACKEND: {settings.EMAIL_BACKEND}")
        self.stdout.write(f"   EMAIL_HOST: {settings.EMAIL_HOST}")
        self.stdout.write(f"   EMAIL_PORT: {settings.EMAIL_PORT}")
        self.stdout.write(f"   EMAIL_USE_TLS: {settings.EMAIL_USE_TLS}")
        self.stdout.write(f"   EMAIL_HOST_USER: {settings.EMAIL_HOST_USER or 'No configurado'}")
        self.stdout.write(f"   EMAIL_HOST_PASSWORD: {'***Configurado***' if settings.EMAIL_HOST_PASSWORD else 'No configurado'}")
        self.stdout.write(f"   DEFAULT_FROM_EMAIL: {settings.DEFAULT_FROM_EMAIL}")
        
        # Verificar variables de entorno
        self.stdout.write(f"\n📧 Variables de entorno (.env):")
        env_vars = [
            'EMAIL_BACKEND',
            'EMAIL_HOST_USER', 
            'EMAIL_HOST_PASSWORD',
            'DEFAULT_FROM_EMAIL'
        ]
        
        for var in env_vars:
            value = os.environ.get(var)
            if var == 'EMAIL_HOST_PASSWORD' and value:
                self.stdout.write(f"   {var}: ***Configurado***")
            else:
                self.stdout.write(f"   {var}: {value or 'No configurado'}")
        
        # Estado actual
        self.stdout.write(f"\n📝 Estado:")
        if settings.EMAIL_BACKEND == 'django.core.mail.backends.console.EmailBackend':
            self.stdout.write("   ⚠️  MODO DESARROLLO: Los emails se muestran solo en consola")
            self.stdout.write("   📧 Para enviar emails reales, necesitas configurar Gmail")
        elif not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            self.stdout.write("   ❌ SMTP configurado pero faltan credenciales")
        else:
            self.stdout.write("   ✅ Configurado para enviar emails por SMTP")
            
            # Probar envío de email
            if input("\n¿Quieres enviar un email de prueba? (s/N): ").lower() == 's':
                email_destino = input("Ingresa el email de destino: ")
                if email_destino:
                    try:
                        send_mail(
                            'Prueba de Email - AgriRipeness',
                            'Este es un email de prueba desde tu aplicación Django.',
                            settings.DEFAULT_FROM_EMAIL,
                            [email_destino],
                            fail_silently=False,
                        )
                        self.stdout.write("✅ Email enviado correctamente!")
                    except Exception as e:
                        self.stdout.write(f"❌ Error al enviar email: {e}")
        
        # Instrucciones de configuración
        self.stdout.write(f"\n🔧 Para configurar Gmail:")
        self.stdout.write("   1. Ve a https://myaccount.google.com/security")
        self.stdout.write("   2. Habilita verificación en 2 pasos")
        self.stdout.write("   3. Ve a 'App passwords' y crea una nueva")
        self.stdout.write("   4. Agrega estas líneas a tu archivo .env:")
        self.stdout.write("")
        self.stdout.write("      # Configuración de Email")
        self.stdout.write("      EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend")
        self.stdout.write("      EMAIL_HOST_USER=tu-email@gmail.com")
        self.stdout.write("      EMAIL_HOST_PASSWORD=tu-contraseña-de-aplicacion")
        self.stdout.write("      DEFAULT_FROM_EMAIL=tu-email@gmail.com")
        self.stdout.write("")
        self.stdout.write("   5. Reinicia el servidor Django")