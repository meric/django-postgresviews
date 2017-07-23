from django.core.management.base import BaseCommand
from django.db import connection

from postgresviews import drop_views


class Command(BaseCommand):
    args = ''
    help = """python manage.py dropviews
# Drop defined postgres views.
"""

    def handle(self, *args, **options):
        drop_views()
