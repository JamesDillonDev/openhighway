from .national_highways import NationalHighwaysSource
from .source import Source
from .tfl import TfLSource

#: every source OpenHighways knows how to build, keyed by its `name`
AVAILABLE_SOURCES: dict[str, type[Source]] = {
    NationalHighwaysSource.name: NationalHighwaysSource,
    TfLSource.name: TfLSource,
}


def load_sources(names: list[str] | None = None) -> list[Source]:
    """Instantiate the requested sources (default: all registered sources)."""

    names = names or list(AVAILABLE_SOURCES)

    unknown = [name for name in names if name not in AVAILABLE_SOURCES]

    if unknown:
        raise ValueError(
            f"Unknown source(s): {', '.join(unknown)}. "
            f"Available: {', '.join(AVAILABLE_SOURCES)}"
        )

    return [AVAILABLE_SOURCES[name]() for name in names]


__all__ = ["Source", "NationalHighwaysSource", "TfLSource", "AVAILABLE_SOURCES", "load_sources"]
