from .cli import build, dev


def run_dev_build():
    # This will run by itself as a command, so it can exit()
    dev([], standalone_mode=True)


def run_build():
    # Standalone mode prevents it from exit()ing
    build([], standalone_mode=False)
