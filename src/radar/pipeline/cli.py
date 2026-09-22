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
from collections.abc import Sequence
from pathlib import Path

import structlog
from pydantic import ValidationError

from radar.core.db import session_scope
from radar.core.settings import Settings, get_settings
from radar.core.types import FetchStatus
from radar.pipeline.http import SafeHttpClient
from radar.pipeline.ingest import build_fetcher, host_for, ingest_all, parse_since
from radar.pipeline.labelling import (
    DEFAULT_PER_DOMAIN,
    DEFAULT_SEED,
    check_worksheet,
    format_report,
    parse_worksheet,
    render_worksheet,
    select_documents,
)
from radar.pipeline.ratelimit import LimiterRegistry
from radar.pipeline.registry import DEFAULT_REGISTRY_PATH, load_registry, sync_registry


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

    total_fetched = sum(r.fetched_count for r in runs)
    total_new = sum(r.new_count for r in runs)
    failed = [r for r in runs if r.status == FetchStatus.ERROR]

    print(f"\n{len(runs)} sources polled: {total_fetched} documents seen, {total_new} new")
    for run in runs:
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

    out.write_text(worksheet, encoding="utf-8")
    domains = sorted({d for doc in documents for d in (doc.source.domains or [])})
    print(f"wrote {len(documents)} documents to {out}")
    print(f"domains covered: {', '.join(domains) or '(none recorded)'}")
    print(f"seed {args.seed} - rerunning with the same seed gives the same documents")
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(get_settings())
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
