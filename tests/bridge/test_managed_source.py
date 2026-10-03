from tavotto.engine import figcapture
from tavotto.engine.bridge_runner import _normalize_managed_source


def test_normalize_managed_source_accepts_open_code_bytes():
    source = (
        b"# OmicOS managed figure source v1\nfigmeta = {'sem': 'standard error'}\npanel.sem = 1\n"
    )

    normalized = _normalize_managed_source(source)

    assert isinstance(normalized, bytes)
    assert b'panel["sem"] = 1' in normalized


def test_normalize_managed_source_preserves_non_utf8_source_bytes():
    source = b"# user source\nlabel = 'caf\xe9'\n"

    assert _normalize_managed_source(source) is source


def test_normalize_managed_source_removes_windows_extended_prefixes():
    source = (
        '# OmicOS managed figure source v1\n'
        'OUT = r"\\\\?\\G:\\outputs\\figure"\n'
        'ws = r"G:\\outputs"\n'
        'rel = os.path.relpath(OUT, ws)\n'
    )

    normalized = _normalize_managed_source(source)

    assert 'OUT = r"G:\\outputs\\figure"' in normalized
    assert "\\\\?\\" not in normalized


def test_normalize_managed_source_preserves_prefix_cleanup_code():
    source = (
        '# OmicOS managed figure source v1\n'
        'src_plain = src.replace("\\\\\\\\?\\\\", "")\n'
    )

    normalized = _normalize_managed_source(source)

    assert 'src_plain = src.replace("\\\\\\\\?\\\\", "")' in normalized


def test_managed_fallback_stem_uses_copied_asset_name_when_artifact_exists(tmp_path):
    sources = tmp_path / "sources"
    sources.mkdir()
    script = sources / "asset-a1b2c3-figure_1791042415039_4.py"
    script.write_text("# OmicOS managed figure source v1\n", encoding="utf-8")
    (sources / "figure_1791042415039_4.png").write_bytes(b"png")

    assert (
        figcapture.managed_fallback_stem(script, tmp_path)
        == "figure_1791042415039_4"
    )


def test_managed_fallback_stem_does_not_guess_without_artifact(tmp_path):
    script = tmp_path / "asset-a1b2c3-figure_1791042415039_4.py"
    script.write_text("# OmicOS managed figure source v1\n", encoding="utf-8")

    assert figcapture.managed_fallback_stem(script, tmp_path) is None
