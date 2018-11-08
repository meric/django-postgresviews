import hashlib

from django.db import models, migrations, connection
from django.db.backends.postgresql import schema
from django.apps import apps
from django.utils.encoding import force_bytes

from django.db.utils import ProgrammingError

from aldjemy.orm import get_session

from sqlalchemy import Table, MetaData
from sqlalchemy_views import CreateView, DropView


class ViewOptions(object):
    from_models = []
    refresh_automatically = True

    def __init__(self, opts):
        if opts:
            for key, value in opts.__dict__.items():
                if key in ['from_models', 'refresh_automatically']:
                    setattr(self, key, value)


class ViewBase(type(models.Model)):
    view_models = []
    operations = []

    def __new__(mcs, name, bases, attrs):
        new = super(ViewBase, mcs).__new__(mcs, name, bases, attrs)

        opts = attrs.pop('ViewMeta', None)
        setattr(new, '_view_meta', ViewOptions(opts))
        new._meta.managed = False
        return new

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self._meta.abstract:
            self._add_view_model()

    def _add_view_model(self):
        if self not in ViewBase.view_models:
            ViewBase.view_models.append(self)

    def _drop_table_sql(self):
        return "DROP TABLE IF EXISTS %s CASCADE" % self._meta.db_table

    def _drop_view_sql(self):
        return "DROP VIEW IF EXISTS %s CASCADE" % self._meta.db_table

    def _create_view_sql(self):
        sql = self.view()

        if isinstance(sql, str):
            return sql

        return CreateView(
            Table(self._meta.db_table, MetaData()),
            self.view().subquery(),
            or_replace=True)

    def _from_tables(self):
        if hasattr(self._view_meta, "from_tables"):
            return self._view_meta.from_tables

        from django.apps import apps
        from_models = self._view_meta.from_models
        from_tables = set()
        for label in from_models:
            if "." in label:
                app_label, model_name = label.split(".")
                model = apps.get_model(app_label=app_label, model_name=model_name)
                if issubclass(model, View):
                    from_tables = from_tables | model._from_tables()
                else:
                    from_tables.add(model._meta.db_table)
            else:
                from_tables.add(label)
        setattr(self._view_meta, "from_tables", from_tables)
        return from_tables

    def _from_view_models(self):
        if hasattr(self._view_meta, "from_view_models"):
            return self._view_meta.from_view_models
        tables = {
            model._meta.db_table: model for model in apps.get_models()
        }
        from_models = self._view_meta.from_models
        from_view_models = set()
        for label in from_models:
            if "." in label:
                app_label, model_name = label.split(".")
                model = apps.get_model(app_label=app_label, model_name=model_name)
                if issubclass(model, View):
                    from_view_models.add(model)
            else:
                model = tables[label]
                if issubclass(model, View):
                    from_view_models.add(model)
        setattr(self._view_meta, "from_view_models", from_view_models)
        return from_view_models

    def _drop_view(self, cursor):
        try:
            cursor.execute(self._drop_view_sql())
        except ProgrammingError:
            cursor.execute(self._drop_table_sql())

    def _create_view(self, cursor, created):
        if self in created:
            return
        created.add(self)
        for view_model in self._from_view_models():
            view_model._create_view(cursor, created)

        sql = self._create_view_sql()

        if isinstance(sql, str):
            cursor.execute(sql)
        else:
            session = get_session()
            session.execute(sql)

        return True


class View(models.Model, metaclass=ViewBase):
    class Meta:
        managed = False
        abstract = True


class MaterializedViewBase(ViewBase):
    refresh_triggers = {}
    materialized_view_models = []

    class IncorrectlyConfigured(Exception):
        pass

    sql_create_unique_index = (
        "CREATE UNIQUE INDEX %(name)s on %(table)s (%(columns)s);")

    def _create_unique_sql(self, columns):
        editor = schema.DatabaseSchemaEditor(connection)
        return self.sql_create_unique_index % {
            "table": editor.quote_name(self._meta.db_table),
            "name": editor.quote_name(
                editor._create_index_name(self, columns, suffix="_uniq")),
            "columns": ", ".join(editor.quote_name(column)
                for column in columns),
        }

    def _drop_materialized_view_sql(self):
        return "DROP MATERIALIZED VIEW IF EXISTS %s CASCADE" % self._meta.db_table

    def _drop_view(self, cursor):
        try:
            cursor.execute(self._drop_materialized_view_sql())
        except ProgrammingError:
            try:
                cursor.execute(self._drop_view_sql())
            except ProgrammingError:
                cursor.execute(self._drop_table_sql())

    def _create_view_sql(self):
        return "CREATE MATERIALIZED VIEW %s AS %s" % (
            self._meta.db_table, self.view())

    @classmethod
    def _add_refresh_for_view(cls, from_table, materialized_view):
        if not materialized_view._view_meta.refresh_automatically:
            raise IncorrectlyConfigured(
                "An automatically refreshed materialized view must have "
                "all its materialized view dependencies automatically "
                "refreshed also.")
        refresh_triggers = MaterializedViewBase.refresh_triggers.setdefault(
            from_table, [])
        if materialized_view not in refresh_triggers:
            refresh_triggers.append(materialized_view)

    @classmethod
    def _add_materialized_view_model(cls, model):
        if model not in MaterializedViewBase.materialized_view_models:
            MaterializedViewBase.materialized_view_models.append(model)

    def _create_view(self, cursor, created):
        if super()._create_view(cursor, created):
            if self._meta.unique_together:
                for unique_together in self._meta.unique_together:
                    columns = [self._meta.get_field(field).column
                        for field in unique_together]
                    cursor.execute(self._create_unique_sql(columns))

            from_models = self._view_meta.from_models

            for label in from_models:
                if "." in label:
                    app_label, model_name = label.split(".")
                    model = apps.get_model(
                        app_label=app_label,
                        model_name=model_name)
                    if issubclass(model, MaterializedView):
                        for from_table in model._from_tables():
                            self._add_materialized_view_model(model)
                            self._add_materialized_view_model(self)
                    else:
                        self._add_materialized_view_model(self)
                else:
                    self._add_materialized_view_model(self)

            if self._view_meta.refresh_automatically:
                # Add list of materialized views to refresh for each table.
                # Keep an ordering such that materialized views used by other
                # materialized views are refreshed first.
                # There is much probably a much more optimal algorithm.
                # If it gets slow as the number of materialized views grow,
                # look here; But for half a dozen materialized views, the slowness
                # should not be noticeable.
                for label in from_models:
                    if "." in label:
                        app_label, model_name = label.split(".")
                        model = apps.get_model(
                            app_label=app_label,
                            model_name=model_name)
                        if issubclass(model, MaterializedView):
                            for from_table in model._from_tables():
                                self._add_refresh_for_view(from_table, model)
                        elif not issubclass(model, View):
                            self._add_refresh_for_view(model._meta.db_table, self)
                    else:
                        self._add_refresh_for_view(label, self)
                for label in from_models:
                    if "." in label:
                        app_label, model_name = label.split(".")
                        model = apps.get_model(
                            app_label=app_label,
                            model_name=model_name)
                        if issubclass(model, MaterializedView):
                            for from_table in model._from_tables():
                                self._add_refresh_for_view(from_table, self)
            return True

    @classmethod
    def _refresh_materialized_view_sql(cls, view_models):
        return "\n".join([
            "REFRESH MATERIALIZED VIEW %s %s;" % (
                    "CONCURRENTLY" if model._meta.unique_together else "",
                    model._meta.db_table) for model in view_models
        ])

    @classmethod
    def _hexdigest(cls, *args):
        h = hashlib.md5()
        if args:
            for a in args:
                h.update(force_bytes(a))
        hexdigest = h.hexdigest()[:8]
        return hexdigest

    @classmethod
    def _create_refresh_table_sql(cls, from_table, view_models):
        return """
DROP TABLE IF EXISTS %(from_table)s_scheduled_refresh_%(hash)s CASCADE;
CREATE UNLOGGED TABLE %(from_table)s_scheduled_refresh_%(hash)s (
    schedule_refresh BOOLEAN
);
CREATE OR REPLACE FUNCTION %(from_table)s_refresh_materialized_views_%(hash)s()
RETURNS TRIGGER LANGUAGE plpgsql
AS $$
BEGIN
    %(sql)s
    DELETE FROM %(from_table)s_scheduled_refresh_%(hash)s;
    RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION schedule_%(from_table)s_refresh_materialized_view_%(hash)s()
RETURNS TRIGGER LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS
        (SELECT * FROM %(from_table)s_scheduled_refresh_%(hash)s LIMIT 1) THEN
        INSERT INTO %(from_table)s_scheduled_refresh_%(hash)s VALUES (true);
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS %(from_table)s_schedule_triggers_refresh_%(hash)s ON %(from_table)s_scheduled_refresh_%(hash)s;
CREATE CONSTRAINT TRIGGER %(from_table)s_schedule_triggers_refresh_%(hash)s
AFTER INSERT ON %(from_table)s_scheduled_refresh_%(hash)s
INITIALLY DEFERRED
FOR EACH ROW EXECUTE PROCEDURE %(from_table)s_refresh_materialized_views_%(hash)s();
""" % {
    'hash': cls._hexdigest(from_table),
    'from_table': from_table,
    'sql': cls._refresh_materialized_view_sql(view_models)
}

    @classmethod
    def _create_constraint_trigger_sql(cls, from_table):
        return """
DROP TRIGGER IF EXISTS %(from_table)s_trigger_schedule_refresh_%(hash)s ON %(from_table)s;
CREATE CONSTRAINT TRIGGER %(from_table)s_trigger_schedule_refresh_%(hash)s
AFTER INSERT OR UPDATE OR DELETE ON %(from_table)s
DEFERRABLE
FOR EACH ROW EXECUTE PROCEDURE
    schedule_%(from_table)s_refresh_materialized_view_%(hash)s();
""" % {
    'from_table': from_table,
    'hash': cls._hexdigest(from_table)
}


class MaterializedView(View, metaclass=MaterializedViewBase):
    class Meta:
        managed = False
        abstract = True

    @classmethod
    def refresh(cls, concurrently=True):
        with connection.cursor() as cursor:
            cursor.execute("REFRESH MATERIALIZED VIEW %s %s" % (
                "CONCURRENTLY" if concurrently else "",
                cls._meta.db_table))
