# Хендофф: BaseAPI — декларативные API на YAML

## Что это

Фреймворк, который превращает yml-файлы в работающие HTTP-ручки. Один файл —
одна ручка, целиком: параметры, бизнес-проверки, SQL, форма ответа.

Рабочее дерево — `C:\Users\mixak\PycharmProjects\BaseAPI`. Код исполнителя
ложится туда же, рядом с `verify/`.

## Что делать

1. Открой чат исполнителя (DeepSeek).
2. Приложи файлы: `AGENTS.md`, `SPEC.md`, `TASKS.md` и папку `verify/`
   (десять файлов `test_*.py` плюс пустой `__init__.py`).
   Если приложить папку нельзя — вставь содержимое тестов следом за текстом
   ниже, каждый под своим заголовком с путём.
3. Вставь текст из блока и отправь.

Пакет крупный: одиннадцать задач. Если исполнитель начнёт сыпаться на длинном
горизонте — выдавай по одной задаче за заход через `/next-task yaml-api`.

## Текст для вставки

```
You are implementing a project. I am attaching four things: AGENTS.md (your
standing rules), SPEC.md (what to build and what NOT to build), TASKS.md (the
ordered task list) and verify/ (tests that define "done").

Read AGENTS.md first. Then work through TASKS.md one task at a time, in order,
starting with T0.

Rules that override anything you might otherwise assume:
- verify/ is read-only. Never edit, delete, rename or skip a test to get a
  passing run. A test failure is information about your code, never about the
  test.
- Stay inside the FILES listed for the current task.
- Add no dependencies beyond pyyaml and httpx, which T0 installs. psycopg is
  NOT installed and must never be imported at module level - the PostgreSQL
  adapter imports it lazily and the tests drive it through a fake driver.
- Never use eval, exec, compile or ast.literal_eval. The expression language
  is a hand-written tokenizer and recursive-descent parser. This is a security
  boundary: the framework evaluates strings that come from config files.
- Implement nothing listed under Non-goals: no pagination, no OpenAPI schema
  generation, no JWT, no query builder, no migrations, no hot reload.
- Keep the layers separate. expr.py, dialect.py and mapping.py do no I/O.
  pipeline.py never imports fastapi or baseapi.db. app.py does HTTP only.
- After each task, run its VERIFY command and paste the real output.
  Never report success without the output.
- If you cannot finish a task within its FILES, stop and reply
  NEEDS-DECISION: <question>. Do not improvise a workaround.

Start with T0.
```

## Проверить самому, без Claude

В папке `C:\Users\mixak\PycharmProjects\BaseAPI`:

```bash
.venv\Scripts\python.exe -m unittest discover -s verify -t . -v
```

Сейчас, на пустом проекте, это падает десятью `ModuleNotFoundError: No module
named 'baseapi'` — так и должно быть. Зелёный прогон закрывает T1–T10
полностью: тестами покрыт весь путь запроса, включая FastAPI-слой и пример.

Глазами добивается только последний пункт T10 — поднять сервер и потыкать:

```bash
.venv\Scripts\python.exe -m uvicorn main:app --port 8000
```

`GET /notes` — два примечания, `GET /notes/999` — 404 с объектом `error`,
`POST /notes` без токена — 401.

## Про зависимости

`pyyaml` и `httpx` я уже поставил в `.venv`, `pyproject.toml` и `uv.lock`
обновлены. T0 — просто проверка импорта, она пройдёт сразу.

Это важно, потому что `uv` у тебя не в `PATH` (лежит в
`C:\Users\mixak\AppData\Roaming\Python\Scripts\uv.exe`), а `pip` внутри
`.venv` отсутствует — venv создан через uv. Исполнитель об этом предупреждён
и знает порядок запасных вариантов, но трогать их ему не придётся.

## Когда вернётся код

Положи присланные файлы в `C:\Users\mixak\PycharmProjects\BaseAPI` по путям из
`FILES` соответствующей задачи. Затем запусти в Claude:

```
/handback yaml-api
```
