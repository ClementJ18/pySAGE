"""The bug report every SAGE front end hands over: the build it names, and the issue link it
builds. Qt-free, like the module - the crash handler builds a report in exactly this state."""

import urllib.parse

from sage_utils.bugreport import (
    DESCRIPTION_PLACEHOLDER,
    ISSUES_URL,
    URL_BODY_LIMIT,
    environment,
    new_issue_url,
    report_text,
)
from sage_utils.extras import package_version


def test_the_environment_names_the_build_and_the_interpreter():
    rows = environment("SAGE WorldBuilder")

    assert rows["App"] == "SAGE WorldBuilder"
    assert rows["pySAGE"] == package_version()
    assert rows["Build"] in {"frozen exe", "source checkout"}
    assert rows["Python"] and rows["OS"]


def test_app_state_is_added_to_the_environment():
    rows = environment("SAGE WorldBuilder", {"Map": "maps/Moria/Moria.map", "Mods": "none"})

    assert rows["Map"] == "maps/Moria/Moria.map"
    # The build rows stay: app state is added to the report, never in place of it.
    assert rows["App"] == "SAGE WorldBuilder"


def test_a_report_carries_the_description_the_environment_and_the_details():
    report = report_text("The App", extra={"Map": "none open"}, details="Traceback: boom")

    assert DESCRIPTION_PLACEHOLDER in report
    assert "- **Map:** none open" in report
    assert "```\nTraceback: boom\n```" in report


def test_a_report_without_details_has_no_empty_code_fence():
    assert "```" not in report_text("The App")


def test_the_issue_link_prefills_the_title_and_the_body():
    url = new_issue_url("The App", "the whole report")

    assert url.startswith(f"{ISSUES_URL}/new?")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["title"] == ["The App"]
    assert query["body"] == ["the whole report"]


def test_a_body_too_long_for_a_url_is_left_out_rather_than_breaking_the_link():
    # GitHub answers an over-long URL with a 414, so a long report (a traceback) travels by
    # clipboard instead - the link must still open an empty form.
    url = new_issue_url("The App", "x" * (URL_BODY_LIMIT + 1))

    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert query["title"] == ["The App"]
    assert "body" not in query
