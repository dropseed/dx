# plain.tailwind

Integrate Tailwind CSS without JavaScript or npm.

Made possible by the [Tailwind standalone CLI](https://tailwindcss.com/blog/standalone-cli),
which is installed for you.

```console
$ plain tailwind
Usage: plain tailwind [OPTIONS] COMMAND [ARGS]...

  Tailwind CSS

Options:
  --help  Show this message and exit.

Commands:
  build  Compile a Tailwind CSS file
  init     Install Tailwind, create a tailwind.config.js...
  update   Update the Tailwind CSS version
```

## Installation

Add `plain.tailwind` to your `INSTALLED_PACKAGES`:

```python
# settings.py
INSTALLED_PACKAGES = [
    # ...
    "plain.tailwind",
]
```

Create a new `tailwind.config.js` file in your project root:

```sh
plain tailwind init
```

This will also create a `tailwind.css` file at `static/src/tailwind.css` where additional CSS can be added.
You can customize where these files are located if you need to,
but this is the default (requires `STATICFILES_DIR = BASE_DIR / "static"`).

The `src/tailwind.css` file is then compiled into `dist/tailwind.css` by running `tailwind build`:

```sh
plain tailwind build
```

When you're working locally, add `--watch` to automatically compile as changes are made:

```sh
plain tailwind build --watch
```

Then include the compiled CSS in your base template `<head>`:

```html
{% tailwind_css %}
```

In your repo you will notice a new `.plain` directory that contains `tailwind` (the standalone CLI binary) and `tailwind.version` (to track the version currently installed).
You should add `.plain` to your `.gitignore` file.

## Updating Tailwind

This package manages the Tailwind versioning by comparing the value in your `pyproject.toml` to `.plain/tailwind.version`.

```toml
# pyproject.toml
[tool.plain.tailwind]
version = "3.4.1"
```

When you run `tailwind compile`,
it will automatically check whether your local installation needs to be updated and will update it if necessary.

You can use the `update` command to update your project to the latest version of Tailwind:

```sh
plain tailwind update
```

## Adding custom CSS

If you need to actually write some CSS,
it should be done in `app/static/src/tailwind.css`.

```css
@tailwind base;


@tailwind components;

/* Add your own "components" here */
.btn {
    @apply bg-blue-500 hover:bg-blue-700 text-white;
}

@tailwind utilities;

/* Add your own "utilities" here */
.bg-pattern-stars {
    background-image: url("/static/images/stars.png");
}

```

[Read the Tailwind docs for more about using custom styles →](https://tailwindcss.com/docs/adding-custom-styles)

## Deployment

If possible, you should add `static/dist/tailwind.css` to your `.gitignore` and run the `plain tailwind build --minify` command as a part of your deployment pipeline.

When you run `plain tailwind build`, it will automatically check whether the Tailwind standalone CLI has been installed, and install it if it isn't.

When using Plain on Heroku, we do this for you automatically in our [Plain buildpack](https://github.com/plainpackages/heroku-buildpack-plain/blob/master/bin/files/post_compile).
