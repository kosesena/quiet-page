import pytest

from counterfoil.llm import PRESETS, preset


def test_local_preset_needs_no_key():
    cfg = preset("qwen2.5")
    assert cfg.base_url.startswith("http://localhost") and cfg.model == "qwen2.5-8k" and cfg.seed == 7


def test_unknown_preset_is_refused():
    with pytest.raises(ValueError):
        preset("gpt-9")


@pytest.mark.parametrize("name", [n for n, p in PRESETS.items() if p[2]])
def test_cloud_presets_refuse_to_run_without_their_key(name, monkeypatch):
    monkeypatch.delenv(PRESETS[name][2], raising=False)
    monkeypatch.setenv("ASTRA_MODEL_ID", "x")
    with pytest.raises(RuntimeError):
        preset(name)


def test_anthropic_presets_do_not_send_seed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert preset("haiku-5.5").seed is None


def test_astra_needs_its_model_id(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.delenv("ASTRA_MODEL_ID", raising=False)
    with pytest.raises(RuntimeError, match="ASTRA_MODEL_ID"):
        preset("gpt6-astra")


def test_reader_accepts_a_fenced_json_object():
    from types import SimpleNamespace

    from counterfoil.agents import read_email

    fenced = '```json\n{"musteri_email": "a@b.c", "siparis_no": "ST-1", "tutar": "30.00"}\n```'
    llm = SimpleNamespace(chat=lambda *a, **k: SimpleNamespace(content=fenced))
    out, raw = read_email(llm, {"from": "a@b.c", "subject": "s", "body": "b"})
    assert out and out["siparis_no"] == "ST-1" and raw == fenced


def test_claude_5_family_does_not_send_temperature(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    assert preset("opus-5.5").temperature is None
    assert preset("qwen2.5").temperature == 0.0


def test_gpt_5_6_on_the_gateway_turns_reasoning_off(monkeypatch):
    monkeypatch.setenv("ASTRO_GATEWAY_URL", "https://gateway.example")
    monkeypatch.setenv("ASTRO_GATEWAY_API_KEY", "test")
    monkeypatch.setenv("CF_MODEL", "gpt-5-6-terra")
    cfg = preset("astropods")
    assert cfg.reasoning_effort == "none" and cfg.temperature is None and cfg.base_url == "https://gateway.example/v1"


def test_vultr_preset_uses_serverless_inference(monkeypatch):
    from counterfoil.llm import preset

    monkeypatch.setenv("VULTR_INFERENCE_API_KEY", "test-key")
    monkeypatch.delenv("VULTR_MODEL", raising=False)
    cfg = preset("vultr")
    assert cfg.base_url == "https://api.vultrinference.com/v1"
    assert cfg.model == "qwen3.8-flash-next" and cfg.seed is None
