from app.config import FeaturesConfig, UpstreamConfig
from app.fc.policy import resolve_fc_mode
from app.models.canonical import CanonicalRequest, Message, ToolDef


def _req(with_tools: bool = True) -> CanonicalRequest:
    tools = [ToolDef(name="get_weather", description="weather", parameters={"type": "object"})] if with_tools else []
    return CanonicalRequest(
        model="demo",
        messages=[Message(role="user", content="hi")],
        tools=tools,
    )


def test_no_tools_passthrough():
    upstream = UpstreamConfig(name="u", native_fc=True)
    features = FeaturesConfig(fc_mode="auto")
    assert resolve_fc_mode(_req(False), upstream, features) == "passthrough"


def test_auto_native_when_upstream_supports():
    upstream = UpstreamConfig(name="u", native_fc=True)
    features = FeaturesConfig(fc_mode="auto")
    assert resolve_fc_mode(_req(True), upstream, features) == "native"


def test_auto_prompt_when_upstream_lacks_native():
    upstream = UpstreamConfig(name="u", native_fc=False)
    features = FeaturesConfig(fc_mode="auto")
    assert resolve_fc_mode(_req(True), upstream, features) == "prompt"


def test_force_prompt_header():
    upstream = UpstreamConfig(name="u", native_fc=True)
    features = FeaturesConfig(fc_mode="auto")
    assert resolve_fc_mode(_req(True), upstream, features, header_override="force_prompt") == "prompt"


def test_global_force_prompt():
    upstream = UpstreamConfig(name="u", native_fc=True)
    features = FeaturesConfig(fc_mode="force_prompt")
    assert resolve_fc_mode(_req(True), upstream, features) == "prompt"
