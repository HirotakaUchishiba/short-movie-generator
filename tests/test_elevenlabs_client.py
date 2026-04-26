import elevenlabs_client


def test_credit_multiplier_known_models() -> None:
    assert elevenlabs_client.credit_multiplier("eleven_v3") == 2.0
    assert elevenlabs_client.credit_multiplier("eleven_multilingual_v2") == 1.0
    assert elevenlabs_client.credit_multiplier("eleven_turbo_v2_5") == 0.5
    assert elevenlabs_client.credit_multiplier("eleven_flash_v2_5") == 0.33


def test_credit_multiplier_unknown_falls_back_to_one() -> None:
    assert elevenlabs_client.credit_multiplier("eleven_xyz_unknown") == 1.0


def test_credit_multiplier_uses_module_default(monkeypatch) -> None:
    monkeypatch.setattr(elevenlabs_client, "MODEL_ID", "eleven_v3")
    assert elevenlabs_client.credit_multiplier() == 2.0
    monkeypatch.setattr(elevenlabs_client, "MODEL_ID", "eleven_multilingual_v2")
    assert elevenlabs_client.credit_multiplier() == 1.0


def test_models_without_context_set() -> None:
    assert "eleven_v3" in elevenlabs_client.MODELS_WITHOUT_CONTEXT
    assert "eleven_multilingual_v2" not in elevenlabs_client.MODELS_WITHOUT_CONTEXT
