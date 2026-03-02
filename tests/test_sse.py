"""Tests for the SSE line-protocol parser."""

from tripswitch._sse import parse_sse_stream


def test_single_event():
    lines = [
        "data: hello\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    assert events[0].data == "hello"


def test_event_with_type():
    lines = [
        "event: breaker_update\n",
        "data: {\"state\": \"open\"}\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events[0].event == "breaker_update"
    assert events[0].data == '{"state": "open"}'


def test_multi_data_lines():
    lines = [
        "data: line1\n",
        "data: line2\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events[0].data == "line1\nline2"


def test_comments_ignored():
    lines = [
        ": this is a comment\n",
        "data: real data\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    assert events[0].data == "real data"


def test_multiple_events():
    lines = [
        "data: first\n",
        "\n",
        "data: second\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 2
    assert events[0].data == "first"
    assert events[1].data == "second"


def test_empty_lines_without_data_are_ignored():
    lines = [
        "\n",
        "\n",
        "data: actual\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1


def test_stream_end_without_blank_line():
    lines = [
        "data: trailing\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert len(events) == 1
    assert events[0].data == "trailing"


def test_retry_field():
    lines = [
        "retry: 5000\n",
        "data: with retry\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events[0].retry == 5000


def test_id_field():
    lines = [
        "id: evt-123\n",
        "data: identified\n",
        "\n",
    ]
    events = list(parse_sse_stream(iter(lines)))
    assert events[0].id == "evt-123"
