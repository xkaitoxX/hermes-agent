"""Android (Termux) is a Linux userland: skills tagged ``linux`` must load there."""
from __future__ import annotations

import pytest

from agent import skill_utils


@pytest.mark.parametrize("platforms, expected", [
    (["linux"], True),
    (["android"], True),
    (["linux", "macos", "windows"], True),
    (["macos"], False),
    (["windows"], False),
    (None, True),
])
def test_android_matches_linux_skills(monkeypatch, platforms, expected):
    monkeypatch.setattr(skill_utils.sys, "platform", "android")
    assert skill_utils.skill_matches_platform_list(platforms) is expected


def test_linux_does_not_match_android_only_skills(monkeypatch):
    monkeypatch.setattr(skill_utils.sys, "platform", "linux")
    assert skill_utils.skill_matches_platform_list(["android"]) is False
