import sys

from sage_utils import elevation


def test_own_command_drops_the_arguments(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")
    monkeypatch.setattr(sys, "orig_argv", ["python", "-X", "utf8", "-m", "tool.ui", "a.map"])
    monkeypatch.setattr(sys, "argv", [r"C:\tool\ui\__main__.py", "a.map"])
    assert elevation.own_command() == [r"C:\Python312\python.exe", "-X", "utf8", "-m", "tool.ui"]


def test_own_command_without_arguments(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Python312\python.exe")
    monkeypatch.setattr(sys, "orig_argv", ["python", r"C:\Scripts\tool.exe"])
    monkeypatch.setattr(sys, "argv", [r"C:\Scripts\tool.exe"])
    assert elevation.own_command() == [r"C:\Python312\python.exe", r"C:\Scripts\tool.exe"]


def test_own_command_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\tool\tool.exe")
    monkeypatch.setattr(sys, "argv", [r"C:\tool\tool.exe", "a.map"])
    assert elevation.own_command() == [r"C:\tool\tool.exe"]
