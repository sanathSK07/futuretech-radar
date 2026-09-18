"""Quote verification: the rule that keeps invented facts out of the database.

Every extracted claim carries a quote that must actually appear in the document
it was taken from. A model that invents a plausible-sounding sentence fails this
check and the claim is discarded. It is the cheapest and most effective of the
grounding rules in docs/04 section G.3, and it is deliberately deterministic:
no model is asked whether a quote is faithful.

What it does not catch, stated plainly so nobody mistakes it for more than it
is: a real quote attached to a misleading paraphrase, or a real quote given the
wrong claim type. Those are what the labelled evaluation set and reviewer
spot-checks exist for.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MIN_QUOTE_CHARACTERS = 24
"""Shorter than this and a quote proves nothing.

"the" appears in every document ever written. Without a floor, a model that
returned single common words would score 100% verification while supporting
nothing at all — the metric would look perfect precisely when the extraction was
worthless.
"""

MAX_QUOTE_CHARACTERS = 600
"""Longer than this is not a quote, it is the document.

A claim whose evidence is six paragraphs has not isolated an assertion, and a
reviewer cannot check it at a glance.
"""

# Typographic characters that mean the same thing as their ASCII equivalents and
# differ between a publisher's HTML, a PDF extraction and a model's output.
_CHARACTER_EQUIVALENTS = {
    "‘": "'",  # left single quote
    "’": "'",  # right single quote / apostrophe
    "‚": "'",
    "“": '"',  # left double quote
    "”": '"',  # right double quote
    "„": '"',
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
    "‒": "-",  # figure dash
    "–": "-",  # en dash
    "—": "-",  # em dash
    "−": "-",  # minus sign
    " ": " ",  # non-breaking space
    " ": " ",
    " ": " ",
    "…": "...",  # ellipsis
    "­": "",  # soft hyphen
    "﻿": "",  # zero-width no-break space
    "​": "",  # zero-width space
}

_HYPHENATED_LINE_BREAK = re.compile(r"-\s*\n\s*")
_WHITESPACE_RUN = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Reduce text to the form both sides of a comparison can agree on.

    Unicode compatibility normalisation first (so a ligature and its two
    letters compare equal), then typographic characters to their ASCII
    equivalents, then hyphenated line breaks rejoined — a PDF that wraps
    "quantum" as "quan-\\ntum" is still the word quantum — then whitespace runs
    collapsed to single spaces.

    Case is preserved. Lowercasing would make the check more forgiving and less
    true: "US" and "us" are not the same token, and a quote that has been
    recapitalised has been edited.
    """
    text = unicodedata.normalize("NFKC", text)
    for character, replacement in _CHARACTER_EQUIVALENTS.items():
        text = text.replace(character, replacement)
    text = _HYPHENATED_LINE_BREAK.sub("", text)
    return _WHITESPACE_RUN.sub(" ", text).strip()


@dataclass(frozen=True, slots=True)
class Verification:
    """The outcome of checking one quote against one document."""

    verified: bool
    reason: str | None = None
    """Why it failed, in words a reviewer can act on. None when it passed."""
    offset: int | None = None
    """Where the quote starts in the normalised source, for a "show me" view."""

    def __bool__(self) -> bool:
        return self.verified


def verify_quote(quote: str, source_text: str) -> Verification:
    """Check that ``quote`` appears in ``source_text`` after normalisation.

    Returns a result rather than raising: the caller records the failure on the
    analysis run and moves on to the next claim, because one bad claim in a
    batch of twenty is a data-quality signal, not an outage.
    """
    normalised_quote = normalise(quote)
    if not normalised_quote:
        return Verification(False, "the quote is empty")
    if len(normalised_quote) < MIN_QUOTE_CHARACTERS:
        return Verification(
            False,
            f"the quote is {len(normalised_quote)} characters; "
            f"at least {MIN_QUOTE_CHARACTERS} are needed to support a claim",
        )
    if len(normalised_quote) > MAX_QUOTE_CHARACTERS:
        return Verification(
            False,
            f"the quote is {len(normalised_quote)} characters; "
            f"over {MAX_QUOTE_CHARACTERS} is an excerpt, not a quote",
        )

    normalised_source = normalise(source_text)
    if not normalised_source:
        return Verification(False, "the source document has no text to check against")

    offset = normalised_source.find(normalised_quote)
    if offset < 0:
        return Verification(False, "the quote does not appear in the source document")
    return Verification(True, offset=offset)


def quote_contains(quote: str, value: str) -> bool:
    """Whether a metric value appears in the quote (grounding rule G.3.4).

    A number in a claim that is not in the quote has been carried over from the
    model's own knowledge, or invented. Compared after normalisation so that
    "99.9%" in the quote matches a value written "99.9 %".
    """
    return normalise(value).replace(" ", "") in normalise(quote).replace(" ", "")
