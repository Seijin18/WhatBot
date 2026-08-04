"""Regression test: no unexpected "associação"/"matrícula" vocabulary in
production/deploy-facing files.

This bot serves whatever business `knowledge/base.md` describes — today
that's a made-to-order product catalog with nothing to do with a sports
association or student enrollment. That vocabulary used to be baked into
the filename, structural section headings, an env var, a Python function
name, and several internal identifiers, all left over from when this
codebase was written for an actual sports association (see
docs/REVISAO_CAMADA_CONVERSACIONAL.md). All of that was renamed away.

This test is the regression guard for that sweep: it scans every
customer/deploy-facing file for "associac*"/"associaç*"/"matricul*" and
fails on anything not in `_EXPECTED` below. The remaining matches are
business-agnostic *trigger words* (e.g. a customer might type "matrícula"
for an enrollment-style business reusing this code) or illustrative
comments — not domain assumptions baked into control flow.

Deliberately out of scope:
- `tests/` (other than this file) — `tests/kb_fixtures.py`'s
  `CLASS_SCHEDULE_KB` fixture legitimately models a sports-class business
  as *content*, to keep that code path under test.
- `docs/*.md`, `openspec/changes/archive/**` — point-in-time historical
  records, not live config; rewriting them would be revisionist.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Matches "associac*"/"associaç*" (associacao, associação, associativa...)
# and "matricul*"/"matrícul*" (matricula, matrícula, matricular...).
_PATTERN = re.compile(r"associa[cç][a\wãáàâ]*|matr[ií]cul\w*", re.IGNORECASE)

_SCAN_GLOBS = (
    "whatbot/**/*.py",
    "scripts/*.py",
    "knowledge/*.md",
    ".env.example",
    "README.md",
)

# Expected match count per file, relative to repo root. A file scoring
# *more* matches than listed here means a new leftover crept in; *fewer*
# means something here should be trimmed down to match reality again.
_EXPECTED: dict[str, Counter] = {
    "whatbot/grounding.py": Counter(
        {"associacao": 1, "associação": 2, "matricula": 2, "matrícula": 2}
    ),
    "whatbot/knowledge_facts.py": Counter({"matrícula": 2, "matricula": 1}),
    "whatbot/priority.py": Counter(
        {"matrícula": 3, "matricula": 2, "matricular": 1}
    ),
}


class TestNoAssociationLeftovers(unittest.TestCase):
    def test_no_unexpected_association_vocabulary(self) -> None:
        seen: set[Path] = set()
        mismatches: list[str] = []
        for pattern in _SCAN_GLOBS:
            for path in sorted(ROOT.glob(pattern)):
                if not path.is_file() or path in seen:
                    continue
                seen.add(path)
                rel = str(path.relative_to(ROOT))
                found = Counter(
                    m.lower() for m in _PATTERN.findall(path.read_text(encoding="utf-8"))
                )
                expected = Counter(
                    {k.lower(): v for k, v in _EXPECTED.get(rel, Counter()).items()}
                )
                if found != expected:
                    mismatches.append(
                        f"{rel}: encontrado={dict(found)} esperado={dict(expected)}"
                    )
        self.assertFalse(
            mismatches,
            "Vocabulário 'associação'/'matrícula' fora do esperado em "
            "arquivo de produção/deploy. Se for um novo resquício de "
            "domínio, remova-o; se for um gatilho de conteúdo legítimo "
            "(ex.: negócio de matrícula/aula reusando este código), "
            "atualize _EXPECTED neste teste:\n" + "\n".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
