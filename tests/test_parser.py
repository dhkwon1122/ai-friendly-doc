from ai_friendly_doc.parser import parse_storage_html


def test_table_merged_cell_flagged():
    html = '<table><tbody><tr><td colspan="2">a</td></tr></tbody></table>'
    doc = parse_storage_html("t", html)
    assert doc.tables[0].has_merged_cells is True
    assert doc.tables[0].has_nested_table is False


def test_table_rowspan_also_counts_as_merged():
    html = '<table><tbody><tr><td rowspan="2">a</td></tr></tbody></table>'
    doc = parse_storage_html("t", html)
    assert doc.tables[0].has_merged_cells is True


def test_table_colspan_1_not_flagged():
    # colspan="1"은 실질적으로 병합이 아님
    html = '<table><tbody><tr><td colspan="1">a</td></tr></tbody></table>'
    doc = parse_storage_html("t", html)
    assert doc.tables[0].has_merged_cells is False


def test_nested_table_flagged():
    html = "<table><tbody><tr><td><table><tbody><tr><td>inner</td></tr></tbody></table></td></tr></tbody></table>"
    doc = parse_storage_html("t", html)
    assert doc.tables[0].has_nested_table is True


def test_plain_table_no_merge_no_nesting():
    html = "<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
    doc = parse_storage_html("t", html)
    assert doc.tables[0].has_merged_cells is False
    assert doc.tables[0].has_nested_table is False


def test_macro_count_increments_per_macro():
    html = '<ac:structured-macro ac:name="code"></ac:structured-macro><ac:structured-macro ac:name="info"></ac:structured-macro>'
    doc = parse_storage_html("t", html)
    assert doc.macro_count == 2


def test_macro_count_zero_when_no_macros():
    doc = parse_storage_html("t", "<p>본문</p>")
    assert doc.macro_count == 0
