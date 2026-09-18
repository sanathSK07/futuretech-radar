"""Source fetchers. One module per source kind."""

from radar.pipeline.fetchers.arxiv import ArxivFetcher
from radar.pipeline.fetchers.base import Fetcher, RawDocument

__all__ = ["ArxivFetcher", "Fetcher", "RawDocument"]
