from relkit.changelog import render_section, split_entries


def test_split_entries_groups_by_type():
    grouped = split_entries(["feat(api): add export", "fix: handle empty input"])
    assert grouped["Added"] == ["add export"]
    assert grouped["Fixed"] == ["handle empty input"]


def test_split_entries_skips_unknown_types():
    grouped = split_entries(["chore: bump deps", "feat: real change"])
    assert "add" not in grouped
    assert grouped["Added"] == ["real change"]


def test_split_entries_handles_breaking_marker():
    grouped = split_entries(["feat(api)!: drop v1"])
    assert grouped["Added"] == ["drop v1"]


def test_render_section_has_heading():
    out = render_section("0.4.0", "2026-03-01", {"Added": ["thing"]})
    assert out.startswith("## [0.4.0] - 2026-03-01")


def test_render_section_keeps_canonical_order():
    out = render_section("0.4.0", "2026-03-01", {"Fixed": ["b"], "Added": ["a"]})
    assert out.index("### Added") < out.index("### Fixed")


def test_render_section_omits_empty_groups():
    out = render_section("0.4.0", "2026-03-01", {"Added": ["a"]})
    assert "### Security" not in out
