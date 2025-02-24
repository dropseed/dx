# plain.vendor

Download those CDN scripts and styles.

## What about source maps?

It's fairly common right now to get an error during `plain build` that says it can't find the source map for one of your vendored files.
Right now, the fix is add the source map itself to your vendored dependencies too.
In the future `plain vendor` might discover those during the vendoring process and download them automatically with the compiled files.
