# BaseAPI — Tasks

Work through tasks in order. **One task at a time.** After each task, run its
`VERIFY` command and report before starting the next one.

Every command below is run from the project root. `PY` means
`.venv\Scripts\python.exe` on Windows and `.venv/bin/python` elsewhere.

| ID | Task | Depends on | Done |
|---|---|---|---|
| T0 | Confirm the two authorized dependencies are present | — | [x] |
| T1 | Errors and the check expression language | T0 | [x] |
| T2 | SQL named parameters | T0 | [x] |
| T3 | Config loading and validation | T1, T2 | [x] |
| T4 | Database adapters | T2 | [x] |
| T5 | Hook resolution | T0 | [x] |
| T6 | Response mapping | T1 | [x] |
| T7 | Bearer-token authentication | T1 | [x] |
| T8 | The request pipeline | T3, T6, T7 | [x] |
| T9 | The FastAPI layer | T4, T5, T8 | [x] |
| T10 | The example project and FORMAT.md | T9 | [x] |

---

## T0 — Confirm the two authorized dependencies are present

**GOAL**
Make the test suite runnable. Nothing else.

`pyyaml` and `httpx` were installed into `.venv` before this package was
handed to you, so in the normal case this task is a one-command check that
already passes and you install nothing.

**FILES**
- Modify: `pyproject.toml`, `uv.lock` — **only** as a side effect of an
  install command, and **only** if the check below fails. Never hand-edit
  either file.

**BOUNDARIES**
- Add no package other than `pyyaml` and `httpx`, now or later. `psycopg` is
  deliberately absent and must stay absent.
- Do not create any source file in this task.
- Do not create a new virtual environment, and do not upgrade or reinstall
  anything that already imports.

**DEFINITION OF DONE**
- [ ] `PY -c "import yaml, httpx; print('ok')"` prints `ok`.
- [ ] If it printed `ok` on the first try, **stop — the task is done.** Install
      nothing and change no file.
- [ ] Only if it failed, install with the first of these that runs. `uv` is
      often not on `PATH` on this machine, and this `.venv` has no `pip`, so
      do not stop at the first failure:
      1. `uv add pyyaml httpx`
      2. `C:\Users\mixak\AppData\Roaming\Python\Scripts\uv.exe add pyyaml httpx`
      3. `PY -m ensurepip --upgrade` then `PY -m pip install pyyaml httpx`
- [ ] If all three fail, reply `NEEDS-DECISION: cannot install pyyaml and
      httpx, <the exact error>` and stop.

**VERIFY**
```
.venv\Scripts\python.exe -c "import yaml, httpx; print('ok')"
```

**DEPENDS ON** — none

---

## T1 — Errors and the check expression language

**GOAL**
The two exception types the whole framework uses, and a small safe expression
language for business checks and response fields.

**FILES**
- Create: `baseapi/__init__.py` (may be empty)
- Create: `baseapi/errors.py`
- Create: `baseapi/expr.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Add no dependencies. `expr.py` imports only from `baseapi.errors` and the
  standard library.
- **Never use `eval`, `exec`, `compile` or `ast.literal_eval`.** Write a
  tokenizer and a recursive-descent parser by hand. A weak parser that defers
  to Python would accept `__import__` and is an automatic failure.
- No I/O, no clock, no environment access in either file.

**DEFINITION OF DONE**
- [ ] `errors.py` exports `ConfigError(Exception)` — raised for anything wrong
      in the YAML or in wiring, always at load time.
- [ ] `errors.py` exports `ApiError(Exception)` with `__init__(self, status,
      message)`, storing `.status` (int) and `.message` (str).
- [ ] `expr.py` exports `parse(source: str) -> Callable[[dict], Any]`.
      `parse` does all the work; the returned callable only evaluates.
- [ ] Grammar, loosest to tightest: `or`, `and`, `not`, then the comparisons
      `== != < <= > >= in "not in"`, then a primary. A primary is a literal,
      a `root.name` path, or a parenthesised expression. Comparisons do not
      chain: `1 < 2 < 3` is a syntax error.
- [ ] Literals: integers, floats, single- and double-quoted strings, `true`,
      `false`, `null`.
- [ ] The only accepted path roots are `params`, `auth`, `row`, `rows`,
      `result`. Any other root raises `ConfigError` **at parse time**, and the
      message contains the offending root name.
- [ ] A path is exactly `root.name` — one dot. `params` alone and
      `params.a.b` are syntax errors.
- [ ] At evaluation time a missing root, or a missing key under a present
      root, yields `None`.
- [ ] `and`, `or`, `not` and every comparison return real `bool` values, not
      the operands. Truthiness of a non-boolean follows normal Python rules.
- [ ] `<`, `<=`, `>`, `>=` return `False` when either side is `None`.
      `==` and `!=` keep working against `None`.
- [ ] `in` / `not in` return `False` when the right side is `None`.
- [ ] Any syntax error — including an empty source, a trailing token, an
      unterminated string, a function call, an index, or arithmetic — raises
      `ConfigError`.
- [ ] `PY -m unittest verify.test_expr -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_expr -v
```

**DEPENDS ON** — T0

---

## T2 — SQL named parameters

**GOAL**
Find `:name` placeholders in a SQL statement, and rewrite them for drivers that
speak the pyformat style.

**FILES**
- Create: `baseapi/dialect.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Standard library only. No `re`-only shortcut that ignores string literals —
  scan the statement character by character.

**DEFINITION OF DONE**
- [ ] Exports `param_names(sql: str) -> list[str]` — every placeholder in
      order of first appearance, without duplicates.
- [ ] A placeholder is `:` followed by `[A-Za-z_]` then `[A-Za-z0-9_]*`.
- [ ] Text inside `'single quoted'` (with `''` as the escape) and inside
      `"double quoted"` identifiers is skipped entirely.
- [ ] `::` is a PostgreSQL cast and never starts a placeholder.
- [ ] Exports `to_pyformat(sql: str) -> str` — every placeholder becomes
      `%(name)s`, every literal `%` becomes `%%`, and casts and string
      literals are otherwise untouched.
- [ ] `PY -m unittest verify.test_dialect -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_dialect -v
```

**DEPENDS ON** — T0

---

## T3 — Config loading and validation

**GOAL**
Turn `app.yml` and `endpoints/*.yml` into validated dataclasses. This is where
the user's typos get caught, so validation is the point of the task, not a
side concern.

**FILES**
- Create: `baseapi/config.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- May import `yaml`, `baseapi.errors`, `baseapi.expr`, `baseapi.dialect` and
  the standard library. Nothing else.
- Use `yaml.safe_load`, never `yaml.load`.
- Do not open a database connection here.
- **Every error raised from this module is a `ConfigError`**, including
  wrapped YAML parse errors and missing files.
- **Validate the type of every scalar before using it, in `app.yml` exactly
  as in the endpoint files.** YAML turns `when: true` into a `bool` and
  `path: 123` into an `int`. Handing either to `str`-expecting code leaks a
  raw `TypeError`/`AttributeError` past the `ConfigError` contract. Check the
  type first, then use the value. This applies to `database.url`,
  `database.init_sql`, `token`, `token_env`, `subject` and `roles` just as
  much as to endpoint keys — `load_app` and `load_endpoint` are two halves of
  one contract.
- **`bool` is a subclass of `int` in Python.** Any field that must be an
  integer — `check.status`, `response.status`, `response.when_empty` — has to
  reject `True`/`False` explicitly, or a YAML `when_empty: true` becomes an
  HTTP status of `True`.

**DEFINITION OF DONE**
- [ ] Dataclasses: `ParamSpec(name, location, type, required, default,
      has_default)`, `CheckSpec(expression, hook, status, message)`,
      `QuerySpec(sql, returns)`, `ResponseSpec(status, when_empty, transform,
      fields)`, `Endpoint(name, method, path, summary, auth, params, checks,
      query, response)`, `AppConfig(base_dir, database_url, init_sql, tokens,
      endpoints)`.
- [ ] Exports `load_endpoint(data: dict, *, source: str = "<memory>")
      -> Endpoint`, working from a plain dict with no file access.
- [ ] Exports `load_app(directory: str) -> AppConfig`.
- [ ] Endpoint keys: `name`, `method`, `path` and `query` are required;
      `summary`, `auth`, `params`, `checks`, `response` are optional. Any
      other key is a `ConfigError` naming it.
- [ ] Defaults: `summary` `""`, `auth` `"none"`, `params` `{}`, `checks` `[]`,
      `response.status` `200`, `response.when_empty` `404`,
      `response.transform` `None`, `response.fields` `None`.
- [ ] `method` is upper-cased and must be one of `GET POST PUT PATCH DELETE`.
- [ ] `auth` must be `"required"` or `"none"`.
- [ ] `path` must start with `/`. Every `{placeholder}` in it must have a
      declared parameter with `in: path`, and every `in: path` parameter must
      appear in the path. Both directions are errors, and the message names
      the parameter.
- [ ] Param keys: `in`, `type`, `required`, `default`. `in` is one of
      `path query body header auth`; `type` is one of `str int float bool`.
      `required` defaults to `False`. `has_default` is `True` only when the
      key `default` is present — `default: false` and `default: null` are real
      defaults.
- [ ] A parameter with `in: body` is rejected unless the method is `POST`,
      `PUT` or `PATCH`, and the message contains `body`.
- [ ] Query keys: `sql` (required), `returns` (required, one of
      `one many none`). Every name returned by `dialect.param_names(sql)` must
      be a declared parameter; otherwise `ConfigError` naming it.
- [ ] Response keys: `status`, `when_empty`, `transform`, `fields`.
      `when_empty` is only allowed when `returns` is `one`, and the message
      contains `when_empty`.
- [ ] Check keys: `when`, `hook`, `status`, `message`. Exactly one of `when`
      and `hook` must be present. `status` defaults to `400`, `message`
      defaults to the exact string `"check failed"`.
- [ ] `when` is compiled with `expr.parse` into `CheckSpec.expression`;
      for a `hook` check, `expression` is `None` and `hook` holds the string.
- [ ] Every value in `response.fields` is compiled with `expr.parse`; a value
      that is itself a mapping is compiled recursively, so nesting works.
      A parse failure surfaces as `ConfigError`.
- [ ] A `hook` or `transform` string must be `module:function` — exactly one
      colon, neither half empty. Otherwise `ConfigError`. The module is **not**
      imported here.
- [ ] `load_app` reads `<directory>/app.yml`; a missing directory, a missing
      `app.yml`, a missing `endpoints/` directory, or unparsable YAML is a
      `ConfigError`, and for a per-file failure the message contains the file
      name.
- [ ] `app.yml` accepts only `database` and `auth`. `database.url` is
      required; `database.init_sql` names a file, read as text into
      `AppConfig.init_sql` (missing file is a `ConfigError`); `init_sql` is
      `None` when the key is absent.
- [ ] Each entry in `auth.tokens` has exactly one of `token` and `token_env`,
      plus a required `subject` and optional `roles` (default `[]`).
      `token_env` is read from `os.environ`; an unset variable is a
      `ConfigError` naming the variable. `AppConfig.tokens` maps the resolved
      token string to `{"subject": ..., "roles": [...]}`.
- [ ] `token`, `token_env` and `subject` must be strings — never coerced with
      `str()`, or `token: null` silently becomes the usable token `"None"`.
      `roles` must be a list of strings: `roles: "admin"` would turn
      `'admin' in auth.roles` into a substring match, so a role named `adm`
      would pass an admin-only check.
- [ ] Endpoint files are `endpoints/*.yml` and `endpoints/*.yaml`, loaded in
      sorted filename order. A file whose top level is not a mapping is a
      `ConfigError`. An empty `endpoints/` directory yields `[]`.
- [ ] Duplicate endpoint `name`, or a duplicate `method` + `path` pair, is a
      `ConfigError` naming the duplicate.
- [ ] `AppConfig.base_dir` is the directory that was passed in.
- [ ] `PY -m unittest verify.test_config -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_config -v
```

**DEPENDS ON** — T1, T2

---

## T4 — Database adapters

**GOAL**
One narrow interface over SQLite and PostgreSQL, so the rest of the framework
never sees a driver.

**FILES**
- Create: `baseapi/db.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- May import `sqlite3`, `baseapi.dialect`, `baseapi.errors`, `threading`, `os`
  and the standard library.
- **Never import `psycopg` at module level.** It is not installed. Import it
  inside the PostgreSQL adapter only, at the moment a connection is opened,
  and only when no `driver` was injected.
- Never build SQL by string formatting or concatenation of parameter values.

**DEFINITION OF DONE**
- [ ] Exports a `Result` dataclass with `rows: list[dict]` and
      `rowcount: int`.
- [ ] Exports `connect(url, *, base_dir=".", init_sql=None, driver=None)`
      returning an object with `run(sql, params) -> Result` and `close()`.
- [ ] `run` passes only the parameters the statement actually names, using
      `dialect.param_names`; extra keys in `params` are dropped, not an error.
- [ ] When the executed cursor has a `description`, `rows` is
      `[dict(zip(columns, row)) for row in cursor.fetchall()]` with plain
      `dict` values, and `rowcount` is `len(rows)`. Otherwise `rows` is `[]`
      and `rowcount` is `cursor.rowcount`.
- [ ] Every `run` commits.
- [ ] A `run` call is serialised with a `threading.Lock`, because the web
      server calls handlers from a thread pool over one shared connection.
- [ ] SQLite: `sqlite:///` prefix; the remainder is the path; `:memory:` is
      in-memory; a relative path is joined to `base_dir`. The connection is
      opened with `check_same_thread=False`.
- [ ] PostgreSQL: `postgresql://` and `postgres://` prefixes. The full URL is
      passed to `driver.connect(url)` unchanged. SQL is converted with
      `dialect.to_pyformat` before execution, and the parameter dict is passed
      through as-is.
- [ ] `init_sql` is SQL **text**, not a path, and is executed once at connect
      time before `connect` returns.
- [ ] Any other URL scheme, and an empty URL, raise `ConfigError`.
- [ ] `PY -m unittest verify.test_db -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_db -v
```

**DEPENDS ON** — T2

---

## T5 — Hook resolution

**GOAL**
Turn a `"module:function"` string into a real callable, importing the user's
`hooks.py` from their API directory.

**FILES**
- Create: `baseapi/hooks.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Standard library plus `baseapi.errors` only.
- Do not call the resolved function here.

**DEFINITION OF DONE**
- [ ] Exports `resolve_hook(ref: str, *, base_dir: str | None = None)
      -> Callable`.
- [ ] `ref` must contain exactly one colon with a non-empty module path and a
      non-empty attribute name; otherwise `ConfigError`.
- [ ] When `base_dir` is given it is prepended to `sys.path` for the import
      and **removed again afterwards, including when the import fails** — use
      `try/finally`.
- [ ] When `base_dir` is given, the module is resolved **from that
      directory**, even if a module of the same name was already imported
      from a different one. Two API projects each shipping a plain `hooks.py`
      must get their own functions. `importlib.import_module` alone does not
      do this: it returns whatever `sys.modules` already holds under that
      name. Before importing, drop any cached entry for the top-level module
      name — and its submodules — whose `__file__` is not inside `base_dir`.
- [ ] A callable already returned by an earlier `resolve_hook` keeps working
      unchanged after a later call resolves the same name elsewhere.
- [ ] A dotted module path (`pkg.checks:fn`) works.
- [ ] A module that cannot be imported, an attribute that does not exist, and
      an attribute that is not callable each raise `ConfigError`, and the
      message names the module or the attribute.
- [ ] `PY -m unittest verify.test_hooks -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_hooks -v
```

**DEPENDS ON** — T0

---

## T6 — Response mapping

**GOAL**
Turn query rows into the response body described by `response.fields`.

**FILES**
- Create: `baseapi/mapping.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Pure function: no I/O, no clock, no imports beyond the standard library.
- Never mutate the `context` or the rows inside it.

**DEFINITION OF DONE**
- [ ] Exports `build_body(fields, context, returns)`.
- [ ] `fields` is either `None` or a mapping whose values are callables
      (compiled expressions) or nested mappings of the same shape.
- [ ] `returns == "one"`: with `fields` `None`, return a **copy** of
      `context["row"]`; otherwise evaluate the field structure against
      `context` and return a dict in the field declaration order.
- [ ] `returns == "many"`: with `fields` `None`, return `context["rows"]`
      unchanged in content; otherwise return a list, evaluating the field
      structure once per row with `row` bound to that row and every other root
      taken from `context`. The list is empty when there are no rows, and a
      pre-existing `context["row"]` must not leak into any item.
- [ ] `returns == "none"`: with `fields` `None`, return
      `{"rowcount": context["result"]["rowcount"]}`; otherwise evaluate the
      field structure against `context`.
- [ ] `PY -m unittest verify.test_mapping -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_mapping -v
```

**DEPENDS ON** — T1

---

## T7 — Bearer-token authentication

**GOAL**
Turn an `Authorization` header into an identity, or reject it.

**FILES**
- Create: `baseapi/auth.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Standard library plus `baseapi.errors` only.
- No hashing, no signing, no expiry, no database lookup. Static tokens only.

**DEFINITION OF DONE**
- [ ] Exports `ANONYMOUS`, equal to `{"subject": None, "roles": []}`.
- [ ] Exports `authenticate(header_value, tokens) -> dict`, where `tokens` is
      the mapping from `AppConfig.tokens`.
- [ ] The header must be `Bearer <token>`; the scheme is matched
      case-insensitively, surrounding whitespace is ignored, and the token
      value is compared exactly.
- [ ] `None`, an empty or whitespace-only header, a different scheme, a
      missing token and an unknown token each raise `ApiError` with
      `status == 401`.
- [ ] The 401 message must not contain the supplied token value.
- [ ] The returned identity is a fresh dict with a fresh `roles` list, so a
      caller cannot mutate the configuration through it.
- [ ] `PY -m unittest verify.test_auth -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_auth -v
```

**DEPENDS ON** — T1

---

## T8 — The request pipeline

**GOAL**
The executor: one endpoint plus one request in, one `(status, body)` pair out.
This is the whole product, and it is deliberately free of HTTP.

**FILES**
- Create: `baseapi/pipeline.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- **Do not import `fastapi`, `starlette`, `uvicorn` or `baseapi.db` here.**
  The database arrives as an argument and is used only through
  `run(sql, params)`.
- No clock, no environment, no filesystem access.

**DEFINITION OF DONE**
- [ ] Exports `coerce_params(endpoint, *, path=None, query=None, body=None,
      headers=None, auth=None) -> dict`, raising `ApiError(422, ...)` whose
      message names the offending parameter.
- [ ] Each parameter is read only from its declared location. `path`, `query`
      and `body` are looked up by exact name; `header` is matched
      case-insensitively with `_` in the parameter name matching `-` in the
      header name; `auth` reads the identity dict by the parameter name.
- [ ] A value of `None`, and an absent key, both count as missing. A missing
      required parameter is a 422. A missing optional parameter uses its
      `default` **uncoerced** when it has one, and is otherwise left out of
      the returned dict entirely. An empty string is a value, not a missing
      one.
- [ ] Coercion, with anything else a 422: `int` accepts `int` (never `bool`)
      and a string parsing as an integer; `float` accepts `int`, `float`
      (never `bool`) and a string parsing as a float; `bool` accepts `bool`,
      `0`/`1`, and case-insensitively `true false 1 0 yes no on off`; `str`
      accepts `str` and stringifies `int` and `float`, but rejects `bool`.
- [ ] If any parameter is declared `in: body` and `body` is not a mapping
      (including `None`), that is a 422.
- [ ] Unknown extra keys in any source are ignored.
- [ ] Exports `handle(endpoint, *, db, path=None, query=None, body=None,
      headers=None, auth=None, hooks=None) -> tuple[int, Any]`, forwarding
      **all four** request sources — including `headers` — to
      `coerce_params`. An `in: header` parameter that works in
      `coerce_params` but never receives a value through `handle` is a dead
      feature, not a passing task.
- [ ] `handle` runs exactly this order and stops at the first failure:
      1. If `endpoint.auth == "required"` and `auth` is falsy — 401.
      2. `coerce_params` — 422 on failure.
      3. Checks, in list order. An expression check fails when its value is
         falsy; a hook check fails when `hooks[ref](context)` returns a falsy
         value. On failure use that check's `status` and `message`.
      4. `db.run(endpoint.query.sql, params)`.
      5. For `returns == "one"` with no rows — `response.when_empty` with the
         message `"not found"`.
      6. `mapping.build_body`, then the `transform` hook if there is one.
- [ ] The context handed to expressions and hooks is
      `{"params": ..., "auth": ...}` before the query, and additionally
      `"row"` (the first row, or `None`), `"rows"` and
      `"result": {"rowcount": ...}` after it.
- [ ] `auth` defaults to `auth.ANONYMOUS` when it is not supplied.
- [ ] `returns == "one"` uses the first row when the query returns several.
- [ ] A transform hook is called as `hooks[ref](body, context)` and its return
      value becomes the body.
- [ ] Every error response body is exactly
      `{"error": {"code": <status>, "message": <str>}}`.
- [ ] `handle` **never** lets an `ApiError` escape. A `hook` reference that is
      missing from `hooks` raises `ConfigError` — that is a wiring bug, not a
      request failure, and it is the one exception that may propagate.
- [ ] The query does not run when auth, coercion or a check fails, and the
      transform hook does not run when anything before it fails.
- [ ] `PY -m unittest verify.test_pipeline -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_pipeline -v
```

**DEPENDS ON** — T3, T6, T7

---

## T9 — The FastAPI layer

**GOAL**
Mount the endpoints on a real server. This file does HTTP and nothing else:
no validation, no business logic, no mapping.

**FILES**
- Create: `baseapi/app.py`
- Modify: `main.py`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Do not change any module from T1–T8. If one seems wrong, stop and reply
  `NEEDS-DECISION`.
- Do not use FastAPI request models, `pydantic`, `Depends` validation or
  response models. Take the raw `Request`; the framework does its own
  validation. This is deliberate — schema generation is a Non-goal.

**DEFINITION OF DONE**
- [ ] Exports `create_app(directory: str) -> FastAPI`.
- [ ] At startup, and **before returning**, `create_app` loads the config,
      resolves every `hook` and `transform` reference with
      `hooks.resolve_hook(ref, base_dir=config.base_dir)` into one dict, and
      opens the database with `db.connect(config.database_url,
      base_dir=config.base_dir, init_sql=config.init_sql)`. Any failure
      surfaces as `ConfigError` from `create_app`, not at request time.
- [ ] One route per endpoint, registered with its own `method` and `path`.
      FastAPI's `{placeholder}` syntax already matches the YAML `path`.
- [ ] Each handler reads path parameters, query parameters, headers and — for
      `POST`/`PUT`/`PATCH` — the JSON body, and passes **every one of them**
      to `pipeline.handle`, headers included. The request headers serve two
      separate purposes: `Authorization` for authentication, and any
      `in: header` parameter the endpoint declares. A body that is absent or
      not valid JSON is passed along as `None`, never raised.
- [ ] When `endpoint.auth == "required"`, the `Authorization` header goes
      through `auth.authenticate`; a raised `ApiError` becomes that status and
      the standard error body. When it is `"none"`, the identity is
      `auth.ANONYMOUS` and any supplied header is ignored.
- [ ] The handler calls `pipeline.handle` and returns its `(status, body)` as
      a `JSONResponse`.
- [ ] `main.py` exposes `app = create_app(...)`, defaulting to the `example`
      directory **resolved relative to `main.py` itself**, overridable with
      the `BASEAPI_DIR` environment variable.
- [ ] `PY -m unittest verify.test_app -v` passes.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest verify.test_app -v
```

**DEPENDS ON** — T4, T5, T8

---

## T10 — The example project and FORMAT.md

**GOAL**
A working API a reader can copy, plus the reference that makes the YAML format
self-explanatory. This is the deliverable the user actually looks at first.

**FILES**
- Create: `example/app.yml`
- Create: `example/schema.sql`
- Create: `example/hooks.py`
- Create: `example/endpoints/list_notes.yml`
- Create: `example/endpoints/get_note.yml`
- Create: `example/endpoints/create_note.yml`
- Create: `example/endpoints/delete_note.yml`
- Create: `FORMAT.md`

**BOUNDARIES**
- Do not modify any file outside FILES. Do not modify `verify/`.
- Do not change any module from T1–T9 to make the example work. If the example
  cannot be expressed in the format as built, that is a real finding — stop
  and reply `NEEDS-DECISION`.
- No new endpoints beyond the four listed. No pagination, no search, no
  update endpoint.

**DEFINITION OF DONE**
- [ ] `example/app.yml` uses `url: "sqlite:///:memory:"` and
      `init_sql: "schema.sql"`, and declares exactly two tokens:
      `dev-token` → subject `alice`, roles `["admin"]`; and
      `reader-token` → subject `bob`, roles `["reader"]`.
- [ ] `example/schema.sql` creates a `notes` table with an autoincrementing
      `id` plus `title`, `body` and `owner`, and seeds **exactly two** rows
      with ids `1` and `2` and non-empty titles.
- [ ] `example/hooks.py` defines `is_admin(ctx)` returning whether `"admin"`
      is in `ctx["auth"]["roles"]`.
- [ ] `GET /notes` — `returns: many`, no auth, fields exactly
      `id`, `title`, `text` (from the `body` column) and `owner`.
- [ ] `GET /notes/{note_id}` — `returns: one`, no auth, a check rejecting
      `note_id <= 0` with status `400`, and `when_empty: 404`.
- [ ] `POST /notes` — `auth: required`, body `title` and `body`, an
      `in: auth` parameter for the owner, `INSERT ... RETURNING id`,
      `status: 201`, and a response containing the new `id`.
- [ ] `DELETE /notes/{note_id}` — `auth: required`, a `hook` check on
      `hooks:is_admin` with status `403`, `returns: none`, and a response
      field `deleted` from `result.rowcount`.
- [ ] Every YAML file carries short `#` comments explaining its sections —
      this example is documentation as much as it is a test fixture.
- [ ] `FORMAT.md` is at least 1500 characters and documents `app.yml`, all
      five `params` locations, `checks` (both `when` and `hook`), `query`
      with `returns`, `response` with `status`, `when_empty`, `fields` and
      `transform`, the expression language including its roots and its `null`
      rules, and both hook signatures — `check(ctx)` and
      `transform(body, ctx)`. It also states the Non-goals, so a reader does
      not go looking for pagination.
- [ ] Running the example creates no `.db` file anywhere.
- [ ] `PY -m unittest verify.test_example -v` passes.
- [ ] The full suite passes: `PY -m unittest discover -s verify -t . -v`.

**VERIFY**
```
.venv\Scripts\python.exe -m unittest discover -s verify -t . -v
```
Then start the server and confirm by eye:
```
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```
- `GET http://127.0.0.1:8000/notes` returns two notes as JSON;
- `GET http://127.0.0.1:8000/notes/999` returns 404 with an `error` object;
- `POST http://127.0.0.1:8000/notes` without a token returns 401.

**DEPENDS ON** — T9
