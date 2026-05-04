# Generated manually

from django.db import migrations


class Migration(migrations.Migration):
    """
    Modifica el constraint de email único para permitir emails vacíos.
    Solo emails no vacíos deben ser únicos.
    """

    dependencies = [
        ('users', '0011_remove_cuartel_hilera'),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Eliminar el índice anterior
                "DROP INDEX IF EXISTS auth_user_email_unique;",
                # Crear índice parcial que solo aplica a emails no vacíos
                """
                CREATE UNIQUE INDEX auth_user_email_unique
                ON auth_user (email)
                WHERE email != '';
                """,
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS auth_user_email_unique;",
                """
                CREATE UNIQUE INDEX auth_user_email_unique
                ON auth_user (email);
                """,
            ],
        ),
    ]
