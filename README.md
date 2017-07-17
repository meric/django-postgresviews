# Postgres SQL Views for Django

* [PostgreSQL View](https://www.postgresql.org/docs/9.4/static/sql-createview.html)
* [PostgreSQL Materialized View](https://www.postgresql.org/docs/9.4/static/sql-creatematerializedview.html)

## Requirements

* Python 3
* Django 1.11

## Installation

`pip install -e "git+git@github.com:meric/django-postgresviews.git#egg=postgresviews"`

Add to `INSTALLED_APPS` in settings.py:

```
INSTALLED_APPS = (
  # ...
  'postgresviews',
)
```

## Usage

### Normal View

1. Extend the model with `postgresviews.View` class.
2. Define a class method with signature `view(cls)` which returns the SQL for
   the view.
3. The column names selected by the SQL should match the corresponding
   django field.
3. Create a `ViewMeta` class, with a `from_models` attribute, which lists the
   models the view selects from. You can enter the `model._meta.db_table`
   instead of the model label. Add any PostgreSQL table names the view selects
   from, even if they do not map to an existing Django model.
4. Run `python manage.py createviews --force` to install the view everytime you
   change it.
5. At any time you can run `python manage.py createviews --validate` to list
   any models missing from `from_models`.

#### Example

The following view unions default data with user data into a single view.

```
from postgresview.models import View

class Split(View):
    id = models.UUIDField(default=uuid.uuid4, primary_key=True)
    code = models.CharField(max_length=12, db_index=True)
    from_units = models.FloatField()
    to_units = models.FloatField(db_index=True)
    split_date = models.DateField(db_index=True)
    exchange = models.CharField(max_length=16, db_index=True)
    user = models.ForeignKey('User', related_name='%(class)ss')
    split_file = models.ForeignKey('UserSplitFile',
        related_name='%(class)ss')
    created = ext.CreationDateTimeField()
    modified = ext.ModificationDateTimeField()

    class ViewMeta:
        from_models = ['cgt.DefaultSplit', 'cgt.User', 'cgt.UserSplit']

    class Meta:
        ordering = ['exchange', 'split_date', 'code']

    @classmethod
    def view(cls):
        return """
SELECT
    cgt_split.*
FROM (
    SELECT
        "cgt_usersplit".*
    FROM cgt_usersplit
    UNION
    SELECT
        "cgt_defaultsplit".*,
        cgt_user.id as user_id,
        NULL as split_file_id
    FROM cgt_defaultsplit, cgt_user
    LEFT OUTER JOIN cgt_usersplit ON
        cgt_usersplit.exchange = exchange AND
        cgt_usersplit.split_date = split_date AND
        cgt_usersplit.code = code
    WHERE
        cgt_usersplit.id IS NULL
) as cgt_split
"""
```

If the `ViewMeta.from_models` is missing, a warning message will be logged when
django starts, but if you really know what you are doing, postgresviews will
continue to operate:

```
cgt.Split.ViewMeta.from_models might be missing the following models: cgt.UserSplit, cgt.User, cgt.DefaultSplit. The correct from_models definition might be:
    from_models = ['cgt.DefaultSplit', 'cgt.User', 'cgt.UserSplit']
```

### Materialized View

A PostgreSQL Materialized view is a view whose results are cached in a table
managed by postgres, and the table only updates when
[`REFRESH MATERIALIZED VIEW [ CONCURRENTLY ] name`](https://www.postgresql.org/docs/9.4/static/sql-refreshmaterializedview.html) is called.

django-postgresviews allows you to implement models that are backed by
materialized views. In addition, you can configure django-postgresviews to
automatically create the PostgreSQL triggers to update the materialized view
whenever an INSERT, UPDATE, or DELETE is performed on the table. The refresh
is NOT performed on each row inserted, updated, or deleted, but only at the end
of a transaction involving one of these operations.

1. Extend the model with `postgresviews.MaterializedView` class.
2. Define a class method with signature `view(cls)` which returns the SQL for
   the view.
4. The column names selected by the SQL should match the corresponding
   django field.
5. Create a `ViewMeta` class, with a `from_models` attribute, which lists the
   models the view selects from. You can enter the `model._meta.db_table`
   instead of the model label. Add any PostgreSQL table names the view selects
   from, even if they do not map to an existing Django model.
6. Set `ViewMeta.refresh_automatically` to `True` or `False`, depending on
   whether you want django-postgresviews to update the materialized view
   automatically. (Default: `True`) If `ViewMeta.refresh_automatically` is
   `True`, then all materialized views it selects from must have their
   `ViewMeta.refresh_automatically` set to `True` also. django-postgresviews
   will take care to refresh materialized views in the correct ordering.
7. A PostgreSQL materialized view, when being refreshed, locks the table to
   prevent reads until the view is refreshed completely. To avoid this,
   `REFRESH MATERIALIZED VIEW CONCURRENTLY` can be run instead. However, this
   requires the view to have a unique index. You can specify the unique index
   using [Meta.unique_together](https://docs.djangoproject.com/en/1.11/ref/models/options/#unique-together)
   as normal. The automatic refresh will then be done concurrently.
8. At any time you can perform a manual refresh of a materialized view by
   calling `view_model.refresh(concurrently=True)`. Note that if you try to
   refresh a materialized view concurrently with a unique_together, PostgreSQL
   will raise an exception.
9. Run `python manage.py createviews --force` to install the view everytime you
   change it.
10. At any time you can run `python manage.py createviews --validate` to list
   any models missing from `from_models`.

The `MaterializedView` class uses `from_models` to determine what underlying
tables to create triggers for.

#### Example

There is a table of stock code changes that list the list of stock code changes
for the an exchange. A company can change their symbols multiple times, so a
view was created to apply code changes on code changes, when the to_code of the
former matches the from_code of the latter. This following materialized view
uses recursive queries to achieve this.

```
from postgresview.models import MaterializedView

class AggregateCodeChange(MaterializedView, AbstractUserCodeChange):
    class ViewMeta:
        from_models = [
            'cgt.CodeChange'
        ]
        refresh_automatically = True

    class Meta:
        ordering = ['exchange', 'change_date', 'from_code', 'to_code']
        unique_together = [(
            'user',
            'change_date',
            'exchange',
            'from_code',
            'to_code'
        )]

    @classmethod
    def view(cls):
        return """
WITH RECURSIVE cgt_aggregatecodechange(
    id,
    change_date,
    from_code,
    to_code,
    exchange,
    created,
    modified,
    user_id,
    code_change_file_id) AS (
SELECT a.* FROM cgt_codechange a
UNION ALL
SELECT
    b.id,
    b.change_date,
    a.from_code,
    b.to_code,
    a.exchange,
    b.created,
    b.modified,
    a.user_id,
    b.code_change_file_id
FROM cgt_aggregatecodechange a, cgt_codechange b
WHERE
    a.user_id = b.user_id AND
    a.to_code = b.from_code AND
    a.exchange = b.exchange AND
    a.change_date <= b.change_date
)
SELECT * FROM cgt_aggregatecodechange
"""
```

There are two underlying tables, `cgt_usercodechange`, and
`cgt_defaultcodechange` (`cgt_codechange` is itself a view that depends on
these two tables). When `python manage.py createviews --force` is run, the
following SQL is generated:

##### Triggers for `cgt_usercodechange` table

```
DROP TABLE IF EXISTS cgt_usercodechange_scheduled_refresh_8d9d76a8 CASCADE;
CREATE UNLOGGED TABLE cgt_usercodechange_scheduled_refresh_8d9d76a8 (
    schedule_refresh BOOLEAN
);
CREATE OR REPLACE FUNCTION cgt_usercodechange_refresh_materialized_views_8d9d76a8()
RETURNS TRIGGER LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_aggregatecodechange;
REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_aggregatesplit;
REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_adjustedcapitalgainrecord;
REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_purchaserecordgroup;
    DELETE FROM cgt_usercodechange_scheduled_refresh_8d9d76a8;
    RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION schedule_cgt_usercodechange_refresh_materialized_view_8d9d76a8()
RETURNS TRIGGER LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS
        (SELECT * FROM cgt_usercodechange_scheduled_refresh_8d9d76a8 LIMIT 1) THEN
        INSERT INTO cgt_usercodechange_scheduled_refresh_8d9d76a8 VALUES (true);
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS cgt_usercodechange_schedule_triggers_refresh_8d9d76a8 ON cgt_usercodechange_scheduled_refresh_8d9d76a8;
CREATE CONSTRAINT TRIGGER cgt_usercodechange_schedule_triggers_refresh_8d9d76a8
AFTER INSERT ON cgt_usercodechange_scheduled_refresh_8d9d76a8
INITIALLY DEFERRED
FOR EACH ROW EXECUTE PROCEDURE cgt_usercodechange_refresh_materialized_views_8d9d76a8();


DROP TRIGGER IF EXISTS cgt_usercodechange_trigger_schedule_refresh_8d9d76a8 ON cgt_usercodechange;
CREATE CONSTRAINT TRIGGER cgt_usercodechange_trigger_schedule_refresh_8d9d76a8
AFTER INSERT OR UPDATE OR DELETE ON cgt_usercodechange
DEFERRABLE
FOR EACH ROW EXECUTE PROCEDURE
    schedule_cgt_usercodechange_refresh_materialized_view_8d9d76a8();
```

##### Triggers for `cgt_defaultcodechange` table

```
DROP TABLE IF EXISTS cgt_defaultcodechange_scheduled_refresh_b2c41476 CASCADE;
CREATE UNLOGGED TABLE cgt_defaultcodechange_scheduled_refresh_b2c41476 (
    schedule_refresh BOOLEAN
);
CREATE OR REPLACE FUNCTION cgt_defaultcodechange_refresh_materialized_views_b2c41476()
RETURNS TRIGGER LANGUAGE plpgsql
AS $$
BEGIN
    REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_aggregatecodechange;
REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_aggregatesplit;
REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_adjustedcapitalgainrecord;
REFRESH MATERIALIZED VIEW CONCURRENTLY cgt_purchaserecordgroup;
    DELETE FROM cgt_defaultcodechange_scheduled_refresh_b2c41476;
    RETURN NULL;
END $$;
CREATE OR REPLACE FUNCTION schedule_cgt_defaultcodechange_refresh_materialized_view_b2c41476()
RETURNS TRIGGER LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS
        (SELECT * FROM cgt_defaultcodechange_scheduled_refresh_b2c41476 LIMIT 1) THEN
        INSERT INTO cgt_defaultcodechange_scheduled_refresh_b2c41476 VALUES (true);
    END IF;
    RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS cgt_defaultcodechange_schedule_triggers_refresh_b2c41476 ON cgt_defaultcodechange_scheduled_refresh_b2c41476;
CREATE CONSTRAINT TRIGGER cgt_defaultcodechange_schedule_triggers_refresh_b2c41476
AFTER INSERT ON cgt_defaultcodechange_scheduled_refresh_b2c41476
INITIALLY DEFERRED
FOR EACH ROW EXECUTE PROCEDURE cgt_defaultcodechange_refresh_materialized_views_b2c41476();


DROP TRIGGER IF EXISTS cgt_defaultcodechange_trigger_schedule_refresh_b2c41476 ON cgt_defaultcodechange;
CREATE CONSTRAINT TRIGGER cgt_defaultcodechange_trigger_schedule_refresh_b2c41476
AFTER INSERT OR UPDATE OR DELETE ON cgt_defaultcodechange
DEFERRABLE
FOR EACH ROW EXECUTE PROCEDURE
    schedule_cgt_defaultcodechange_refresh_materialized_view_b2c41476();
```

You may or may not have noticed in the above SQL, the refresh function
generated is also shared between other materialized views depending on that
table.

The refresh is executed once, no matter how many rows were affected. It uses
a technique described [here](https://www.postgresql.org/message-id/CADbMkNNagpOQ6fLHcABt4j9xG0u6-4GL2zrqVntspvZGGMKZkA%40mail.gmail.com).

## See also

This library is alpha software. You might want to look at [mypebble/django-pgviews](https://github.com/mypebble/django-pgviews).
