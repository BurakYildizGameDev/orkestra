"""``regex`` verifier: patterns that must (not) appear in the answer (Mimari §10).

Patterns are searched with ``re.MULTILINE``, so ``^`` and ``$`` match at line boundaries.
Every failing pattern is reported, so one round of feedback can fix all of them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orkestra.verify.base import CheckResult, Message, VerifyContext, failed, passed


@dataclass(frozen=True)
class RegexCheck:
    must_match: tuple[str, ...]
    must_not_match: tuple[str, ...]
    type: str = "regex"

    async def check(self, ctx: VerifyContext) -> CheckResult:
        problems = [
            Message("verify.regex.missing", {"pattern": p})
            for p in self.must_match
            if not re.search(p, ctx.output, re.MULTILINE)
        ]
        problems += [
            Message("verify.regex.forbidden", {"pattern": p})
            for p in self.must_not_match
            if re.search(p, ctx.output, re.MULTILINE)
        ]
        return failed(self.type, problems) if problems else passed(self.type)
