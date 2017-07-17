import re
import logging

from django.apps import AppConfig
from django.db.models.signals import pre_migrate, post_migrate

default_app_config = 'postgresview.ViewConfig'

logger = logging.getLogger('postgresview')

class ViewConfig(AppConfig):
    name = 'postgresview'
    verbose_name = 'postgresview'

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
            if (re.search(table + "[^_a-zA-Z0-9]", create_view_sql)
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
