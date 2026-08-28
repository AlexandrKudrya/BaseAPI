# AGENTS.md — BaseAPI

You are implementing this project. Read `SPEC.md` first, then `TASKS.md`.
These three files plus `verify/` are your complete context. Nothing else
exists — there is no other conversation, no wider repository, no hidden
requirement.

## Stack

- Python 3.13, already set up. The interpreter is `.venv\Scripts\python.exe`
  on Windows, `.venv/bin/python` elsewhere. Below, `PY` means that path.
- Web layer: FastAPI + uvicorn, already installed.
- Tests: the standard library `unittest`. There is no pytest.
- Exactly two dependencies beyond the above, and no others ever: `pyyaml` and
  `httpx`. **Both are already installed** — T0 only confirms it.
- This `.venv` was created by `uv`, so it has **no `pip`**, and `uv` itself is
  usually **not on `PATH`**. Neither matters unless T0's check fails; T0 lists
  the fallbacks in order.
- `psycopg` is **not installed and must never be imported at module level.**
  The PostgreSQL adapter imports it lazily, and the test suite drives that
  adapter through an injected fake driver. If you write
  `import psycopg` at the top of a file, every test in the suite stops
  collecting and the task fails.

## Commands

| What | Command |
|---|---|
| Setup check (T0 only) | `.venv\Scripts\python.exe -c "import yaml, httpx; print('ok')"` |
| Run one test file | `.venv\Scripts\python.exe -m unittest verify.test_expr -v` |
| Run the whole suite | `.venv\Scripts\python.exe -m unittest discover -s verify -t . -v` |
| Run the app | `.venv\Scripts\python.exe -m uvicorn main:app --port 8000` |

All commands run from the project root — the directory that holds `verify/`
and `pyproject.toml`.

## Working protocol

1. Take the first unchecked task in `TASKS.md` whose dependencies are done.
2. Implement it **inside the files listed under FILES for that task only**.
3. Run the task's `VERIFY` command.
4. If it fails, fix your implementation and run it again.
5. Report (format below), then move to the next task.

A test failure is information about your code. It is never information about
the test.

## Hard rules

- **Never modify or delete anything in `verify/`.** Those tests define what
  "done" means. Editing, deleting, renaming, skipping or `@unittest.skip`-ing
  a test to get a green run is a failed task, and the whole delivery is
  rejected. If a test looks wrong, stop and reply `NEEDS-DECISION` with the
  test name and what you think it asserts.
- **Never add a dependency** beyond `pyyaml` and `httpx`. No SQLAlchemy, no
  pydantic models of your own, no `python-multipart`, no `psycopg`, no
  `python-jose`, no CDN links.
- **Never use `eval`, `exec`, `compile` or `ast.literal_eval`** anywhere. The
  expression language is a hand-written parser. This is a security boundary:
  the framework evaluates strings that come out of config files.
- **Never touch files outside the current task's FILES.** If the task seems to
  require it, stop and reply `NEEDS-DECISION: <question>`.
- **Never expand scope.** Everything under `Non-goals` in `SPEC.md` stays
  unimplemented, even where it would be three lines. Pagination, OpenAPI
  schemas, JWT and a query builder are all explicitly excluded.
- **Keep the layers separate.** `expr.py`, `dialect.py` and `mapping.py` do no
  I/O. `pipeline.py` never imports FastAPI or `baseapi.db`. `app.py` does HTTP
  and nothing else. That separation is what makes the suite runnable without a
  server, so breaking it fails the task even if tests happen to pass.
- **Never claim a check passed without running it.**

## NEEDS-DECISION

If you cannot finish a task inside its FILES, or two requirements contradict
each other, stop immediately and reply with exactly:

```
NEEDS-DECISION: <the single specific question>
```

Do not improvise a workaround, do not widen the file list, and do not leave a
`TODO` in the code and carry on. A stopped task is cheap; a task that silently
solved a different problem is not.

## Report format

After each task, reply with exactly this:

```
TASK <ID> — done | needs-decision | blocked

FILES CHANGED
- <path> (created | modified)

COMMAND
$ <the exact command you ran>
<last ~15 lines of its real output>

DECISIONS
- <any non-obvious choice you made, one line each; "none" if none>

REMAINING
- <anything from the DoD you did not complete; "none" if none>
```

A report with no command output is not a report. If you did not run the
command, say so instead of pasting invented output.
