from django.core.management.base import BaseCommand
from django.core.files import File
from django.db import connection

from django.apps import apps

from postgresview.models import ViewBase, MaterializedViewBase



class Command(BaseCommand):
    args = ''
    help = """python manage.py dropviews
# Drop defined postgres views.
"""

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            for model in ViewBase.view_models:
                model._drop_view(cursor)
