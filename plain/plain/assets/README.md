# Assets

Serve static assets (CSS, JS, images, etc.) directly from your app.


## Usage

To serve assets, put them in `app/assets` or `app/{package}/assets`.

Then include the `plain.assets.urls` in your `urls.py`:

```python
# app/urls.py
from plain.urls import include, path
import plain.assets.urls


urlpatterns = [
    path("assets/", include(plain.assets.urls)),
    # ...
]
```

Now in your template you can use the `asset()` function to get the URL:

```html
<link rel="stylesheet" href="{{ asset('css/style.css') }}">
```


## Local development

When you're working with `settings.DEBUG = True`, the assets will be served directly from their original location. You don't need to run `plain build` or configure anything else.


## Production deployment

In production, one of your deployment steps should be to compile the assets.

```bash
plain build
```

By default, this generates "fingerprinted" and compressed versions of the assets, which are then served by your app. This means that a file like `main.css` will result in two new files, like `main.d0db67b.css` and `main.d0db67b.css.gz`.

The purpose of fingerprinting the assets is to allow the browser to cache them indefinitely. When the content of the file changes, the fingerprint will change, and the browser will use the newer file. This cuts down on the number of requests that your app has to handle related to assets.


## FAQs

### How do you reference assets in Python code?

```python
from plain.assets.urls import get_asset_url

url = get_asset_url("css/style.css")
```

### What if I need the files in a different location?

The generated/copied files are stored in `{repo}/.plain/assets/compiled`. If you need them to be somewhere else, try simply moving them after compilation.

```bash
plain build
mv .plain/assets/compiled /path/to/your/static
```

### How do I upload the assets to a CDN?

The steps for this will vary, but the general idea is to compile them, and then upload the compiled assets.

```bash
plain build
./example-upload-to-cdn-script
```

Use the `ASSETS_BASE_URL` setting to tell the `{{ asset() }}` template function where to point.

```python
# app/settings.py
ASSETS_BASE_URL = "https://cdn.example.com/"
```


### Why aren't the originals copied to the compiled directory?

The default behavior is to fingerprint assets, which is an exact copy of the original file but with a different filename. The originals aren't copied over because you should generally always use this fingerprinted path (that automatically uses longer-lived caching).

If you need the originals for any reason, you can use `plain build --keep-original`, though this will typically be combined with `--no-fingerprint` otherwise the fingerprinted files will still get priority in `{{ asset() }}` template calls.


### What about source maps or imported css files?

TODO
