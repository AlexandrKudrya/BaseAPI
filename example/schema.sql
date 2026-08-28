-- Schema for the example notes API, executed once at connect time.
-- A single table: an autoincrementing id, a title, a body and an owner.

CREATE TABLE notes (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    body  TEXT NOT NULL,
    owner TEXT NOT NULL
);

-- Seed exactly two notes. In-memory SQLite starts empty every time the
-- app is built, so the ids are always 1 and 2.
INSERT INTO notes (id, title, body, owner) VALUES
    (1, 'first note',  'hello from alice', 'alice'),
    (2, 'second note', 'world from bob',   'bob');
