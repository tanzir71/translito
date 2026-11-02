from unittest.mock import Mock

import pytest

from engines.secrets import CredentialError, CredentialStore


def test_keys_are_only_sent_to_credential_manager_not_config_files(tmp_path, monkeypatch):
    import app_config
    config = tmp_path / "config.ini"
    config.write_text("[UNRELATED]\nvalue = preserved\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "CONFIG_FILE", config)
    original = config.read_bytes()
    backend = Mock()
    backend.get_password.return_value = "secret_test_value"
    store = CredentialStore(backend=backend)
    store.save("azure", "secret_test_value")
    assert store.get("azure") == "secret_test_value"
    backend.set_password.assert_called_once_with("Translito", "azure", "secret_test_value")
    assert config.read_bytes() == original
    assert list(tmp_path.iterdir()) == [config]


def test_backend_failure_and_validation_messages_never_contain_the_key(caplog):
    backend = Mock()
    backend.set_password.side_effect = RuntimeError("key=secret_test_value")
    store = CredentialStore(backend=backend)
    with pytest.raises(CredentialError) as error:
        store.save("azure", "secret_test_value")
    assert "secret_test_value" not in str(error.value)
    assert "secret_test_value" not in caplog.text
    with pytest.raises(CredentialError):
        store.save("azure", "key\ninjection")
