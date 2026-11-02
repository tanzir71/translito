from engines.display import FSI, PDI, display_text, dominant_rtl, isolate_latin


def test_latin_isolates_are_inserted_only_in_the_display_copy():
    original = "نراجع ال deployment بعد ال meeting"
    displayed = isolate_latin(original)
    assert FSI + "deployment" + PDI in displayed
    assert FSI + "meeting" + PDI in displayed
    assert displayed.replace(FSI, "").replace(PDI, "") == original
    assert FSI not in original and PDI not in original
    rendered = display_text(original)
    assert FSI not in rendered and PDI not in rendered
    assert "deployment" in rendered and "meeting" in rendered
    assert display_text("The API works.") == "The API works."


def test_alignment_follows_dominant_script():
    assert dominant_rtl("هذه جملة عربية فيها API")
    assert not dominant_rtl("Review the API today")
    assert not dominant_rtl("1234")
