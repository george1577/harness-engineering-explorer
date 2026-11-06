"""Specs (test suites) and candidate implementations used across the tabs.

The original spec is copied verbatim from the notebook. The others are variants that make
specific harness paths fire.
"""

SPEC_FILE = "test_slugify.py"
TARGET_FILE = "slugify.py"

_HEADER = '''\
import unittest
from slugify import slugify


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Hello World"), "hello-world")

    def test_punctuation(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_collapses_space(self):
        self.assertEqual(slugify("  Hello   World  "), "hello-world")
'''

SPECS = {
    "Notebook spec (3 tests)": _HEADER,
    "+ test_unicode (stricter)": _HEADER + '''
    def test_unicode(self):
        self.assertEqual(slugify("Café Déjà Vu"), "cafe-deja-vu")
''',
    "+ test_contradiction (impossible)": _HEADER + '''
    def test_contradiction(self):
        # Contradicts test_basic: no implementation can pass both.
        self.assertEqual(slugify("Hello World"), "hello_world")
''',
}

DEFAULT_SPEC = "Notebook spec (3 tests)"


def task_for(spec: str) -> str:
    """The notebook's task message, wrapping a spec."""
    return ("Implement slugify(text) in slugify.py so this test suite "
            f"passes:\n\n{spec}")


# --- Candidate implementations (tab ③) ------------------------------------------------------

CORRECT = '''\
import re


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
'''

CORRECT_UNICODE = '''\
import re
import unicodedata


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
'''

NAIVE = '''\
def slugify(text: str) -> str:
    return text.lower().replace(" ", "-")
'''

NO_COLLAPSE = '''\
def slugify(text: str) -> str:
    kept = "".join(c for c in text.lower() if c.isalnum() or c == " ")
    return kept.strip().replace(" ", "-")
'''

SYNTAX_ERROR = '''\
def slugify(text: str) -> str
    return text.lower()
'''

INFINITE_LOOP = '''\
def slugify(text: str) -> str:
    while "  " in text or True:   # oops: never ends
        text = text.replace("  ", " ")
    return text
'''

CANDIDATES = {
    "Correct (regex)": CORRECT,
    "Correct + handles accents": CORRECT_UNICODE,
    "Naive (lower + replace spaces)": NAIVE,
    "Drops punctuation, forgets to collapse spaces": NO_COLLAPSE,
    "Syntax error": SYNTAX_ERROR,
    "Infinite loop (hits the timeout)": INFINITE_LOOP,
    "Nothing written (file missing)": None,
}
