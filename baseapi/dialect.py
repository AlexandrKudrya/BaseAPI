"""Named SQL parameter discovery and pyformat conversion.

Small pure helpers. ``param_names`` finds every ``:name`` placeholder in order
of first appearance; ``to_pyformat`` rewrites placeholders to the ``%(name)s``
style that the PostgreSQL DB-API driver expects. Both scan the statement
character by character so that occurrences inside ``'single quoted'`` strings
(with ``''`` as an escape) and ``"double quoted"`` identifiers are skipped, and
so that PostgreSQL ``::type`` casts never start a placeholder.
"""


def _is_ident_start(ch):
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z") or ch == "_"


def _is_ident_char(ch):
    return _is_ident_start(ch) or ("0" <= ch <= "9")


def param_names(sql):
    """Return every ``:name`` placeholder, in order of first appearance."""
    found = []
    seen = set()
    for name in _scan(sql):
        if name not in seen:
            seen.add(name)
            found.append(name)
    return found


def to_pyformat(sql):
    """Rewrite ``:name`` to ``%(name)s`` and every literal ``%`` to ``%%``."""
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            out.append(ch)
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out.append("''")
                        i += 2
                        continue
                    out.append("'")
                    i += 1
                    break
                if sql[i] == "%":
                    out.append("%%")
                    i += 1
                    continue
                out.append(sql[i])
                i += 1
            continue

        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        out.append('""')
                        i += 2
                        continue
                    out.append('"')
                    i += 1
                    break
                if sql[i] == "%":
                    out.append("%%")
                    i += 1
                    continue
                out.append(sql[i])
                i += 1
            continue

        if ch == ":":
            if i + 1 < n and sql[i + 1] == ":":
                out.append("::")
                i += 2
                continue
            j = i + 1
            if j < n and _is_ident_start(sql[j]):
                k = j
                while k < n and _is_ident_char(sql[k]):
                    k += 1
                name = sql[j:k]
                out.append("%%(%s)s" % name)
                i = k
                continue
            out.append(":")
            i += 1
            continue

        if ch == "%":
            out.append("%%")
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _scan(sql):
    """Yield ``:name`` placeholder names without regard to duplicates."""
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        if ch == '"':
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        if ch == ":":
            if i + 1 < n and sql[i + 1] == ":":
                i += 2
                continue
            j = i + 1
            if j < n and _is_ident_start(sql[j]):
                k = j
                while k < n and _is_ident_char(sql[k]):
                    k += 1
                yield sql[j:k]
                i = k
                continue
            i += 1
            continue

        i += 1
