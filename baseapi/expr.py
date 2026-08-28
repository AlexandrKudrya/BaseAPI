"""A small, safe expression language.

This module is pure: no I/O, no clock, no environment access. It is the
hand-written tokenizer and recursive-descent parser behind the ``checks`` and
``response.fields`` sections of an endpoint file.

Grammar, loosest to tightest binding::

    or
    and
    not
    comp:  == != < <= > >= in "not in"
    primary: literal | root.name | '(' expression ')'

The only permitted path roots are ``params``, ``auth``, ``row``, ``rows`` and
``result``. ``eval``/``exec``/``compile`` are never used.
"""

from baseapi.errors import ConfigError

# The only roots a path may start with.
_ALLOWED_ROOTS = frozenset(("params", "auth", "row", "rows", "result"))
# Words that are literals, not paths.
_LITERAL_WORDS = {"true": True, "false": False, "null": None}
# Words that are operators and so are not valid in a primary position.
_OPERATOR_WORDS = frozenset(("and", "or", "not", "in"))


def parse(source):
    """Parse ``source`` into a callable ``f(context) -> value``.

    All validation happens here — an unknown root name or a syntax error
    raises ``ConfigError`` before the returned callable is ever invoked.
    """
    tokens = _tokenize(source)
    parser = _Parser(tokens)
    node = parser.parse_expression()
    parser.expect_eof()
    return node


# --------------------------------------------------------------------------
# Tokenizer
# --------------------------------------------------------------------------


def _tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c in " \t\r\n":
            i += 1
            continue

        if c.isdigit() or (c == "." and i + 1 < n and source[i + 1].isdigit()):
            j = i
            is_float = False
            while j < n and source[j].isdigit():
                j += 1
            if j < n and source[j] == "." and j + 1 < n and source[j + 1].isdigit():
                is_float = True
                j += 1
                while j < n and source[j].isdigit():
                    j += 1
            text = source[i:j]
            value = float(text) if is_float else int(text)
            tokens.append(("num", value, i))
            i = j
            continue

        if c in "'\"":
            quote = c
            j = i + 1
            chars = []
            while j < n:
                if source[j] == quote:
                    if j + 1 < n and source[j + 1] == quote:
                        chars.append(quote)
                        j += 2
                        continue
                    j += 1
                    break
                chars.append(source[j])
                j += 1
            else:
                raise ConfigError("unterminated string literal in expression")
            tokens.append(("str", "".join(chars), i))
            i = j
            continue

        if c.isalpha() or c == "_":
            j = i
            while j < n and (source[j].isalnum() or source[j] == "_"):
                j += 1
            tokens.append(("name", source[i:j], i))
            i = j
            continue

        if c == "(":
            tokens.append(("lparen", c, i))
            i += 1
            continue
        if c == ")":
            tokens.append(("rparen", c, i))
            i += 1
            continue
        if c == ".":
            tokens.append(("dot", c, i))
            i += 1
            continue

        if c == "=":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(("op", "==", i))
                i += 2
                continue
            raise ConfigError("unexpected '=' in expression")
        if c == "!":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(("op", "!=", i))
                i += 2
                continue
            raise ConfigError("unexpected '!' in expression")
        if c == "<":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(("op", "<=", i))
                i += 2
                continue
            tokens.append(("op", "<", i))
            i += 1
            continue
        if c == ">":
            if i + 1 < n and source[i + 1] == "=":
                tokens.append(("op", ">=", i))
                i += 2
                continue
            tokens.append(("op", ">", i))
            i += 1
            continue

        raise ConfigError("unexpected character %r in expression" % c)

    tokens.append(("eof", None, n))
    return tokens


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens):
        self._tokens = tokens
        self._pos = 0

    def _current(self):
        return self._tokens[self._pos]

    def _peek(self, offset=1):
        idx = self._pos + offset
        return self._tokens[idx] if idx < len(self._tokens) else self._tokens[-1]

    def _advance(self):
        tok = self._tokens[self._pos]
        if tok[0] != "eof":
            self._pos += 1
        return tok

    def _fail(self, message):
        raise ConfigError("invalid expression: " + message)

    def expect_eof(self):
        if self._current()[0] != "eof":
            self._fail("unexpected trailing token")

    def parse_expression(self):
        return self._parse_or()

    def _parse_or(self):
        node = self._parse_and()
        while self._current()[0] == "name" and self._current()[1] == "or":
            self._advance()
            right = self._parse_and()
            node = _op_logical("or", node, right)
        return node

    def _parse_and(self):
        node = self._parse_not()
        while self._current()[0] == "name" and self._current()[1] == "and":
            self._advance()
            right = self._parse_not()
            node = _op_logical("and", node, right)
        return node

    def _parse_not(self):
        if self._current()[0] == "name" and self._current()[1] == "not":
            self._advance()
            return _op_not(self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self):
        left = self._parse_primary()
        op = self._match_comparison_op()
        if op is None:
            return left
        right = self._parse_primary()
        return _op_comparison(op, left, right)

    def _match_comparison_op(self):
        tok = self._current()
        if tok[0] == "op":
            self._advance()
            return tok[1]
        if tok[0] == "name":
            word = tok[1]
            if word == "in":
                self._advance()
                return "in"
            if word == "not":
                nxt = self._peek()
                if nxt[0] == "name" and nxt[1] == "in":
                    self._advance()
                    self._advance()
                    return "not in"
        return None

    def _parse_primary(self):
        tok = self._current()
        kind = tok[0]
        if kind == "num":
            self._advance()
            return _constant(tok[1])
        if kind == "str":
            self._advance()
            return _constant(tok[1])
        if kind == "name":
            word = tok[1]
            if word in _LITERAL_WORDS:
                self._advance()
                return _constant(_LITERAL_WORDS[word])
            if word in _OPERATOR_WORDS:
                self._fail("unexpected operator %r" % word)
            return self._parse_path()
        if kind == "lparen":
            self._advance()
            node = self.parse_expression()
            if self._current()[0] != "rparen":
                self._fail("missing closing parenthesis")
            self._advance()
            return node
        self._fail("unexpected token %r" % (tok[1],))

    def _parse_path(self):
        root_tok = self._advance()
        root = root_tok[1]
        if root not in _ALLOWED_ROOTS:
            raise ConfigError("unknown root %r in expression" % root)
        if self._current()[0] != "dot":
            self._fail("expected '.' after %r" % root)
        self._advance()
        attr_tok = self._current()
        if attr_tok[0] != "name":
            self._fail("expected an attribute name after %r." % root)
        self._advance()
        return _path(root, attr_tok[1])


# --------------------------------------------------------------------------
# Node constructors (each returns a closure ``context -> value``)
# --------------------------------------------------------------------------


def _constant(value):
    return lambda context: value


def _path(root, name):
    def evaluate(context):
        container = context.get(root)
        if isinstance(container, dict):
            return container.get(name)
        return None

    return evaluate


def _op_logical(op, left, right):
    if op == "or":
        return lambda c: bool(left(c) or right(c))
    return lambda c: bool(left(c) and right(c))


def _op_not(operand):
    return lambda c: bool(not operand(c))


def _op_comparison(op, left, right):
    if op in ("<", "<=", ">", ">="):
        def evaluate(context):
            l = left(context)
            r = right(context)
            if l is None or r is None:
                return False
            if op == "<":
                return l < r
            if op == "<=":
                return l <= r
            if op == ">":
                return l > r
            return l >= r

        return evaluate

    if op == "in":
        def evaluate(context):
            r = right(context)
            if r is None:
                return False
            return left(context) in r

        return evaluate

    if op == "not in":
        def evaluate(context):
            r = right(context)
            if r is None:
                return False
            return left(context) not in r

        return evaluate

    if op == "==":
        return lambda c: left(c) == right(c)
    return lambda c: left(c) != right(c)
