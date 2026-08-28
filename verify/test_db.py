"""Database adapters. SQLite runs for real; PostgreSQL runs against a fake
DB-API driver so the suite needs no server and no psycopg installed."""

import os
import tempfile
import threading
import unittest

from baseapi.db import connect
from baseapi.errors import ConfigError


# --------------------------------------------------------------------------
# A minimal DB-API 2.0 stand-in, used to observe what the adapter sends.
# --------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.description = None
        self.rowcount = -1
        self._rows = []

    def execute(self, sql, params=None):
        self.connection.calls.append((sql, params))
        scripted = self.connection.result
        if scripted is None:
            self.description = None
            self.rowcount = 3
            self._rows = []
        else:
            columns, rows = scripted
            self.description = [(name,) + (None,) * 6 for name in columns]
            self._rows = list(rows)
            self.rowcount = len(rows)

    def fetchall(self):
        return list(self._rows)

    def close(self):
        self.connection.closed_cursors += 1


class FakeConnection:
    def __init__(self, dsn):
        self.dsn = dsn
        self.calls = []
        self.commits = 0
        self.closed = False
        self.closed_cursors = 0
        self.result = None

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


class FakeDriver:
    """Stands in for the psycopg module."""

    def __init__(self):
        self.connections = []

    def connect(self, dsn):
        conn = FakeConnection(dsn)
        self.connections.append(conn)
        return conn


# --------------------------------------------------------------------------


class TestSqlite(unittest.TestCase):
    def test_select_returns_rows_as_plain_dicts(self):
        db = connect("sqlite:///:memory:")
        try:
            result = db.run("SELECT 1 AS n, 'a' AS s", {})
            self.assertEqual(result.rows, [{"n": 1, "s": "a"}])
            self.assertIs(type(result.rows[0]), dict)
        finally:
            db.close()

    def test_select_rowcount_is_the_number_of_rows(self):
        db = connect("sqlite:///:memory:")
        try:
            db.run("CREATE TABLE t (id INTEGER)", {})
            db.run("INSERT INTO t (id) VALUES (1), (2), (3)", {})
            result = db.run("SELECT id FROM t ORDER BY id", {})
            self.assertEqual(result.rowcount, 3)
            self.assertEqual(result.rows, [{"id": 1}, {"id": 2}, {"id": 3}])
        finally:
            db.close()

    def test_select_with_no_matching_rows(self):
        db = connect("sqlite:///:memory:")
        try:
            db.run("CREATE TABLE t (id INTEGER)", {})
            result = db.run("SELECT id FROM t", {})
            self.assertEqual(result.rows, [])
            self.assertEqual(result.rowcount, 0)
        finally:
            db.close()

    def test_named_parameters_are_bound_not_interpolated(self):
        db = connect("sqlite:///:memory:")
        try:
            db.run("CREATE TABLE t (id INTEGER, s TEXT)", {})
            db.run("INSERT INTO t VALUES (:id, :s)", {"id": 1, "s": "x"})
            hostile = "1 OR 1=1; DROP TABLE t; --"
            result = db.run("SELECT id FROM t WHERE s = :s", {"s": hostile})
            self.assertEqual(result.rows, [])
            # the table is still there, so nothing was interpolated
            self.assertEqual(db.run("SELECT COUNT(*) AS c FROM t", {}).rows,
                             [{"c": 1}])
        finally:
            db.close()

    def test_write_reports_the_affected_row_count(self):
        db = connect("sqlite:///:memory:")
        try:
            db.run("CREATE TABLE t (id INTEGER)", {})
            db.run("INSERT INTO t (id) VALUES (1), (2), (3)", {})
            result = db.run("DELETE FROM t WHERE id > :id", {"id": 1})
            self.assertEqual(result.rowcount, 2)
            self.assertEqual(result.rows, [])
        finally:
            db.close()

    def test_insert_with_returning_gives_rows_back(self):
        db = connect("sqlite:///:memory:")
        try:
            db.run("CREATE TABLE t (id INTEGER PRIMARY KEY, s TEXT)", {})
            result = db.run(
                "INSERT INTO t (s) VALUES (:s) RETURNING id", {"s": "a"}
            )
            self.assertEqual(result.rows, [{"id": 1}])
        finally:
            db.close()

    def test_a_write_is_committed(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = connect("sqlite:///data.db", base_dir=tmp)
            first.run("CREATE TABLE t (id INTEGER)", {})
            first.run("INSERT INTO t (id) VALUES (7)", {})
            first.close()

            second = connect("sqlite:///data.db", base_dir=tmp)
            try:
                self.assertEqual(second.run("SELECT id FROM t", {}).rows,
                                 [{"id": 7}])
            finally:
                second.close()

    def test_a_relative_path_resolves_against_base_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = connect("sqlite:///nested.db", base_dir=tmp)
            db.run("CREATE TABLE t (id INTEGER)", {})
            db.close()
            self.assertTrue(os.path.isfile(os.path.join(tmp, "nested.db")))

    def test_parameters_the_sql_does_not_use_are_dropped(self):
        # the pipeline hands over every declared parameter, but a statement
        # only binds the ones it names.
        db = connect("sqlite:///:memory:")
        try:
            db.run("CREATE TABLE t (id INTEGER)", {})
            db.run("INSERT INTO t (id) VALUES (1)", {"unused": "x"})
            result = db.run("SELECT id FROM t WHERE id = :id",
                            {"id": 1, "verbose": True})
            self.assertEqual(result.rows, [{"id": 1}])
        finally:
            db.close()

    def test_init_sql_runs_at_connect_time(self):
        script = (
            "CREATE TABLE IF NOT EXISTS t (id INTEGER);"
            "INSERT INTO t (id) VALUES (5);"
        )
        db = connect("sqlite:///:memory:", init_sql=script)
        try:
            self.assertEqual(db.run("SELECT id FROM t", {}).rows, [{"id": 5}])
        finally:
            db.close()


class TestSqliteThreads(unittest.TestCase):
    """The web server runs sync handlers on a thread pool, so one connection
    is shared across threads and must tolerate that."""

    def test_a_connection_is_usable_from_another_thread(self):
        db = connect("sqlite:///:memory:")
        self.addCleanup(db.close)
        db.run("CREATE TABLE t (id INTEGER)", {})
        db.run("INSERT INTO t (id) VALUES (1)", {})

        errors = []

        def read():
            try:
                self.assertEqual(db.run("SELECT id FROM t", {}).rows,
                                 [{"id": 1}])
            except Exception as exc:  # noqa: BLE001 - reported to the main thread
                errors.append(exc)

        worker = threading.Thread(target=read)
        worker.start()
        worker.join()
        self.assertEqual(errors, [])

    def test_concurrent_use_from_several_threads_does_not_corrupt_results(self):
        db = connect("sqlite:///:memory:")
        self.addCleanup(db.close)
        db.run("CREATE TABLE t (id INTEGER)", {})
        db.run("INSERT INTO t (id) VALUES (1), (2), (3)", {})

        seen = []
        errors = []

        def work():
            for _ in range(20):
                try:
                    rows = db.run("SELECT id FROM t ORDER BY id", {}).rows
                    seen.append(len(rows))
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

        workers = [threading.Thread(target=work) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertEqual(errors, [])
        self.assertEqual(set(seen), {3})


class TestPostgres(unittest.TestCase):
    def open(self, url="postgresql://u:p@h:5432/d"):
        driver = FakeDriver()
        db = connect(url, driver=driver)
        return db, driver

    def test_passes_the_url_through_to_the_driver(self):
        db, driver = self.open()
        try:
            self.assertEqual(len(driver.connections), 1)
            self.assertEqual(driver.connections[0].dsn,
                             "postgresql://u:p@h:5432/d")
        finally:
            db.close()

    def test_the_postgres_scheme_alias_is_accepted(self):
        db, driver = self.open("postgres://u:p@h:5432/d")
        try:
            self.assertEqual(len(driver.connections), 1)
        finally:
            db.close()

    def test_converts_named_parameters_to_pyformat(self):
        db, driver = self.open()
        try:
            db.run("SELECT * FROM t WHERE id = :id", {"id": 4})
            sql, params = driver.connections[0].calls[-1]
            self.assertEqual(sql, "SELECT * FROM t WHERE id = %(id)s")
            self.assertEqual(params, {"id": 4})
        finally:
            db.close()

    def test_parameters_the_sql_does_not_use_are_dropped(self):
        db, driver = self.open()
        try:
            db.run("SELECT * FROM t WHERE id = :id", {"id": 4, "unused": "x"})
            sql, params = driver.connections[0].calls[-1]
            self.assertEqual(params, {"id": 4})
        finally:
            db.close()

    def test_builds_dict_rows_from_the_cursor_description(self):
        db, driver = self.open()
        try:
            driver.connections[0].result = (["id", "title"],
                                            [(1, "a"), (2, "b")])
            result = db.run("SELECT id, title FROM t", {})
            self.assertEqual(result.rows,
                             [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}])
            self.assertEqual(result.rowcount, 2)
        finally:
            db.close()

    def test_a_statement_returning_no_rows_reports_the_driver_rowcount(self):
        db, driver = self.open()
        try:
            driver.connections[0].result = None
            result = db.run("DELETE FROM t WHERE id = :id", {"id": 1})
            self.assertEqual(result.rows, [])
            self.assertEqual(result.rowcount, 3)
        finally:
            db.close()

    def test_each_run_is_committed(self):
        db, driver = self.open()
        try:
            db.run("DELETE FROM t", {})
            self.assertEqual(driver.connections[0].commits, 1)
        finally:
            db.close()

    def test_close_closes_the_connection(self):
        db, driver = self.open()
        db.close()
        self.assertTrue(driver.connections[0].closed)


class TestUrlErrors(unittest.TestCase):
    def test_unknown_scheme_is_a_config_error(self):
        for url in ("mysql://localhost/db", "notes.db", "", "http://x"):
            with self.subTest(url=url):
                with self.assertRaises(ConfigError):
                    connect(url)


if __name__ == "__main__":
    unittest.main()
