from plain.admin.views import (
    AdminModelDetailView,
    AdminModelListView,
    AdminViewset,
    register_viewset,
)
from plain.cache.models import CachedItem


@register_viewset
class CachedItemViewset(AdminViewset):
    class ListView(AdminModelListView):
        nav_section = "Cache"
        model = CachedItem
        title = "Cached items"
        fields = [
            "key",
            "created_at",
            "expires_at",
            "updated_at",
        ]
        queryset_order = ["-pk"]
        allow_global_search = False

        # TODO put back
        # def get_list_queryset(self):
        #     return CachedItem.objects.all().only(
        #         "key", "created_at", "expires_at", "updated_at"
        #     )

    class DetailView(AdminModelDetailView):
        model = CachedItem
        title = "Cached item"
