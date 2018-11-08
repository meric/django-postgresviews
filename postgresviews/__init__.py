import re
import logging

from django.apps import AppConfig
from django.db.models.signals import pre_migrate, post_migrate
from django.db import connection

default_app_config = 'postgresviews.ViewConfig'

logger = logging.getLogger('postgresviews')


class ViewConfig(AppConfig):
    name = 'postgresviews'
    verbose_name = 'postgresviews'

    def ready(self):
        from .models import ViewBase, MaterializedViewBase
        from django.apps import apps

        tables = {
            model._meta.db_table: model for model in apps.get_models()
        }

        for model in ViewBase.view_models:
            self.validate_view_model(model, tables)

    def validate_view_model(self, view_model, tables):
        create_view_sql = view_model.view()
        from_models = view_model._view_meta.from_models

        missing = []

        for table, model in tables.items():
            if (re.search(table + "[^_a-zA-Z0-9]", str(create_view_sql))
                    and table != view_model._meta.db_table):
                _meta = model._meta
                if (_meta.label not in from_models
                        and _meta.db_table not in from_models):
                    missing.append(model)

        if missing:
            labels = [model._meta.label for model in missing]
            logger.warning(("%s.ViewMeta.from_models might be missing the following models: %s. "
                "The correct from_models definition might be:"
                "\n    from_models = %s") % (
                view_model._meta.label,
                ", ".join(labels),
                str(list(sorted(from_models + labels)))))


def create_views():
    from .models import ViewBase, MaterializedViewBase, View
    from django.apps import apps


    with connection.cursor() as cursor:
        created = set()
        for model in ViewBase.view_models:
            model._create_view(cursor, created)

        for view_model in MaterializedViewBase.materialized_view_models:
            view_model.refresh()

        for from_table, view_models in MaterializedViewBase.refresh_triggers.items():
            cursor.execute(MaterializedViewBase._create_refresh_table_sql(from_table, view_models))
            cursor.execute(MaterializedViewBase._create_constraint_trigger_sql(from_table))


def drop_views():
    from .models import ViewBase

    with connection.cursor() as cursor:
        for model in ViewBase.view_models:
            model._drop_view(cursor)
