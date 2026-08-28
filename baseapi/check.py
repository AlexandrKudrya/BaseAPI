"""Validate a BaseAPI project without starting a server.

    python -m baseapi.check <directory>

Three layers, in order, because each one can only be judged once the previous
one holds:

1. the YAML loads and validates;
2. every hook and transform reference resolves to a real callable;
3. every statement compiles against the real schema.

Step 3 is the reason this command exists. A column that does not exist is
invisible to the config layer and only shows up when someone calls the
endpoint. SQLite's EXPLAIN prepares a statement - resolving tables and
columns - without executing it, so a broken INSERT or DELETE is reported
without touching a row.

For a PostgreSQL project the SQL step is skipped: it would need a live server,
and this command is meant to run anywhere.
"""

import os
import sys

from baseapi import db as db_module
from baseapi import dialect
from baseapi.config import load_app
from baseapi.errors import ConfigError
from baseapi.hooks import resolve_hook

USAGE = "usage: python -m baseapi.check <directory>"

_SQLITE_PREFIX = "sqlite:///"


def check(directory):
    """Return ``(exit_code, report)``. 0 means the project is sound."""
    try:
        config = load_app(directory)
    except ConfigError as exc:
        return 1, "FAILED\n  config: %s" % exc

    problems = []
    problems.extend(_check_hooks(config))

    notes = []
    if config.database_url.startswith(_SQLITE_PREFIX):
        problems.extend(_check_sql(config))
    else:
        notes.append("SQL check skipped: not SQLite, would need a live server")

    if problems:
        body = "\n".join("  %s" % line for line in problems)
        return 1, "FAILED\n%s\n\n%d problem(s)" % (body, len(problems))

    return 0, _report(config, notes)


def _check_hooks(config):
    problems = []
    for endpoint in config.endpoints:
        refs = [check.hook for check in endpoint.checks if check.hook]
        if endpoint.response.transform:
            refs.append(endpoint.response.transform)
        for ref in refs:
            try:
                resolve_hook(ref, base_dir=config.base_dir)
            except ConfigError as exc:
                problems.append("%s: %s" % (endpoint.name, exc))
    return problems


def _check_sql(config):
    try:
        database = db_module.connect(
            config.database_url,
            base_dir=config.base_dir,
            init_sql=config.init_sql,
        )
    except Exception as exc:
        return ["database: %s" % exc]

    problems = []
    try:
        for endpoint in config.endpoints:
            sql = endpoint.query.sql
            # EXPLAIN compiles the statement without running it, so a write
            # is validated without changing anything.
            params = {name: None for name in dialect.param_names(sql)}
            try:
                database.run("EXPLAIN " + sql, params)
            except Exception as exc:
                problems.append("%s: %s" % (endpoint.name, exc))
    finally:
        database.close()
    return problems


def _report(config, notes):
    lines = ["OK  %s" % os.path.abspath(config.base_dir),
             "    database: %s" % config.database_url]
    for note in notes:
        lines.append("    %s" % note)
    lines.append("")

    if not config.endpoints:
        lines.append("    (no endpoints declared)")
    else:
        width_path = max(len(e.path) for e in config.endpoints)
        width_name = max(len(e.name) for e in config.endpoints)
        for endpoint in sorted(config.endpoints,
                               key=lambda e: (e.path, e.method)):
            lines.append("    %-7s %-*s  %-*s  %-4s%s" % (
                endpoint.method,
                width_path, endpoint.path,
                width_name, endpoint.name,
                endpoint.query.returns,
                "  auth" if endpoint.auth == "required" else "",
            ))

    lines.append("")
    lines.append("%d endpoint(s), %d token(s)"
                 % (len(config.endpoints), len(config.tokens)))
    return "\n".join(lines)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    code, report = check(argv[0])
    print(report, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
