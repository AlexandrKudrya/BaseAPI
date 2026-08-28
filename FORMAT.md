# BaseAPI YAML format reference

BaseAPI turns YAML files into working HTTP endpoints. One file describes one
endpoint, end to end: request parameters, business checks, a SQL query, and the
shape of the JSON response. The author writes YAML; Python appears only as
optional hooks for logic an expression cannot express.

A project is a directory with:

- `app.yml` — the database connection and the auth tokens;
- `endpoints/*.yml` (or `.yaml`) — one file per endpoint;
- `hooks.py` — optional, referenced from YAML as `"module:function"`;
- `schema.sql` — optional, run once at connect time.

## app.yml

```yaml
database:
  url: "sqlite:///notes.db"        # or "postgresql://user:pass@host:5432/db"
  init_sql: "schema.sql"           # optional, executed on connect

auth:
  tokens:
    - token: "dev-token"           # a literal token value
      subject: "alice"
      roles: ["admin"]
    - token_env: "SERVICE_TOKEN"   # the token comes from this env variable
      subject: "service"
      roles: ["service"]
```

`database.url` is required; `database.init_sql` and the whole `auth` section
are optional (`auth.tokens` defaults to an empty list). A relative `sqlite`
path and `init_sql` resolve against the directory that holds `app.yml`.

## Endpoint files

```yaml
name: get_note                     # required, unique
method: GET                        # GET|POST|PUT|PATCH|DELETE
path: /notes/{note_id}             # required, unique with method
auth: required                     # required|none, default none
summary: "Return one note."        # optional, documentation only
```

## params

Five locations; each entry declares how to read and coerce a value:

```yaml
params:
  note_id: { in: path,   type: int,  required: true }
  verbose: { in: query,  type: bool, required: false, default: false }
  title:   { in: body,   type: str,  required: true }
  x_id:    { in: header, type: str }
  subject: { in: auth,   type: str,  required: false }
```

- `path` — read from the URL, matched by the `{placeholder}` in `path`.
- `query` — read from the query string, by exact name.
- `body` — read from the JSON body. Only allowed on `POST`, `PUT`, `PATCH`.
- `header` — matched case-insensitively; `_` in the parameter name matches `-`
  in the header name.
- `auth` — read from the authenticated identity under its own name (`subject`,
  for example), which is how a write statement binds a row to the caller.

`type` is one of `str`, `int`, `float`, `bool`. `required` defaults to `false`.
`has_default` is true only when the `default` key is present, so `default:
false` and `default: null` are real defaults. Coercion failures are a 422 and
name the offending field.

## checks

Business checks run in file order, after coercion and before the query. The
first failure wins and uses its own `status` and `message`.

```yaml
checks:
  - when: "params.note_id > 0"      # an expression check
    status: 400
    message: "note_id must be positive"
  - hook: "hooks:is_admin"          # a Python hook check
    status: 403
    message: "only admins may delete"
```

Exactly one of `when` and `hook` must be present. `status` defaults to `400`,
`message` to the exact string `"check failed"`.

## query

```yaml
query:
  sql: "SELECT id, title FROM notes WHERE id = :note_id"
  returns: one                     # one | many | none
```

Named parameters use `:name` and are bound, never interpolated. Every `:name`
must be a declared parameter; otherwise it is a config error. `returns` selects
the shape of the response:

- `one` — a single object; with no matching row the endpoint returns
  `response.when_empty` (default 404).
- `many` — a JSON array; with no rows it is `[]`.
- `none` — no rows; the only available roots are `params`, `auth`, `result`.

## response

```yaml
response:
  status: 200                      # default 200
  when_empty: 404                  # returns:one only, default 404
  transform: "hooks:decorate"      # optional Python post-processing
  fields:                          # optional; omitted = raw rows
    id: "row.id"
    title: "row.title"
    text: "row.body"
```

`fields` maps output keys to expressions and may nest arbitrarily. When
`fields` is omitted, a `one` result passes the row through, a `many` result
passes the rows through, and a `none` result is `{"rowcount": n}`.

## The expression language

A deliberately small, safe language. No `eval`, no function calls, no
arithmetic, no indexing, no attribute access beyond one dot.

- Roots: `params`, `auth`, `row`, `rows`, `result`. Any other root is a config
  error caught at load time.
- Literals: integers, floats, single- and double-quoted strings, `true`,
  `false`, `null`.
- Operators, loosest to tightest: `or`, `and`, `not`, then the comparisons
  `==`, `!=`, `<`, `<=`, `>`, `>=`, `in`, `not in`. Parentheses group.
- A missing key under a known root evaluates to `null`, so optional parameters
  can be compared without crashing.
- An ordering comparison (`<`, `<=`, `>`, `>=`) where either side is `null`
  evaluates to `false`, never an error. `==` and `!=` still work against
  `null`, and `in`/`not in` against a `null` right side is `false`.

## Hooks

A reference is exactly one colon with both halves non-empty. The module is
imported from the API directory.

- A *check* hook: `def check(ctx) -> bool`, where `ctx` is
  `{"params": ..., "auth": ...}` before the query and gains `row`, `rows` and
  `result` after it.
- A *transform* hook: `def transform(body, ctx)`, called after mapping; its
  return value becomes the body.

```python
def is_admin(ctx):
    return "admin" in ctx["auth"]["roles"]
```

## Non-goals

Deliberately not implemented, so do not look for them:

- no pagination, sorting or filtering helpers;
- no OpenAPI/Swagger schema generation;
- no token issuing, login, JWT, sessions, cookies or password hashing;
- no role-based access control as a feature (`auth.roles` is just data);
- no migrations (one `init_sql` script, unversioned);
- no ORM, query builder or declarative `table:`/`where:` syntax;
- no multi-statement transactions across endpoints;
- no shared/reusable YAML fragments, includes or `$ref`;
- no hot reload, file watching, caching, rate limiting, CORS, logging or
  metrics;
- no arithmetic, function calls, indexing or slicing in the expression
  language;
- no async database drivers; handlers are synchronous;
- no CLI; the framework is used as `create_app(directory)`.
