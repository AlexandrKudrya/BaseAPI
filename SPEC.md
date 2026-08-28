# BaseAPI — declarative YAML APIs

## Product

A small framework that turns YAML files into working HTTP endpoints. One file
describes one endpoint, end to end:

```
HTTP request -> parameter coercion -> business checks -> SQL query
             -> response mapping   -> JSON response
```

The author of an API writes YAML, not Python. Python appears only as optional
hooks for logic that an expression cannot express.

## Users and context

One developer starting a small project who needs a CRUD-ish JSON API over an
existing database and does not want to hand-write a route, a validator, a query
and a serializer for every endpoint. They read the YAML file six months later
and must understand the whole endpoint without opening any Python.

## Layout of a user's API project

```
app.yml              database, auth tokens
endpoints/*.yml      one file per endpoint
hooks.py             optional, referenced from YAML as "hooks:function_name"
schema.sql           optional, run at connect time
```

`app.yml` exists because two things do not belong in a per-endpoint file: the
database connection and the auth token table. Everything else stays local to
the endpoint on purpose — no shared fragments, no includes, no inheritance.

## app.yml format

```yaml
database:
  url: "sqlite:///notes.db"        # or "postgresql://user:pass@host:5432/db"
  init_sql: "schema.sql"           # optional, executed on connect

auth:
  tokens:
    - token: "dev-token"           # literal value
      subject: "alice"
      roles: ["admin"]
    - token_env: "SERVICE_TOKEN"   # read from this environment variable
      subject: "service"
      roles: ["service"]
```

`database.url` is required. `database.init_sql` and the whole `auth` section
are optional; `auth.tokens` defaults to an empty list. A relative `sqlite` path
and `init_sql` resolve relative to the directory that contains `app.yml`.

## Endpoint format

```yaml
name: get_note                     # required, unique across the project
method: GET                        # required: GET|POST|PUT|PATCH|DELETE
path: /notes/{note_id}             # required, unique together with method
summary: "Return one note by id."  # optional, documentation only
auth: required                     # required|none, default none

params:
  note_id: { in: path,  type: int,  required: true }
  verbose: { in: query, type: bool, required: false, default: false }
  subject: { in: auth,  type: str,  required: false }

checks:
  - when: "params.note_id > 0"     # must evaluate truthy to pass
    status: 400
    message: "note_id must be positive"
  - hook: "hooks:can_read"         # Python predicate, must return truthy
    status: 403
    message: "forbidden"

query:
  sql: "SELECT id, title, body FROM notes WHERE id = :note_id"
  returns: one                     # one|many|none

response:
  status: 200                      # default 200
  when_empty: 404                  # returns:one only, default 404
  transform: "hooks:decorate"      # optional Python post-processing
  fields:                          # optional; omitted = raw rows
    id: "row.id"
    title: "row.title"
    text: "row.body"
```

## Check expression language

A deliberately small, safe expression language. No `eval`, no function calls,
no arithmetic, no indexing, no attribute access beyond one dot.

- Roots: `params`, `auth`, `row`, `rows`, `result`. Any other root is a config
  error, caught when the YAML is loaded.
- Literals: integers, floats, single- and double-quoted strings, `true`,
  `false`, `null`.
- Operators, loosest to tightest binding: `or`, then `and`, then `not`, then
  the comparisons `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`. Parentheses
  group.
- A missing key under a known root evaluates to `null`, so optional parameters
  can be compared without crashing.
- An ordering comparison (`<`, `<=`, `>`, `>=`) where either side is `null`
  evaluates to `false`, never an error.

## In scope

- Loading and validating `app.yml` and `endpoints/*.yml`, with unknown keys
  and undeclared SQL parameters reported as config errors at load time.
- The expression language above.
- Parameter coercion from five locations — `path`, `query`, `body`, `header`
  and `auth` — with 422 on failure. An `in: auth` parameter takes its value
  from the authenticated identity under its own name (`subject`), which is how
  a write statement binds the caller to a row.
- Business checks: expressions and Python hooks, in file order, first failure
  wins and uses the author's `status` and `message`.
- SQL execution with named `:param` binding, against SQLite and PostgreSQL.
- Response mapping, including nested field structures, plus an optional
  Python transform hook.
- Static bearer-token auth from `app.yml`, exposing `auth.subject` and
  `auth.roles` to expressions.
- Read (`GET`) and write (`POST`, `PUT`, `PATCH`, `DELETE`) endpoints.
- A working `example/` API project and a `FORMAT.md` reference.

## Non-goals

Nothing in this list gets implemented, however small it looks.

- **No pagination, sorting or filtering helpers.** No `limit`/`offset`/`sort`
  query-parameter magic. If an endpoint needs them, its SQL declares them as
  ordinary parameters.
- **No OpenAPI/Swagger schema generation.** `/docs` is left as FastAPI's
  default and is not populated from the YAML. The YAML file is the
  documentation.
- **No token issuing, no login endpoint, no JWT, no sessions, no cookies, no
  password hashing.** Tokens are static strings from `app.yml`.
- **No role-based access control as a feature.** `auth.roles` is data that
  expressions may read; there is no `roles:` key in the endpoint file.
- **No migrations.** `init_sql` runs one SQL script; it is not versioned,
  tracked or rolled back.
- **No ORM, no query builder, no declarative `table:`/`where:` syntax.** SQL is
  written by hand.
- **No multi-statement transactions across endpoints**, no explicit
  begin/commit control in YAML. One endpoint runs one statement.
- **No shared or reusable YAML fragments**, no `include`, no schema
  inheritance, no `$ref`.
- **No hot reload, no file watching.** Configuration is read once at startup.
- **No caching, rate limiting, CORS configuration, logging configuration or
  metrics.**
- **No arithmetic, function calls, string methods, indexing or slicing in the
  expression language.**
- **No async database drivers.** Handlers are synchronous.
- **No CLI.** The framework is used as `create_app(directory)`.

## Stack and constraints

- Python 3.13, the interpreter at `.venv/Scripts/python.exe`.
- Dependencies, and **only** these:
  - `fastapi`, `uvicorn` — already installed.
  - `pyyaml` — **authorized**, needed to parse YAML.
  - `httpx` — **authorized**, needed by `fastapi.testclient.TestClient`.
  - `psycopg` — **authorized but never installed and never imported at module
    import time.** It is imported lazily inside the PostgreSQL adapter, only
    when a `postgresql://` URL is actually opened. The test suite must pass on
    a machine where `psycopg` is absent.
- Everything else comes from the standard library: `sqlite3`, `importlib`,
  `dataclasses`, `os`, `unittest`.
- No network access at test time. No running database server at test time.

### File layout

```
baseapi/__init__.py
baseapi/errors.py       ConfigError, ApiError
baseapi/expr.py         pure: expression parser and evaluator
baseapi/config.py       YAML -> dataclasses, validation
baseapi/dialect.py      pure: SQL named-parameter handling
baseapi/db.py           SQLite and PostgreSQL adapters
baseapi/hooks.py        "module:function" -> callable
baseapi/mapping.py      pure: rows -> response body
baseapi/auth.py         static bearer tokens
baseapi/pipeline.py     the executor, no FastAPI import
baseapi/app.py          create_app(directory) -> FastAPI
main.py                 uvicorn entry point
example/                a working API project
FORMAT.md               YAML reference
verify/                 tests (read-only)
```

`baseapi/pipeline.py` must not import FastAPI, and must not read the clock,
the environment or the filesystem. That is what makes the whole request path
testable without a server.

## Acceptance criteria

1. `expr.parse(source)` returns a callable `f(context) -> value`; an unknown
   root name or a syntax error raises `ConfigError` at parse time, not at
   evaluation time.
2. Ordering comparisons involving `null` return `False` instead of raising.
3. `config.load_endpoint(data)` rejects, with `ConfigError`: unknown keys, a
   missing `name`/`method`/`path`/`query`, an unsupported method, a path
   placeholder with no matching `in: path` parameter, a `:name` in the SQL that
   is not a declared parameter, a check with both or neither of `when`/`hook`,
   and a body parameter on a `GET`.
4. `config.load_app(directory)` rejects duplicate endpoint names and duplicate
   `method + path` pairs, and resolves `token_env` from the environment,
   raising `ConfigError` when the variable is unset.
5. `dialect.param_names(sql)` finds every `:name` and ignores those inside
   quoted strings and PostgreSQL `::type` casts.
6. `db.connect("sqlite:///:memory:")` returns a `Database` whose `run()`
   returns a `Result` with `rows` as a list of dicts and an integer `rowcount`.
7. The PostgreSQL adapter is exercised by the test suite through an injected
   fake DB-API driver: it converts `:name` to `%(name)s` and passes the
   parameter dict through unchanged, with no `psycopg` installed.
8. Parameter coercion raises `ApiError(422)` naming the offending field for a
   missing required parameter or an uncoercible value, and fills declared
   defaults for absent optional ones.
9. `pipeline.handle(...)` runs checks in file order, returns the author's
   `status` and `message` for the first failing check, and never raises
   `ApiError` — it returns `(status, body)` in every case.
10. `returns: one` with no matching row returns the endpoint's `when_empty`
    status; `returns: many` with no rows returns an empty list with the normal
    status.
11. An endpoint with `auth: required` returns 401 when the `Authorization`
    header is missing, malformed or holds an unknown token, and exposes
    `auth.subject` / `auth.roles` to expressions when it is valid.
12. `create_app(directory)` serves every endpoint over HTTP with the statuses
    and bodies the pipeline produced, verified through `TestClient`.
13. The `example/` project loads and answers its four endpoints correctly from
    a clean checkout, with no manual database preparation.

## Verification

From the project root:

```
.venv/Scripts/python.exe -m unittest discover -s verify -t . -v
```

All checks in `verify/` must pass. **`verify/` is read-only for the
implementer** — see `AGENTS.md`.

## Open questions

None.
