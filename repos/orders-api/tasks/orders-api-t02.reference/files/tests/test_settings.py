from app.settings import load_config, load_settings


def test_load_config_reads_flat_pairs(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text("pricing:\n  bulk_threshold: 10\n# comment\nname: orders\n", encoding="utf-8")
    assert load_config(path) == {"bulk_threshold": "10", "name": "orders"}


def test_load_settings_reads_config_and_environment(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    settings = load_settings()
    assert settings.bulk_threshold == 10
    assert settings.log_level == "DEBUG"
