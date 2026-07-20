from app.util.sse import SSEParser, format_sse, try_json


def test_sse_parser_multiline_data():
    parser = SSEParser()
    assert parser.feed_line("event: response.created") is None
    assert parser.feed_line('data: {"a":1,') is None
    assert parser.feed_line('data: "b":2}') is None
    event = parser.feed_line("")
    assert event is not None
    assert event.event == "response.created"
    assert event.data == '{"a":1,\n"b":2}'


def test_sse_parser_done():
    parser = SSEParser()
    parser.feed_line("data: [DONE]")
    event = parser.feed_line("")
    assert event is not None
    assert event.is_done is True


def test_format_sse_with_event():
    frame = format_sse({"type": "x"}, event="x")
    assert "event: x\n" in frame
    assert 'data: {"type": "x"}' in frame or "data: {" in frame
    assert frame.endswith("\n\n")


def test_try_json():
    assert try_json('{"a":1}') == {"a": 1}
    assert try_json("[DONE]") is None
