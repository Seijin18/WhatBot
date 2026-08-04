"""Regression test: no unexpected "modalidade"/"modality" vocabulary in
production/deploy-facing files.

`session-item-tracking-rename` renamed the schema for a registered
offering (dataclass, `KnowledgeBase` field, the `.md` heading the parser
looks for, and the text injected into the LLM prompt) from "Modalidade"
(class-schedule-specific, sports-association jargon) to "Item" (neutral
business vocabulary) — see `openspec/changes/session-item-tracking-rename/`.
That is a strict, mechanical rename of the *identifier/schema*, not of the
Portuguese word a customer might actually type: "modalidade"/"modalidades"
remain legitimate trigger-word synonyms for "item"/"itens" in a couple of
places (a customer of a class-schedule business types "quais modalidades
vocês têm?", not "quais itens vocês têm?").

This test is the regression guard for that rename: it scans every
customer/deploy-facing file for "modalidad*" (Portuguese) AND "modalit*"
(the English cognate "modality"/"modalities" — an earlier pass of this
guard only matched the Portuguese spelling and missed a few English
identifiers/docstrings left over from the rename) and fails on anything
not in `_EXPECTED` below. The remaining matches are either
business-agnostic *trigger words* (kept as content, not identifiers) or
historical-narrative comments describing what the code used to be called
before this rename — not a schema/identifier leftover.

Deliberately out of scope:
- `tests/` (other than this file) — `tests/kb_fixtures.py`'s
  `CLASS_SCHEDULE_KB` fixture legitimately models a sports-class business
  as *content* (FAQ answers, "Sobre" prose), and other test files send
  "Quais modalidades vocês têm?" as a simulated customer message — none of
  that is a schema/identifier leftover.
- `docs/*.md`, `openspec/changes/archive/**` — point-in-time historical
  records, not live config; rewriting them would be revisionist.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Matches "modalidade"/"modalidades" (Portuguese, and any other inflection
# of the same stem, e.g. a stray "modalidad" typo) AND "modality"/
# "modalities"/"modal_ref"-style English cognates (e.g. a leftover
# `modality_ref` parameter or `_line_claims_modality` helper).
_PATTERN = re.compile(r"modalidad[a-zà-ú]*|modalit[a-z]*", re.IGNORECASE)

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
    # `_LISTING_SIGNALS`: a customer of a class-schedule business types
    # "modalidade"/"modalidades" to ask "what do you have?" — kept as a
    # content trigger synonym alongside "atividades"; the internal
    # identifier for a registered offering is `Item`, not `Modalidade`.
    "whatbot/intent_router.py": Counter({"modalidade": 4, "modalidades": 3}),
    # `_BASE_INTENT_SIGNALS["horarios"]`: same trigger-word rationale as
    # intent_router.py's `_LISTING_SIGNALS` above.
    "whatbot/knowledge_facts.py": Counter({"modalidade": 4, "modalidades": 2}),
    # `format_grounding_rules_for_prompt` docstring: historical-narrative
    # comment describing wording this method used to fall back to *before*
    # this rename — not a live identifier.
    "whatbot/knowledge.py": Counter({"modalidades": 2}),
    # `update_session_state` docstring: historical-narrative comment
    # naming the pre-rename method (`KnowledgeFacts.match_modalidades`)
    # this function used to call on its own — not a live identifier.
    "whatbot/session_state.py": Counter({"modalidades": 1}),
    # `--help`/usage example showing a simulated customer message.
    "scripts/chat_test.py": Counter({"modalidades": 1}),
}


class TestNoModalidadeLeftovers(unittest.TestCase):
    def test_no_unexpected_modalidade_vocabulary(self) -> None:
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
            "Vocabulário 'modalidade'/'modality' fora do esperado em arquivo "
            "de produção/deploy. Se for um novo resquício de identificador/"
            "schema (português OU inglês), renomeie para 'item'/'itens'; se "
            "for um gatilho de conteúdo legítimo (palavra que um cliente "
            "digitaria) ou um comentário histórico, atualize _EXPECTED "
            "neste teste:\n" + "\n".join(mismatches),
        )


if __name__ == "__main__":
    unittest.main()
