"""The one rule for when a software decision needs a comment.

Every place that records a software decision applies this: the review page, the
products and publishers pages, the product page, the client page and the Issues
bar. A decision is high effect when it reaches many titles or raises findings on
every installed copy, so it must say why. The comment is stored as the
decision's reason.
"""

from __future__ import annotations

COMMENT_MAX_LENGTH = 500


def is_high_effect(decision: str, *, publisher_level: bool) -> bool:
    """Publisher decisions reach every title of the publisher; a reject raises a finding per copy."""
    return publisher_level or decision == "reject"


def comment_problem(decision: str, *, publisher_level: bool, comment: str | None) -> str:
    """Why this decision cannot be recorded yet, or an empty string."""
    comment = (comment or "").strip()
    if len(comment) > COMMENT_MAX_LENGTH:
        return f"Keep the comment to {COMMENT_MAX_LENGTH} characters or fewer."
    if is_high_effect(decision, publisher_level=publisher_level) and not comment:
        return (
            "A comment is required for this decision because it affects many "
            "titles or computers. Say why."
        )
    return ""
