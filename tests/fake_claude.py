"""A stand-in for anthropic.Anthropic that scripts a tool call, a web search, then an answer."""
from types import SimpleNamespace as NS


def block(**kw):
    kw.setdefault("citations", None)
    return NS(**kw)


class FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        n = len(self.calls)
        if n == 1:
            return NS(stop_reason="tool_use", content=[
                block(type="text", text="Let me check your team and the news."),
                block(type="tool_use", id="t1", name="get_my_team", input={}),
                block(type="tool_use", id="t2", name="get_rising_players", input={"top_n": 3}),
                block(type="server_tool_use", id="s1", name="web_search", input={"query": "NBA injury report"}),
            ])
        return NS(stop_reason="end_turn", content=[
            block(type="text", text="Add the top rising player.",
                  citations=[NS(url="https://example.com/injuries", title="Injury report")]),
        ])


class FakeAnthropic:
    last = None

    def __init__(self, *a, **k):
        self.messages = FakeMessages()
        FakeAnthropic.last = self
