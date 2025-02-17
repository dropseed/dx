from plain.urls import RouterBase, path, register_router

from . import views


@register_router
class Router(RouterBase):
    namespace = "pageviews"
    urls = [
        path("track/", views.TrackView, name="track"),
    ]
