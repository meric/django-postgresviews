from django.core.management.base import BaseCommand
from django.core.files import File
from django.db import connection

from django.apps import apps

from postgresview.models import ViewBase, MaterializedViewBase



class Command(BaseCommand):
    args = ''
    help = """python manage.py createviews [--force] [--validate]
# Attempt to run the SQL to create the defined postgres views.
# If --force is specified, it drops existing views first.
"""

    def add_arguments(self, parser):
        parser.add_argument('--force',
                            action='store_true',
                            dest='force',
                            default=False,
                            help='Drop views before create.')
        parser.add_argument('--validate',
                            action='store_true',
                            dest='validate',
                            default=False,
                            help='Validate views only.')


    def handle(self, *args, **options):
        validate = options.get('validate', False)
        force = options.get('force', False)
        app_config = apps.get_app_config('postgresview')
        tables = {
            model._meta.db_table: model for model in apps.get_models()
        }

        for model in ViewBase.view_models:
            app_config.validate_view_model(model, tables)

        if validate:
            return

        with connection.cursor() as cursor:
            for model in ViewBase.view_models:
                if force:
                    model._drop_view(cursor)
                model._create_view(cursor)

            for view_model in MaterializedViewBase.materialized_view_models:
                view_model.refresh()

            for from_table, view_models in MaterializedViewBase.refresh_triggers.items():
                cursor.execute(MaterializedViewBase._create_refresh_table_sql(from_table, view_models))
                cursor.execute(MaterializedViewBase._create_constraint_trigger_sql(from_table))
