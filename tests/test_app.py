"""Drives the real app script headlessly: no browser and no API key."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app.py")


def click(at, label, nth=0):
    [b for b in at.button if b.label == label][nth].click()
    return at.run(timeout=30)


def approve_button(at):
    return next(b for b in at.button if b.label == "Approve plan")


def warnings(at):
    return [w.value for w in at.warning]


@pytest.fixture
def app():
    return AppTest.from_file(APP, default_timeout=30).run()


def test_plan_builds_and_can_be_approved(app):
    at = click(app, "Build plan")
    assert not at.exception
    assert not approve_button(at).disabled
    assert not any("rules changed" in w for w in warnings(at))


def test_adding_a_rule_after_building_blocks_approval(app):
    at = click(app, "Build plan")
    at = click(at, "Add rule")  # default form values: Tech A is out
    assert not at.exception
    assert any("rules changed" in w for w in warnings(at))
    assert approve_button(at).disabled


def test_removing_a_rule_after_building_blocks_approval(app):
    at = click(app, "Add rule")
    at = click(at, "Build plan")
    assert not approve_button(at).disabled
    at = click(at, "Remove")
    assert not at.exception
    assert any("rules changed" in w for w in warnings(at))
    assert approve_button(at).disabled


def test_rebuilding_clears_the_block(app):
    at = click(app, "Build plan")
    at = click(at, "Add rule")
    at = click(at, "Build plan")
    assert not any("rules changed" in w for w in warnings(at))
    assert not approve_button(at).disabled


def test_adding_the_same_rule_twice_keeps_one(app):
    at = click(app, "Add rule")
    at = click(at, "Add rule")
    assert not at.exception
    assert len([b for b in at.button if b.label == "Remove"]) == 1
