"""Restricted arithmetic evaluator for student-supplied expressions.

PRD v0.2 section 9.1 is explicit on two points, and both shape this module:

* **"never execute learner expressions as general code."** This is a hand-written
  parser, not `eval` or `exec`. Anything outside the arithmetic allowlist is
  rejected before evaluation, so there is no path from an evidence field to the
  Python runtime.
* **"Arithmetic uses exact integers/rationals or defined decimal precision."**
  Evaluation is over `Fraction`, so 1/3 stays one third rather than becoming
  0.3333333333333333. That matters when a student writes `(1/2)/(1/15)` and the
  answer must come out as exactly 7.5, and it is why "0.5" and "1/2" compare
  equal here.

The grammar is deliberately tiny: numbers, `+ - * / ^`, parentheses, unary
minus, and `%` read as "percent of" (`20 % 800` is 160), which is the single
most common operation in Aptitude evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

# Tokens: a number, one of the operators, or a parenthesis. Anything else in
# the input is a syntax error rather than something we try to interpret.
_TOKEN = re.compile(r"\d+\.?\d*|[-+*/^%()]")

# Internal marker for unary minus. Its precedence sits between the
# multiplicative operators and exponentiation, matching Python: -2^2 is -(2^2),
# while 2^-2 is 2^(-2). Encoding unary minus as "0 - x" instead would bind it
# to the wrong side of a right-associative "^" and silently compute -1 for 2^-2.
_UNARY_MINUS = "~"
_PRECEDENCE = {"+": 1, "-": 1, "*": 2, "/": 2, "%": 2, _UNARY_MINUS: 3, "^": 4}
_RIGHT_ASSOCIATIVE = {"^", _UNARY_MINUS}

# Guards against a pathological expression consuming the request thread.
_MAX_LENGTH = 500
_MAX_EXPONENT = 64


class ExpressionError(ValueError):
    """The expression could not be parsed or evaluated."""


@dataclass(frozen=True)
class Evaluation:
    """Result of evaluating one expression."""

    value: Fraction
    normalised: str

    @property
    def as_float(self) -> float:
        return float(self.value)


def evaluate(expression: str) -> Evaluation:
    """Evaluate an arithmetic expression exactly.

    Raises `ExpressionError` for anything the allowlist does not cover -
    function calls, names, comparison operators, or stray characters.
    """
    if not expression or not expression.strip():
        raise ExpressionError("empty expression")
    if len(expression) > _MAX_LENGTH:
        raise ExpressionError(f"expression longer than {_MAX_LENGTH} characters")

    compact = expression.replace(",", "").replace(" ", "")
    tokens = _TOKEN.findall(compact)
    # If re-joining the tokens does not reproduce the input, something was
    # dropped - a letter, a function name, a comparison - and we refuse rather
    # than silently evaluating a different expression from the one written.
    if "".join(tokens) != compact:
        raise ExpressionError(
            "expression contains characters outside the arithmetic allowlist "
            "(numbers, + - * / ^ %, parentheses)"
        )

    rpn = _to_rpn(tokens)
    return _evaluate_rpn(rpn)


def _to_rpn(tokens: list[str]) -> list[str]:
    """Shunting-yard: infix tokens to reverse Polish notation."""
    output: list[str] = []
    operators: list[str] = []
    previous: str | None = None

    for token in tokens:
        if token[0].isdigit():
            output.append(token)
        elif token == "(":
            operators.append(token)
        elif token == ")":
            while operators and operators[-1] != "(":
                output.append(operators.pop())
            if not operators:
                raise ExpressionError("unbalanced parentheses")
            operators.pop()
        elif token == "-" and (
            previous is None or previous == "(" or previous in _PRECEDENCE
        ):
            # Prefix minus. A prefix operator pops nothing: whatever is on the
            # stack binds looser than the operand it is about to consume.
            operators.append(_UNARY_MINUS)
        else:
            if previous is not None and previous in _PRECEDENCE:
                raise ExpressionError(f"two operators in a row near {token!r}")
            while (
                operators
                and operators[-1] != "("
                and (
                    _PRECEDENCE[operators[-1]] > _PRECEDENCE[token]
                    or (
                        _PRECEDENCE[operators[-1]] == _PRECEDENCE[token]
                        and token not in _RIGHT_ASSOCIATIVE
                    )
                )
            ):
                output.append(operators.pop())
            operators.append(token)
        previous = token

    while operators:
        op = operators.pop()
        if op == "(":
            raise ExpressionError("unbalanced parentheses")
        output.append(op)
    return output


def _evaluate_rpn(rpn: list[str]) -> Evaluation:
    stack: list[Fraction] = []
    for token in rpn:
        if token[0].isdigit():
            stack.append(Fraction(token))
            continue
        if token == _UNARY_MINUS:
            if not stack:
                raise ExpressionError("malformed expression")
            stack.append(-stack.pop())
            continue
        if len(stack) < 2:
            raise ExpressionError("malformed expression")
        b = stack.pop()
        a = stack.pop()
        stack.append(_apply(token, a, b))

    if len(stack) != 1:
        raise ExpressionError("malformed expression")
    value = stack[0]
    return Evaluation(value=value, normalised=format_value(value))


def _apply(op: str, a: Fraction, b: Fraction) -> Fraction:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if b == 0:
            raise ExpressionError("division by zero")
        return a / b
    if op == "%":
        # "a % b" means "a percent of b" - the dominant reading in aptitude
        # evidence, e.g. "20 % 800" for 20% of 800.
        return (a / 100) * b
    if op == "^":
        if b.denominator != 1:
            raise ExpressionError("fractional exponents are not supported")
        if abs(b) > _MAX_EXPONENT:
            raise ExpressionError(f"exponent larger than {_MAX_EXPONENT}")
        if a == 0 and b < 0:
            raise ExpressionError("division by zero")
        return a ** int(b)
    raise ExpressionError(f"unknown operator {op!r}")


def format_value(value: Fraction) -> str:
    """Render a Fraction for comparison and display.

    Integers render bare, terminating decimals render as decimals, and a
    repeating fraction keeps its exact form rather than being silently rounded.
    """
    if value.denominator == 1:
        return str(value.numerator)
    as_decimal = value.limit_denominator(10**9)
    # A denominator of only 2s and 5s terminates in base 10.
    d = as_decimal.denominator
    for factor in (2, 5):
        while d % factor == 0:
            d //= factor
    if d == 1:
        text = f"{float(value):.10f}".rstrip("0").rstrip(".")
        return text
    return f"{value.numerator}/{value.denominator}"


def parse_value(text: str) -> Fraction | None:
    """Parse a stated result, accepting equivalent forms.

    "0.5", "1/2" and "50 %" of nothing are not the same thing - only the first
    two are values - so percent signs are stripped as a unit, not applied.
    Returns None when the text is not a bare number.
    """
    cleaned = text.strip().replace(",", "").rstrip("%").strip()
    if not cleaned:
        return None
    try:
        return Fraction(cleaned)
    except (ValueError, ZeroDivisionError):
        pass
    try:
        return Fraction(str(float(cleaned)))
    except (ValueError, OverflowError):
        return None


def values_agree(a: str, b: str, *, tolerance: Fraction | None = None) -> bool:
    """Whether two stated values are the same quantity.

    Exact by default, because that is what `Fraction` buys us; a tolerance is
    accepted for content that legitimately rounds (currency to paise, say).
    """
    left, right = parse_value(a), parse_value(b)
    if left is None or right is None:
        return a.strip() == b.strip()
    if tolerance is None:
        return left == right
    return abs(left - right) <= tolerance
