import os

import click
from watchfiles import Change, DefaultFilter, watch

from plain.assets.finders import iter_asset_dirs, iter_assets

from .core import esbuild, get_esbuilt_path


@click.group("esbuild")
def cli():
    pass


@cli.command()
@click.option("--minify", is_flag=True, default=True)
def build(minify):
    returncode = 0
    for asset in iter_assets():
        if ".esbuild." in asset.absolute_path:
            if not esbuild(
                asset.absolute_path,
                get_esbuilt_path(asset.absolute_path),
                minify=minify,
            ):
                returncode = 1
            print()

    if returncode:
        exit(returncode)


@cli.command()
@click.pass_context
def dev(ctx):
    # Do an initial build of the assets
    ctx.invoke(build, minify=False)

    asset_dirs = list(iter_asset_dirs())

    class EsbuildFilter(DefaultFilter):
        def __call__(self, change, path):
            return super().__call__(change, path) and ".esbuild." in path

    print("Watching for changes in .esbuild. asset files...")

    for changes in watch(*asset_dirs, watch_filter=EsbuildFilter()):
        for change, path in changes:
            if change in [Change.added, Change.modified]:
                esbuild(path, get_esbuilt_path(path))
            elif change == Change.deleted:
                dist_path = get_esbuilt_path(path)
                if os.path.exists(dist_path):
                    print(f"Deleting {os.path.relpath(dist_path)}")
                    os.remove(dist_path)


if __name__ == "__main__":
    cli()
