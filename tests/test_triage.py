"""Stage-one triage.

Every test here runs against ScriptedClient, so the suite costs nothing and needs
no key. What is pinned is the two things that would be expensive to get wrong: how
an unreadable verdict is handled, and which documents are allowed to skip the
model entirely.
"""

from __future__ import annotations

import pytest

from radar.core.types import SourceKind
from radar.pipeline.llm import HAIKU, ScriptedClient, Usage
from radar.pipeline.triage import (
    DEFAULT_CHUNK_SIZE,
    STAGE_ONE_SYSTEM,
    TOKENS_PER_VERDICT,
    YES,
    Candidate,
    MisalignedChunkError,
    UnreadableVerdictError,
    build_request,
    estimate_tokens,
    needs_screening,
    parse_verdicts,
    prompt_version,
    render_chunk,
    screen,
)


def candidate(
    title: str = "A title",
    *,
    kind: SourceKind = SourceKind.ARXIV_OAI,
    document_id: str = "doc-1",
) -> Candidate:
    return Candidate(document_id=document_id, title=title, source_id="a-source", source_kind=kind)


class TestChunkParsing:
    def test_a_clean_chunk_reads_in_order(self) -> None:
        assert parse_verdicts("1: YES\n2: NO\n3: YES", 3) == [True, False, True]

    @pytest.mark.parametrize("answer", ["YES", "yes", " Yes. ", "YES "])
    def test_a_yes_in_any_plausible_shape(self, answer: str) -> None:
        assert parse_verdicts(f"1:{answer}", 1) == [True]

    def test_blank_lines_are_tolerated(self) -> None:
        assert parse_verdicts("1: YES\n\n2: NO\n", 2) == [True, False]

    def test_a_missing_verdict_refuses_the_whole_chunk(self) -> None:
        """A short list silently shifts every later verdict onto the wrong document.

        This is the one real risk of batching, and it must never be absorbed: a
        verdict attached to the wrong paper becomes a claim about the wrong paper.
        """
        with pytest.raises(MisalignedChunkError, match=r"missing \[2\]"):
            parse_verdicts("1: YES\n3: NO", 3)

    def test_a_duplicate_number_refuses_the_chunk(self) -> None:
        with pytest.raises(MisalignedChunkError, match="more than once"):
            parse_verdicts("1: YES\n1: NO", 2)

    def test_an_invented_number_refuses_the_chunk(self) -> None:
        with pytest.raises(MisalignedChunkError, match="unexpected"):
            parse_verdicts("1: YES\n2: NO\n9: YES", 2)

    def test_a_preamble_refuses_the_chunk(self) -> None:
        with pytest.raises(MisalignedChunkError, match="expected lines like"):
            parse_verdicts("Here are my verdicts:\n1: YES", 1)

    @pytest.mark.parametrize("answer", ["MAYBE", "", "YES because it reports a fidelity", "1"])
    def test_an_unreadable_answer_is_its_own_error(self, answer: str) -> None:
        """Distinct from misalignment: the count was right, the word was not."""
        with pytest.raises(UnreadableVerdictError):
            parse_verdicts(f"1: {answer}", 1)

    def test_the_unreadable_error_says_it_is_not_a_rejection(self) -> None:
        with pytest.raises(UnreadableVerdictError, match=r"[Nn]ot treated as a rejection"):
            parse_verdicts("1: perhaps", 1)


class TestRendering:
    def test_titles_are_numbered_from_one(self) -> None:
        assert render_chunk(["First", "Second"]) == "1: First\n2: Second"

    def test_a_wrapped_title_becomes_one_line(self) -> None:
        """Feeds hard-wrap titles, and a newline inside one would break the
        one-line-per-title contract the parser depends on."""
        assert "\n" not in render_chunk(["A title\nwrapped mid-way"])[3:]


class TestThePrompt:
    def test_it_addresses_the_demonstrate_ambiguity(self) -> None:
        """The exact failure that killed the keyword gate — 971 false passes on
        'we demonstrate that'. If this instruction is ever dropped, the model is
        being asked the question a term list already got wrong."""
        assert "demonstrate" in STAGE_ONE_SYSTEM
        assert "prove" in STAGE_ONE_SYSTEM

    def test_it_names_newsroom_register_as_a_yes(self) -> None:
        """The other half of that failure: a funding announcement and a product
        launch were rejected for containing no academic vocabulary."""
        for phrase in ("funding announcement", "product launch", "regulatory clearance"):
            assert phrase in STAGE_ONE_SYSTEM

    def test_it_states_the_asymmetry_rather_than_asking_for_accuracy(self) -> None:
        """A model told only 'be accurate' balances the errors evenly, and the
        errors are not evenly costly."""
        assert "deletes a piece of evidence" in STAGE_ONE_SYSTEM
        assert f"answer {YES}" in STAGE_ONE_SYSTEM

    def test_it_asks_for_one_numbered_line_per_title(self) -> None:
        assert "one line per title" in STAGE_ONE_SYSTEM
        assert "no explanation" in STAGE_ONE_SYSTEM.lower()
        assert "same order" in STAGE_ONE_SYSTEM

    def test_the_version_follows_the_content(self) -> None:
        """A hand-maintained version makes an eval compare a prompt with itself."""
        assert prompt_version("a") != prompt_version("b")
        assert prompt_version(STAGE_ONE_SYSTEM) == prompt_version()


class TestTheRequest:
    def test_the_output_ceiling_scales_with_the_chunk(self) -> None:
        """A ceiling that truncates the last verdict turns a cost saving into a
        silent alignment failure, so it has to grow with the chunk."""
        small = build_request(["one"]).max_tokens
        large = build_request(["one"] * 50).max_tokens
        assert large > small
        assert large >= 50 * TOKENS_PER_VERDICT

    def test_only_the_titles_are_sent(self) -> None:
        """Every extra token is multiplied by 2,738 a day."""
        assert build_request(["  Logical Qubit Below Threshold  "]).prompt == (
            "1: Logical Qubit Below Threshold"
        )

    def test_the_system_prompt_carries_the_instructions(self) -> None:
        assert build_request(["a title"]).system == STAGE_ONE_SYSTEM

    def test_haiku_by_default(self) -> None:
        assert build_request(["a title"]).model == HAIKU


class TestWhoGetsScreened:
    @pytest.mark.parametrize("kind", [SourceKind.ARXIV_OAI, SourceKind.ARXIV_CATEGORY])
    def test_bulk_preprint_feeds_are_screened(self, kind: SourceKind) -> None:
        assert needs_screening(candidate(kind=kind))

    @pytest.mark.parametrize("kind", [SourceKind.RSS, SourceKind.BIORXIV])
    def test_everything_else_skips_the_model(self, kind: SourceKind) -> None:
        """13 of 2,751 documents came from these on the day it was measured.

        Screening them saves a fraction of a cent and risks the deployment and
        regulatory claims arXiv structurally cannot carry.
        """
        assert not needs_screening(candidate(kind=kind))


class TestScreening:
    def test_a_yes_passes_and_a_no_does_not(self) -> None:
        client = ScriptedClient.answering("1: YES\n2: NO")
        results = list(screen(client, [candidate(document_id="a"), candidate(document_id="b")]))
        assert [(r.document_id, r.passed) for r in results] == [("a", True), ("b", False)]

    def test_one_call_covers_a_whole_chunk(self) -> None:
        """The entire point: the 488-token system prompt is sent once, not 50 times."""
        client = ScriptedClient.answering("\n".join(f"{i}: YES" for i in range(1, 51)))
        candidates = [candidate(document_id=str(i)) for i in range(50)]
        assert len(list(screen(client, candidates))) == 50
        assert len(client.requests) == 1

    def test_a_full_chunk_is_flushed_before_the_next_one_fills(self) -> None:
        client = ScriptedClient.answering("1: YES\n2: NO", "1: YES")
        candidates = [candidate(document_id=str(i)) for i in range(3)]
        results = list(screen(client, candidates, chunk_size=2))
        assert [r.passed for r in results] == [True, False, True]
        assert len(client.requests) == 2

    def test_an_unscreened_document_costs_no_call(self) -> None:
        client = ScriptedClient.answering()
        results = list(screen(client, [candidate(kind=SourceKind.RSS)]))
        assert client.requests == []
        assert results[0].passed
        assert results[0].screened is False

    def test_input_order_survives_mixed_sources(self) -> None:
        """An unscreened document in the middle must not jump the queue, or the
        caller cannot zip results back onto its own list."""
        client = ScriptedClient.answering("1: YES", "1: NO")
        candidates = [
            candidate(document_id="arxiv-1"),
            candidate(document_id="press-1", kind=SourceKind.RSS),
            candidate(document_id="arxiv-2"),
        ]
        results = list(screen(client, candidates))
        assert [r.document_id for r in results] == ["arxiv-1", "press-1", "arxiv-2"]
        assert [r.passed for r in results] == [True, True, False]

    def test_the_prompt_version_is_recorded_on_every_result(self) -> None:
        client = ScriptedClient.answering("1: YES")
        result = next(iter(screen(client, [candidate()])))
        assert result.prompt_version == prompt_version()

    def test_usage_accumulates_when_asked(self) -> None:
        usage = Usage(batch=True)
        client = ScriptedClient.answering("1: YES\n2: NO\n3: YES")
        list(screen(client, [candidate(document_id=str(i)) for i in range(3)], usage=usage))
        assert usage.calls == 1
        assert usage.estimated_cost_usd > 0

    def test_unscreened_documents_do_not_appear_in_usage(self) -> None:
        usage = Usage()
        client = ScriptedClient.answering("1: YES")
        list(screen(client, [candidate(kind=SourceKind.RSS), candidate()], usage=usage))
        assert usage.calls == 1


class TestMisalignmentRecovery:
    """The one real risk of batching, and what it costs to survive it."""

    def test_a_misaligned_chunk_is_halved_and_retried(self) -> None:
        client = ScriptedClient.answering(
            "1: YES\n2: NO",  # four sent, two answered
            "1: YES\n2: NO",  # first half
            "1: NO\n2: YES",  # second half
        )
        candidates = [candidate(document_id=str(i)) for i in range(4)]
        results = list(screen(client, candidates, chunk_size=4))
        assert [r.passed for r in results] == [True, False, False, True]
        assert len(client.requests) == 3

    def test_recovery_bottoms_out_rather_than_recursing_forever(self) -> None:
        """At one title a misalignment is a genuine parse failure, not a counting
        one, and is allowed to propagate."""
        client = ScriptedClient(
            responses=[
                r
                for _ in range(8)
                for r in [ScriptedClient.answering("nonsense with no numbers").responses[0]]
            ]
        )
        with pytest.raises(MisalignedChunkError):
            list(screen(client, [candidate(document_id=str(i)) for i in range(2)], chunk_size=2))

    def test_the_default_chunk_size_is_worth_the_risk(self) -> None:
        """Documented as a deliberate trade rather than a magic number."""
        assert DEFAULT_CHUNK_SIZE == 50


class TestEstimation:
    def test_it_is_roughly_four_characters_per_token(self) -> None:
        assert estimate_tokens("a" * 400) == 100

    def test_it_never_returns_zero(self) -> None:
        """A zero would make a dry-run cost estimate come out free."""
        assert estimate_tokens("") == 1
        assert estimate_tokens("ab") == 1
