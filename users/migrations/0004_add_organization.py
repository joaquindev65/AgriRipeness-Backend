"""
Migración: Agregar modelo Organization y campo organization a User.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_remove_unused_fields'),
    ]

    operations = [
        # 1. Crear modelo Organization
        migrations.CreateModel(
            name='Organization',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='Nombre de la Organización')),
                ('slug', models.SlugField(unique=True, verbose_name='Slug')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Fecha de Creación')),
                ('is_active', models.BooleanField(default=True, verbose_name='Activa')),
                ('country', models.CharField(blank=True, max_length=100, verbose_name='País')),
                ('region', models.CharField(blank=True, max_length=100, verbose_name='Región')),
                ('logo', models.ImageField(blank=True, null=True, upload_to='organizations/', verbose_name='Logo')),
            ],
            options={
                'verbose_name': 'Organización',
                'verbose_name_plural': 'Organizaciones',
                'ordering': ['name'],
            },
        ),
        
        # 2. Agregar campo organization a UserProfile (nullable temporalmente)
        migrations.AddField(
            model_name='userprofile',
            name='organization',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='profiles',
                to='users.organization',
                verbose_name='Organización'
            ),
        ),
        
        # 3. Agregar campo created_by a UserProfile
        migrations.AddField(
            model_name='userprofile',
            name='created_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='created_profiles',
                to='auth.user',
                verbose_name='Creado por'
            ),
        ),
    ]
