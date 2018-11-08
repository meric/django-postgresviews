Changelog
=========

0.0.1
-----

* Initial release.


0.0.2
-----

* Fix app naming bug. `postgresview` -> `postgresviews`
* Refactor management commands, expose `create_views` and `drop_views` as functions.
* Create views in order of dependencies.
* Enable using SQLAlchemy queries in the `view(cls)` classmethod. Strings will continue to work as well.
* Add SQLAlchemy and aldjemy as a dependency.
* Set Python 3.7 as the minimum supported Python version.
* Started this changelog.

0.0.3
-----

* Fix view SQL projection to Django model fields mismatch bug.
