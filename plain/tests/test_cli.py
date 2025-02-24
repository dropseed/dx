import subprocess


def test_plain_cli_help():
    output = subprocess.check_output(["plain", "--help"])
    assert output.startswith(b"Usage: plain")


def test_plain_cli_build():
    output = subprocess.check_output(["plain", "build"])
    assert b"Compiled 0 assets into 0 files" in output
