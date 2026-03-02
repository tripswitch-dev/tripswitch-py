"""Internal SSE (Server-Sent Events) line-protocol parser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class SSEEvent:
    """A single parsed SSE event."""

    event: str = ""
    data: str = ""
    id: str = ""
    retry: int | None = None


def parse_sse_stream(lines: Iterator[str]) -> Iterator[SSEEvent]:
    """Yield ``SSEEvent`` objects from an iterator of text lines.

    Follows the W3C EventSource specification: blank lines dispatch events,
    lines starting with ``:`` are comments (ignored), and fields are
    ``event``, ``data``, ``id``, and ``retry``.
    """
    current = SSEEvent()

    for raw in lines:
        line = raw.rstrip("\r\n")

        # Blank line → dispatch if we have data
        if not line:
            if current.data:
                # Strip the trailing newline that accumulated from multi-data lines
                current.data = current.data.rstrip("\n")
                yield current
            current = SSEEvent()
            continue

        # Comment
        if line.startswith(":"):
            continue

        # Split field: value
        if ":" in line:
            name, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
        else:
            name = line
            value = ""

        if name == "event":
            current.event = value
        elif name == "data":
            # Multiple data lines are joined with newlines
            current.data = (current.data + "\n" + value) if current.data else value
        elif name == "id":
            current.id = value
        elif name == "retry":
            try:
                current.retry = int(value)
            except ValueError:
                pass

    # Final event if stream ends without trailing blank line
    if current.data:
        current.data = current.data.rstrip("\n")
        yield current
