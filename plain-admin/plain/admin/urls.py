from plain.http import ResponseRedirect
from plain.urls import RouterBase, include, path, register_router

from .impersonate import urls as impersonate_urls
from .querystats import urls as querystats_urls
from .views.base import AdminView
from .views.registry import registry


class AdminIndexView(AdminView):
    template_name = "admin/index.html"
    title = "Dashboard"

    def get(self):
        # Slight hack to redirect to the first view that doesn't
        # require any url params...
        if views := registry.get_searchable_views():
            return ResponseRedirect(list(views)[0].get_view_url())

        return super().get()


class AdminSearchView(AdminView):
    template_name = "admin/search.html"
    title = "Search"

    def get_template_context(self):
        context = super().get_template_context()
        context["searchable_views"] = registry.get_searchable_views()
        context["global_search_query"] = self.request.GET.get("query", "")
        return context


@register_router
class Router(RouterBase):
    namespace = "admin"
    urls = [
        path("search/", AdminSearchView, name="search"),
        include("impersonate/", impersonate_urls),
        include("querystats/", querystats_urls),
        include("", registry.get_urls()),
        path("", AdminIndexView, name="index"),
    ]
