"""The `radar` command line.

radar sources list          show the registry
radar sources sync          write the registry into the database
radar ingest --since 1d     poll active sources for the last day
radar label export          write a worksheet of documents to label by hand
radar label check FILE      verify the labels, including every quote
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import structlog
from pydantic import ValidationError
from sqlalchemy import select

from radar.core.db import session_scope
from radar.core.models import FetchRun, Source, SourceDocument
from radar.core.settings import Settings, get_settings
from radar.core.types import FetchStatus
from radar.pipeline.http import SafeHttpClient
from radar.pipeline.ingest import build_fetcher, host_for, ingest_all, parse_since
from radar.pipeline.labelling import (
    DEFAULT_PER_DOMAIN,
    DEFAULT_SEED,
    check_worksheet,
    coverage,
    format_report,
    missing_domains,
    parse_worksheet,
    render_worksheet,
    select_documents,
)
from radar.pipeline.llm import BATCH_DISCOUNT, HAIKU, PRICES
from radar.pipeline.prefilter import assess, load_vocabulary
from radar.pipeline.ratelimit import LimiterRegistry
from radar.pipeline.registry import DEFAULT_REGISTRY_PATH, load_registry, sync_registry
from radar.pipeline.triage import (
    DEFAULT_CHUNK_SIZE,
    STAGE_ONE_SYSTEM,
    TOKENS_PER_VERDICT,
    Candidate,
    estimate_tokens,
    needs_screening,
    prompt_version,
)


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=settings.log_level.upper())
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper())
        ),
    )


def cmd_sources_list(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    active = registry.active_sources
    print(f"{len(registry.sources)} sources, {len(active)} active\n")
    for spec in registry.sources:
        mark = " " if spec.active else "-"
        domains = ",".join(spec.domains) or "-"
        interval = spec.rate_limit.min_interval_seconds
        print(
            f"{mark} {spec.id:<32} {spec.tier:<3} {spec.kind:<16} {domains:<28} {interval:>5.1f}s"
        )
    if len(active) != len(registry.sources):
        print("\n'-' marks an inactive source: declared, but its fetcher is not built yet.")
    return 0


def cmd_sources_sync(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    with session_scope() as session:
        created, updated = sync_registry(session, registry)
    print(f"sources synced: {created} created, {updated} updated")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    settings = get_settings()
    if not settings.crawler_contact:
        print(
            "RADAR_CRAWLER_CONTACT is not set. Source operators must be able to reach us,\n"
            "so ingestion refuses to run without a contact address. Set it in .env.",
            file=sys.stderr,
        )
        return 2

    registry = load_registry(args.registry)
    since = parse_since(args.since)
    print(f"ingesting documents published since {since.isoformat()}")

    with session_scope() as session:
        sync_registry(session, registry)
        runs = ingest_all(
            session,
            registry,
            settings,
            since=since,
            only=args.source,
            limit=args.limit,
        )

    # A source that failed and then recovered has two runs; the last one is
    # what happened, and a summary that shows both reads as two failures.
    final: dict[str, FetchRun] = {}
    for run in runs:
        final[str(run.source_id)] = run
    outcomes = list(final.values())

    total_fetched = sum(r.fetched_count for r in runs)
    total_new = sum(r.new_count for r in runs)
    failed = [r for r in outcomes if r.status == FetchStatus.ERROR]
    recovered = len(runs) - len(outcomes) - len(failed)

    print(f"\n{len(outcomes)} sources polled: {total_fetched} documents seen, {total_new} new")
    if recovered > 0:
        print(f"{recovered} source(s) failed first and succeeded on the retry pass")
    for run in outcomes:
        flag = "ok " if run.status == FetchStatus.OK else "ERR"
        line = f"  {flag} {run.source_id:<32} fetched={run.fetched_count:<5} new={run.new_count}"
        if run.error:
            line += f"  {run.error}"
        print(line)

    if failed:
        print(f"\n{len(failed)} source(s) failed; their errors are recorded in fetch_run.")
        return 1
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    """Fetch a few documents from a live source and print them. Writes nothing.

    This is the check that the parser still matches the real feed. Fixtures are
    written against the published API documentation, and documentation drifts;
    running this occasionally is how that drift gets caught.
    """
    settings = get_settings()
    if not settings.crawler_contact:
        print("RADAR_CRAWLER_CONTACT is not set; refusing to fetch.", file=sys.stderr)
        return 2

    registry = load_registry(args.registry)
    spec = registry.get(args.source)
    limiter = LimiterRegistry().for_host(host_for(spec), spec.rate_limit.min_interval_seconds)

    print(f"live fetch from {spec.id} ({spec.name})")
    print(f"rate limit: one request every {spec.rate_limit.min_interval_seconds:.1f}s\n")

    with SafeHttpClient(contact=settings.crawler_contact, limiter=limiter) as client:
        fetcher = build_fetcher(spec, client)
        since = parse_since(args.since)
        shown = 0
        for document in fetcher.discover(since):
            shown += 1
            print(f"[{shown}] {document.external_id}  {document.published_at}")
            print(f"     {document.title}")
            authors = ", ".join(a["name"] for a in document.authors[:3]) or "(none parsed)"
            print(f"     authors: {authors}")
            print(f"     ids: {document.canonical_ids}")
            abstract = (document.abstract or "")[:120].replace("\n", " ")
            print(f"     abstract: {abstract}...")
            print(f"     url: {document.url}")
            print(f"     hash: {document.content_hash[:16]}\n")
            if shown >= args.count:
                break

    if shown == 0:
        print("No documents returned. Either the window is too narrow, or parsing failed.")
        return 1
    print(f"{shown} documents parsed successfully. Nothing was written to the database.")
    return 0


def cmd_label_export(args: argparse.Namespace) -> int:
    """Write a worksheet of documents for a person to label."""
    out = Path(args.out)
    if out.exists() and not args.force:
        print(
            f"{out} already exists. Overwriting would discard labelling work,\n"
            "so this refuses by default. Pass --force if you meant it.",
            file=sys.stderr,
        )
        return 2

    with session_scope() as session:
        documents = select_documents(session, per_domain=args.per_domain, seed=args.seed)
        if not documents:
            print(
                "No documents with abstracts are in the database. Run 'radar ingest' first.",
                file=sys.stderr,
            )
            return 1
        worksheet = render_worksheet(documents, seed=args.seed)
        counts = coverage(documents)
        absent = missing_domains(session, documents)

    out.write_text(worksheet, encoding="utf-8")
    print(f"wrote {len(documents)} documents to {out}")
    for domain in sorted(counts):
        print(f"  {domain:<18} {counts[domain]}")
    if absent:
        print(
            f"\nno documents for: {', '.join(absent)}. Those domains have a source "
            "declared but nothing ingested, so this set cannot speak for them."
        )
    print(f"\nseed {args.seed} - rerunning with the same seed gives the same documents")
    print("\nFill it in, then run: radar label check " + str(out))
    return 0


def cmd_label_check(args: argparse.Namespace) -> int:
    """Validate a filled-in worksheet, verifying every quote against its source."""
    path = Path(args.file)
    if not path.exists():
        print(f"{path} does not exist.", file=sys.stderr)
        return 2

    try:
        labelled = parse_worksheet(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        print(f"{path} is not a valid worksheet:\n{exc}", file=sys.stderr)
        return 1

    with session_scope() as session:
        report = check_worksheet(session, labelled)

    print(format_report(report))
    return 0 if report.ok else 1


def cmd_prefilter_report(args: argparse.Namespace) -> int:
    """Measure the triage gate against stored documents. Writes nothing.

    This exists so the gate can be judged before anything depends on it. A gate
    that rejects 95% is a cost saving; one that rejects 99.8% is a bug that
    would have quietly starved the pipeline, and the only way to tell them apart
    is to run it over a real day's corpus and read the samples.
    """
    try:
        vocabulary = load_vocabulary(args.vocabulary)
    except (FileNotFoundError, ValidationError) as exc:
        print(f"cannot read {args.vocabulary}: {exc}", file=sys.stderr)
        return 2

    passed = 0
    rejected = 0
    reasons: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    signals: Counter[str] = Counter()
    by_source: dict[str, list[int]] = {}
    examples: dict[bool, list[tuple[str, str]]] = {True: [], False: []}

    with session_scope() as session:
        rows = session.execute(
            select(
                SourceDocument.source_id, SourceDocument.title, SourceDocument.abstract
            ).order_by(SourceDocument.retrieved_at.desc())
        ).all()

        for source_id, title, abstract in rows:
            verdict = assess(title, abstract, vocabulary)
            tally = by_source.setdefault(source_id, [0, 0])
            if verdict.passed:
                passed += 1
                tally[0] += 1
                domains.update(verdict.domains)
                signals.update(verdict.signals)
            else:
                rejected += 1
                tally[1] += 1
                reasons[verdict.reason.split(":")[0]] += 1
            bucket = examples[verdict.passed]
            if len(bucket) < args.samples:
                bucket.append((title[:96], verdict.reason))

    total = passed + rejected
    if total == 0:
        print("No documents in the database. Run 'radar ingest' first.", file=sys.stderr)
        return 1

    print(f"rule_version {vocabulary.rule_version}   vocabulary {args.vocabulary}")
    print(f"{total} documents: {passed} would reach a model, {rejected} would not")
    print(f"  pass rate {passed / total:.1%}\n")

    print("by source (pass/reject):")
    for source_id in sorted(by_source):
        kept, dropped = by_source[source_id]
        share = kept / (kept + dropped) if kept + dropped else 0.0
        print(f"  {source_id:<28} {kept:>6} / {dropped:<6}  {share:>6.1%}")

    print("\nwhy documents were held back:")
    for reason, count in reasons.most_common():
        print(f"  {count:>6}  {reason}")

    print("\ndomains among passes:")
    for domain, count in domains.most_common():
        print(f"  {count:>6}  {domain}")

    print("\nclaim signals among passes:")
    for signal, count in signals.most_common():
        print(f"  {count:>6}  {signal}")

    for verdict_passed, heading in ((True, "sample passes"), (False, "sample rejections")):
        print(f"\n{heading}:")
        for title, reason in examples[verdict_passed]:
            print(f"  {title}\n      {reason}")

    print("\nNothing was written. Read the samples before trusting the rate.")
    return 0


def cmd_triage_estimate(args: argparse.Namespace) -> int:
    """Print what stage one would send and what it would cost. Makes no calls.

    Deliberately available before an API key is configured, so the bill can be
    read before it is incurred rather than explained afterwards. The token counts
    are a four-characters-per-token approximation; the first real run replaces
    them with measured counts and these should be ignored in favour of those.
    """
    candidates: list[Candidate] = []
    with session_scope() as session:
        rows = session.execute(
            select(
                SourceDocument.id,
                SourceDocument.title,
                SourceDocument.source_id,
                Source.kind,
            )
            .join(Source, Source.id == SourceDocument.source_id)
            .order_by(SourceDocument.retrieved_at.desc())
        ).all()
        candidates = [
            Candidate(
                document_id=str(document_id), title=title, source_id=source_id, source_kind=kind
            )
            for document_id, title, source_id, kind in rows
        ]

    if not candidates:
        print("No documents in the database. Run 'radar ingest' first.", file=sys.stderr)
        return 1

    screened = [c for c in candidates if needs_screening(c)]
    skipped = len(candidates) - len(screened)

    chunk_size = args.chunk_size
    chunks = max(1, -(-len(screened) // chunk_size))  # ceiling division
    system_tokens = estimate_tokens(STAGE_ONE_SYSTEM)
    title_tokens = sum(estimate_tokens(c.title) for c in screened)
    # The system prompt is sent once per chunk, not once per document. Getting
    # this wrong by a factor of the chunk size is exactly the error ADR-0008 made.
    input_tokens = chunks * system_tokens + title_tokens
    output_tokens = len(screened) * TOKENS_PER_VERDICT

    price = PRICES[args.model]
    million = Decimal("1000000")
    discount = Decimal("1") if args.list_price else BATCH_DISCOUNT
    cost = discount * (
        price.input_per_mtok * Decimal(input_tokens) / million
        + price.output_per_mtok * Decimal(output_tokens) / million
    )

    print(f"prompt_version {prompt_version()}   model {args.model}")
    print(f"{len(candidates)} documents stored")
    print(f"  {len(screened)} would be screened by stage one")
    print(f"  {skipped} skip the model entirely (non-arXiv sources go straight to stage two)")
    print(f"\nestimated tokens: {input_tokens:,} in, {output_tokens:,} out")
    print(f"  system prompt is {system_tokens:,} tokens, sent once per document")
    rate = "list" if args.list_price else "batch"
    print(f"  ~${cost:.2f} at {rate} rates for this corpus")
    if not args.list_price:
        print("  (batch rates; add --list-price to see the undiscounted figure)")

    # The system prompt dominates the input cost at these title lengths, and that
    # is worth showing rather than burying: shortening it is the highest-leverage
    # edit available, and nobody would guess that from the totals.
    share = (chunks * system_tokens) / input_tokens if input_tokens else 0
    print(f"  the system prompt is {share:.0%} of input tokens")
    per_document = (chunks * system_tokens) / len(screened) if screened else 0
    print(f"  instruction overhead is {per_document:.0f} tokens per document")
    print(
        f"  (at one title per request it would be {system_tokens:,}; that was the ADR-0008 error)"
    )

    print("\n--- system prompt, as sent ---")
    print(STAGE_ONE_SYSTEM)

    print(f"\n--- first {args.samples} titles, as sent ---")
    for c in screened[: args.samples]:
        print(f"  [{c.source_id}] {c.title[:100]}")

    print("\nNothing was sent. No API key was read.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description="FutureTech Radar pipeline")
    parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_REGISTRY_PATH,
        help="path to sources.yaml (default: %(default)s)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sources = sub.add_parser("sources", help="inspect or sync the source registry")
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    sources_sub.add_parser("list", help="print the registry").set_defaults(func=cmd_sources_list)
    sources_sub.add_parser("sync", help="write the registry to the database").set_defaults(
        func=cmd_sources_sync
    )

    ingest = sub.add_parser("ingest", help="poll sources and store new documents")
    ingest.add_argument("--since", default="1d", help="window: 1d, 12h, 2w or an ISO date")
    ingest.add_argument("--source", help="only this source id")
    ingest.add_argument("--limit", type=int, help="stop after this many documents per source")
    ingest.set_defaults(func=cmd_ingest)

    smoke = sub.add_parser(
        "smoke", help="fetch a few documents from a live source and print them (no writes)"
    )
    smoke.add_argument("--source", default="arxiv-cs-ro", help="source id (default: %(default)s)")
    smoke.add_argument("--count", type=int, default=3, help="documents to show")
    smoke.add_argument("--since", default="7d", help="window: 1d, 7d, 2w or an ISO date")
    smoke.set_defaults(func=cmd_smoke)

    label = sub.add_parser("label", help="build and check the hand-labelled evaluation set")
    label_sub = label.add_subparsers(dest="label_command", required=True)

    label_export = label_sub.add_parser("export", help="write a worksheet to fill in by hand")
    label_export.add_argument(
        "--out", default="labelled-set.yaml", help="where to write (default: %(default)s)"
    )
    label_export.add_argument(
        "--per-domain",
        type=int,
        default=DEFAULT_PER_DOMAIN,
        help="documents per domain (default: %(default)s)",
    )
    label_export.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="sampling seed; the same seed gives the same documents (default: %(default)s)",
    )
    label_export.add_argument(
        "--force", action="store_true", help="overwrite an existing worksheet"
    )
    label_export.set_defaults(func=cmd_label_export)

    label_check = label_sub.add_parser("check", help="verify a filled-in worksheet")
    label_check.add_argument("file", help="the worksheet to check")
    label_check.set_defaults(func=cmd_label_check)

    prefilter = sub.add_parser("prefilter", help="the triage gate that runs before any model")
    prefilter_sub = prefilter.add_subparsers(dest="prefilter_command", required=True)
    prefilter_report = prefilter_sub.add_parser(
        "report", help="measure the gate against stored documents; writes nothing"
    )
    prefilter_report.add_argument(
        "--vocabulary",
        type=Path,
        default=Path("prefilter.yaml"),
        help="path to prefilter.yaml (default: %(default)s)",
    )
    prefilter_report.add_argument(
        "--samples",
        type=int,
        default=8,
        help="how many example titles to print per verdict (default: %(default)s)",
    )
    prefilter_report.set_defaults(func=cmd_prefilter_report)

    triage = sub.add_parser("triage", help="the model passes that decide what is worth extracting")
    triage_sub = triage.add_subparsers(dest="triage_command", required=True)
    triage_estimate = triage_sub.add_parser(
        "estimate", help="print stage one's prompt and cost for the stored corpus; makes no calls"
    )
    triage_estimate.add_argument(
        "--model", default=HAIKU, choices=sorted(PRICES), help="default: %(default)s"
    )
    triage_estimate.add_argument(
        "--list-price",
        action="store_true",
        help="price at list rates instead of the Batch API's 50%% discount",
    )
    triage_estimate.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        help="titles per request (default: %(default)s)",
    )
    triage_estimate.add_argument(
        "--samples", type=int, default=10, help="titles to print (default: %(default)s)"
    )
    triage_estimate.set_defaults(func=cmd_triage_estimate)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(get_settings())
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
