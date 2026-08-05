import os

import pytest

pytest.importorskip("fastapi")

# app.py는 import 시점에 SESSION_SECRET/CONFLUENCE_BASE_URL이 없으면 바로
# RuntimeError를 낸다(둘 다 필수 배포 설정). monkeypatch 픽스처는 아직 없는
# 시점(모듈 import 시점)이라 직접 세팅한다.
os.environ.setdefault("SESSION_SECRET", "test-secret-for-pytest")
os.environ.setdefault("CONFLUENCE_BASE_URL", "https://example.atlassian.net/wiki")

from ai_friendly_doc.web.app import _fixed_base_url


def test_fixed_base_url_raises_when_unset(monkeypatch):
    monkeypatch.delenv("CONFLUENCE_BASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        _fixed_base_url()


def test_fixed_base_url_strips_trailing_slash(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "https://confluence.internal.example.com/wiki/")
    assert _fixed_base_url() == "https://confluence.internal.example.com/wiki"


def test_fixed_base_url_raises_when_blank(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_BASE_URL", "   ")
    with pytest.raises(RuntimeError):
        _fixed_base_url()
