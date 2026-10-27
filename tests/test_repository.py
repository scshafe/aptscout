"""Repository checks: the skeleton's parts exist and the brief's rules hold."""

import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {".git", ".venv", "node_modules", "build", "dist", ".cache"}
# A tailnet hostname ends in the label before "ts.net". The only label
# allowed is the placeholder "<tailnet>" (docs/brief.md: never write the
# tailnet's name).
SUFFIX = ".ts" + ".net"  # split so this file does not match itself
TS_NET = re.compile(r"([A-Za-z0-9<>_-]+)" + re.escape(SUFFIX) + r"\b")
PLACEHOLDER = "<tailnet>"
# The owner's apartments, rents, rankings and notes are runtime data on the
# laptop (docs/brief.md). Files shaped like a database, a backup or secrets
# are never tracked.
PRIVATE_FILE = re.compile(
    r"(\.(db|sqlite|sqlite3|dump|bak)$|\.db-(wal|shm|journal)$|(^|/)\.env(\..*)?$)"
)
# The one exception: the stack's list of host .env names (DEPLOY-03), which
# must hold names only, never a value (checked below).
ENV_EXAMPLE = "deploy/stack/.env.example"
NAME_ONLY_LINE = re.compile(r"^([A-Z][A-Z0-9_]*=\s*(#.*)?|#.*|\s*)$")


def text_files():
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8") as handle:
                    yield os.path.relpath(path, ROOT), handle.read()
            except (UnicodeDecodeError, OSError):
                continue


def tracked_files():
    """The files git tracks, or every file when this is not a git checkout."""
    try:
        out = subprocess.run(
            ["git", "-C", ROOT, "ls-files", "-z"],
            check=True, capture_output=True,
        ).stdout.decode("utf-8")
        return [p for p in out.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = []
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for name in filenames:
                files.append(os.path.relpath(os.path.join(dirpath, name), ROOT))
        return files


class SkeletonTest(unittest.TestCase):
    def test_parts_exist(self):
        for part in ("web", "server", "data"):
            with self.subTest(part=part):
                self.assertTrue(
                    os.path.isfile(os.path.join(ROOT, part, "README.md")),
                    f"{part}/README.md is missing",
                )

    def test_brief_exists(self):
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "docs", "brief.md")))


class TailnetNameTest(unittest.TestCase):
    def test_placeholder_matches(self):
        self.assertEqual(TS_NET.findall("aptscout." + PLACEHOLDER + SUFFIX), [PLACEHOLDER])
        self.assertEqual(TS_NET.findall("host.example-name" + SUFFIX), ["example-name"])

    def test_no_tailnet_name_in_repository(self):
        found = []
        for rel, text in text_files():
            for label in TS_NET.findall(text):
                if label != PLACEHOLDER:
                    found.append(rel)
        self.assertEqual(found, [], "write <tailnet> instead of the tailnet's name")


class OwnerDataTest(unittest.TestCase):
    def test_private_file_pattern(self):
        for path in ("app.db", "x/y.sqlite3", "a.db-wal", ".env", "server/.env.local", "d.dump"):
            with self.subTest(path=path):
                self.assertRegex(path, PRIVATE_FILE)
        for path in ("server/db.go", "docs/environment.md", "web/dashboard.ts"):
            with self.subTest(path=path):
                self.assertNotRegex(path, PRIVATE_FILE)

    def test_data_holds_only_its_readme(self):
        extra = [
            p for p in tracked_files()
            if p.startswith("data/") and p != "data/README.md"
        ]
        self.assertEqual(extra, [], "datasets and owner data are never committed under data/")

    def test_no_database_backup_or_env_file_tracked(self):
        found = [p for p in tracked_files() if PRIVATE_FILE.search(p) and p != ENV_EXAMPLE]
        self.assertEqual(found, [], "the owner's data is runtime data on the laptop, never in git")

    def test_env_example_holds_names_only(self):
        with open(os.path.join(ROOT, ENV_EXAMPLE), encoding="utf-8") as handle:
            lines = handle.read().splitlines()
        self.assertTrue(lines)
        bad = [n for n, line in enumerate(lines, 1) if not NAME_ONLY_LINE.match(line)]
        self.assertEqual(bad, [], f"{ENV_EXAMPLE} lists names only (NAME= with no value)")

    def test_name_only_line(self):
        for line in ("NAME=", "A_B2=   # a comment", "# x", ""):
            with self.subTest(line=line):
                self.assertRegex(line, NAME_ONLY_LINE)
        for line in ("NAME=value", "NAME=value # c", "name=", "export NAME="):
            with self.subTest(line=line):
                self.assertNotRegex(line, NAME_ONLY_LINE)


if __name__ == "__main__":
    unittest.main()
