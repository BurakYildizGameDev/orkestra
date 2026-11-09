"""``regex`` verifier: patterns that must (not) appear in the answer (Mimari §10).

Patterns are searched with ``re.MULTILINE``, so ``^`` and ``$`` match at line boundaries.
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
        for pattern in self.must_match:
            if not re.search(pattern, ctx.output, re.MULTILINE):
                return failed(self.type, Message("verify.regex.missing", {"pattern": pattern}))
        for pattern in self.must_not_match:
            if re.search(pattern, ctx.output, re.MULTILINE):
                return failed(self.type, Message("verify.regex.forbidden", {"pattern": pattern}))
        return passed(self.type)
