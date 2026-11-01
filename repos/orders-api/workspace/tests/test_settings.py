from app.settings import load_config


def test_load_config_reads_flat_pairs(tmp_path):
    path = tmp_path / "app.yaml"
    path.write_text("pricing:\n  bulk_threshold: 10\n# comment\nname: orders\n", encoding="utf-8")
    assert load_config(path) == {"bulk_threshold": "10", "name": "orders"}
