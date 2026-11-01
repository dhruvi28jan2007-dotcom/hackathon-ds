from streamlit.testing.v1 import AppTest


def test_streamlit_app_renders():
    at = AppTest.from_file("../frontend/app.py").run()
    assert not at.exception, f"App failed to render: {at.exception}"
    assert len(at.title) > 0, "Page title not found"
    assert at.title[0].value == "🛡️ ClaimCheck"


def test_streamlit_app_demo_audit():
    at = AppTest.from_file("../frontend/app.py").run()
    assert not at.exception, f"App failed during initial run: {at.exception}"

    # Locate 'Use Demo / Sample PR' checkbox by label
    demo_checkboxes = [c for c in at.checkbox if "Use Demo" in c.label]
    assert len(demo_checkboxes) > 0, "Demo checkbox not found on page"
    demo_checkbox = demo_checkboxes[0]
    demo_checkbox.check().run()
    assert not at.exception, f"App failed after checking demo mode: {at.exception}"

    # Locate 'Run ClaimCheck Audit' button by label
    audit_buttons = [b for b in at.button if "Run ClaimCheck Audit" in b.label]
    assert len(audit_buttons) > 0, "Run ClaimCheck Audit button not found on page"
    audit_button = audit_buttons[0]
    audit_button.click().run()
    assert not at.exception, f"App failed during demo audit execution: {at.exception}"
