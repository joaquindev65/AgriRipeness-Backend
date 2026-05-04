"""
Migración de datos: Crear organización por defecto y asignar a usuarios existentes.
"""
from django.db import migrations


def create_default_organization(apps, schema_editor):
    """
    Crea una organización por defecto y asigna todos los usuarios existentes a ella.
    """
    Organization = apps.get_model('users', 'Organization')
    UserProfile = apps.get_model('users', 'UserProfile')
    
    # Crear organización por defecto
    org, created = Organization.objects.get_or_create(
        slug='parcela-demo',
        defaults={
            'name': 'Parcela Demo',
            'country': 'Chile',
            'region': 'Región Metropolitana',
            'is_active': True,
        }
    )
    
    if created:
        print(f"Organización '{org.name}' creada exitosamente")
    else:
        print(f"Organización '{org.name}' ya existe")
    
    # Asignar organización a todos los perfiles existentes
    profiles_updated = UserProfile.objects.filter(organization__isnull=True).update(
        organization=org
    )
    
    print(f"{profiles_updated} perfiles asignados a '{org.name}'")


def reverse_migration(apps, schema_editor):
    """
    Revertir: eliminar la organización por defecto.
    """
    Organization = apps.get_model('users', 'Organization')
    Organization.objects.filter(slug='parcela-demo').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0004_add_organization'),
    ]

    operations = [
        migrations.RunPython(create_default_organization, reverse_migration),
    ]
