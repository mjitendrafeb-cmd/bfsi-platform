from scripts.export_static_site import export


def test_static_export_includes_full_directory_and_valid_nested_links(tmp_path):
    out = tmp_path / "docs"
    export(out)
    directory = (out / "entities.html").read_text(encoding="utf-8")
    assert "Namdev Finvest" in directory
    assert "Karnataka Bank" in directory
    nested = (out / "entities" / "4.html").read_text(encoding="utf-8")
    assert 'href="../static/style.css"' in nested
    assert 'href="../index.html"' in nested
