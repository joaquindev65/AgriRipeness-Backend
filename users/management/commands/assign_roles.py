"""
Management command para asignar roles a usuarios existentes.
Útil para migrar usuarios que ya existen antes de la implementación del campo 'role'.
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from users.models import UserProfile


class Command(BaseCommand):
    help = 'Asigna roles a usuarios existentes basándose en is_staff y is_superuser'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra qué cambios se harían sin aplicarlos',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        self.stdout.write(self.style.WARNING('\n' + '='*80))
        self.stdout.write(self.style.WARNING('  ASIGNACIÓN DE ROLES A USUARIOS EXISTENTES'))
        self.stdout.write(self.style.WARNING('='*80 + '\n'))

        if dry_run:
            self.stdout.write(self.style.NOTICE('Modo DRY RUN - No se aplicarán cambios\n'))

        # Obtener todos los usuarios
        users = User.objects.all()
        total_users = users.count()

        self.stdout.write(f'Total de usuarios encontrados: {total_users}\n')

        # Contadores
        created_count = 0
        updated_count = 0
        skipped_count = 0

        for user in users:
            # Determinar rol basándose en is_staff y is_superuser
            if user.is_superuser:
                role = 'superadmin'
            elif user.is_staff:
                role = 'admin'
            else:
                role = 'worker'

            # Obtener o crear profile
            profile, created = UserProfile.objects.get_or_create(
                user=user,
                defaults={'role': role}
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  [CREADO] {user.username:20} -> {role:15} (nuevo profile)'
                    )
                )
            else:
                # Si el profile ya existe, verificar si necesita actualización
                if profile.role != role:
                    old_role = profile.role
                    if not dry_run:
                        profile.role = role
                        profile.save()
                    updated_count += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f'  [ACTUALIZADO] {user.username:20} -> {old_role} -> {role}'
                        )
                    )
                else:
                    skipped_count += 1
                    self.stdout.write(
                        f'  [SIN CAMBIOS] {user.username:20} -> {role:15} (ya asignado)'
                    )

        # Resumen
        self.stdout.write('\n' + '='*80)
        self.stdout.write(self.style.SUCCESS('  RESUMEN'))
        self.stdout.write('='*80)
        self.stdout.write(f'\nTotal procesados: {total_users}')
        self.stdout.write(self.style.SUCCESS(f'  - Profiles creados: {created_count}'))
        self.stdout.write(self.style.WARNING(f'  - Roles actualizados: {updated_count}'))
        self.stdout.write(f'  - Sin cambios: {skipped_count}\n')

        # Mostrar distribución de roles
        self.stdout.write('\nDistribución de roles:')
        for role_value, role_name in UserProfile.ROLE_CHOICES:
            count = UserProfile.objects.filter(role=role_value).count()
            self.stdout.write(f'  - {role_name}: {count}')

        if dry_run:
            self.stdout.write(self.style.NOTICE('\nModo DRY RUN - Ningún cambio fue aplicado'))
            self.stdout.write(self.style.NOTICE('Ejecuta sin --dry-run para aplicar los cambios'))
        else:
            self.stdout.write(self.style.SUCCESS('\nAsignación de roles completada exitosamente!'))

        self.stdout.write('='*80 + '\n')
