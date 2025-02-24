from plain.htmx.views import HTMXViewMixin
from plain.http import Response, ResponseRedirect
from plain.models import Model
from plain.paginator import Paginator
from plain.views import (
    CreateView,
    DeleteView,
    DetailView,
    UpdateView,
)

from .base import AdminView


class AdminListView(HTMXViewMixin, AdminView):
    template_name = "admin/list.html"
    fields: list[str]
    actions: list[str] = []
    displays: list[str] = []
    page_size = 100
    show_search = False
    allow_global_search = False

    def get_template_context(self):
        context = super().get_template_context()

        # Make this available on self for usage in get_objects and other methods
        self.display = self.request.GET.get("display", "")

        # Make this available to get_displays and stuff
        self.objects = self.get_objects()

        page_size = self.request.GET.get("page_size", self.page_size)
        paginator = Paginator(self.objects, page_size)
        self._page = paginator.get_page(self.request.GET.get("page", 1))

        context["paginator"] = paginator
        context["page"] = self._page
        context["objects"] = self._page  # alias
        context["fields"] = self.get_fields()
        context["actions"] = self.get_actions()
        context["displays"] = self.get_displays()

        context["current_display"] = self.display

        # Implement search yourself in get_objects
        context["search_query"] = self.request.GET.get("search", "")
        context["show_search"] = self.show_search

        context["table_style"] = getattr(self, "_table_style", "default")

        context["get_object_pk"] = self.get_object_pk
        context["get_field_value"] = self.get_field_value
        context["get_field_value_template"] = self.get_field_value_template

        context["get_object_url"] = self.get_object_url
        context["get_object_links"] = self.get_object_links

        return context

    def get(self) -> Response:
        if self.is_htmx_request():
            hx_from_this_page = self.request.path in self.request.headers.get(
                "HX-Current-Url", ""
            )
            if not hx_from_this_page:
                self._table_style = "simple"
        else:
            hx_from_this_page = False

        response = super().get()

        if self.is_htmx_request() and not hx_from_this_page and not self._page:
            # Don't render anything
            return Response(status=204)

        return response

    def post(self) -> Response:
        # won't be "key" anymore, just list
        action_name = self.request.POST.get("action_name")
        actions = self.get_actions()
        if action_name and action_name in actions:
            target_pks = self.request.POST["action_pks"].split(",")
            response = self.perform_action(action_name, target_pks)
            if response:
                return response
            else:
                # message in session first
                return ResponseRedirect(".")

        raise ValueError("Invalid action")

    def perform_action(self, action: str, target_pks: list) -> Response | None:
        raise NotImplementedError

    def get_objects(self) -> list:
        return []

    def get_fields(self) -> list:
        return (
            self.fields.copy()
        )  # Avoid mutating the class attribute if using append etc

    def get_actions(self) -> dict[str]:
        return self.actions.copy()  # Avoid mutating the class attribute itself

    def get_displays(self) -> list[str]:
        return self.displays.copy()  # Avoid mutating the class attribute itself

    def get_field_value(self, obj, field: str):
        try:
            # Try basic dict lookup first
            if field in obj:
                return obj[field]
        except TypeError:
            pass

        # Try dot notation
        if "." in field:
            field, subfield = field.split(".", 1)
            return self.get_field_value(obj[field], subfield)

        # Try regular object attribute
        attr = getattr(obj, field)

        # Call if it's callable
        if callable(attr):
            return attr()
        else:
            return attr

    def get_object_pk(self, obj):
        try:
            return self.get_field_value(obj, "pk")
        except AttributeError:
            return self.get_field_value(obj, "id")

    def get_field_value_template(self, obj, field: str, value):
        type_str = type(value).__name__.lower()
        return [
            f"admin/values/{type_str}.html",  # Create a template per-type
            f"admin/values/{field}.html",  # Or for specific field names
            "admin/values/default.html",
        ]

    def get_list_url(self) -> str | None:
        return None

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, obj) -> str | None:
        return None

    def get_update_url(self, obj) -> str | None:
        return None

    def get_delete_url(self, obj) -> str | None:
        return None

    def get_object_url(self, obj) -> str | None:
        if url := self.get_detail_url(obj):
            return url
        if url := self.get_update_url(obj):
            return url
        if url := self.get_delete_url(obj):
            return url
        return None

    def get_object_links(self, obj) -> dict[str]:
        links = {}
        if self.get_detail_url(obj):
            links["View"] = self.get_detail_url(obj)
        if self.get_update_url(obj):
            links["Edit"] = self.get_update_url(obj)
        if self.get_delete_url(obj):
            links["Delete"] = self.get_delete_url(obj)
        return links

    def get_links(self):
        links = super().get_links()

        # Not tied to a specific object
        if create_url := self.get_create_url():
            links["New"] = create_url

        return links


class AdminCreateView(AdminView, CreateView):
    template_name = None

    def get_list_url(self) -> str | None:
        return None

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, obj) -> str | None:
        return None

    def get_update_url(self, obj) -> str | None:
        return None

    def get_delete_url(self, obj) -> str | None:
        return None

    def get_success_url(self, form):
        if list_url := self.get_list_url():
            return list_url

        return super().get_success_url(form)


class AdminDetailView(AdminView, DetailView):
    template_name = None
    nav_section = ""
    fields: list[str] = []

    def get_template_context(self):
        context = super().get_template_context()
        context["get_field_value"] = self.get_field_value
        context["get_field_value_template"] = self.get_field_value_template
        context["fields"] = self.get_fields()
        return context

    def get_template_names(self) -> list[str]:
        return super().get_template_names() + [
            "admin/detail.html",
        ]

    def get_description(self):
        return repr(self.object)

    def get_field_value(self, obj, field: str):
        try:
            # Try basic dict lookup first
            if field in obj:
                return obj[field]
        except TypeError:
            pass

        # Try dot notation
        if "." in field:
            field, subfield = field.split(".", 1)
            return self.get_field_value(obj[field], subfield)

        # Try regular object attribute
        attr = getattr(obj, field)

        # Call if it's callable
        if callable(attr):
            return attr()
        else:
            return attr

    def get_field_value_template(self, obj, field: str, value):
        templates = []

        # By type name
        type_str = type(value).__name__.lower()
        templates.append(f"admin/values/{type_str}.html")

        # By field name
        templates.append(f"admin/values/{field}.html")

        # As any model
        if isinstance(value, Model):
            templates.append("admin/values/model.html")

        # Default
        templates.append("admin/values/default.html")

        return templates

    def get_list_url(self) -> str | None:
        return None

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, obj) -> str | None:
        return None

    def get_update_url(self, obj) -> str | None:
        return None

    def get_delete_url(self, obj) -> str | None:
        return None

    def get_fields(self):
        return self.fields.copy()  # Avoid mutating the class attribute itself

    def get_links(self):
        links = super().get_links()

        if hasattr(self.object, "get_absolute_url"):
            links["View in app"] = self.object.get_absolute_url()

        if update_url := self.get_update_url(self.object):
            links["Edit"] = update_url

        if delete_url := self.get_delete_url(self.object):
            links["Delete"] = delete_url

        return links


class AdminUpdateView(AdminView, UpdateView):
    template_name = None
    nav_section = ""

    def get_list_url(self) -> str | None:
        return None

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, obj) -> str | None:
        return None

    def get_update_url(self, obj) -> str | None:
        return None

    def get_delete_url(self, obj) -> str | None:
        return None

    def get_description(self):
        return repr(self.object)

    def get_links(self):
        links = super().get_links()

        if hasattr(self.object, "get_absolute_url"):
            links["View in app"] = self.object.get_absolute_url()

        if detail_url := self.get_detail_url(self.object):
            links["View"] = detail_url

        if delete_url := self.get_delete_url(self.object):
            links["Delete"] = delete_url

        return links

    def get_success_url(self, form):
        if detail_url := self.get_detail_url(self.object):
            return detail_url

        if list_url := self.get_list_url():
            return list_url

        if update_url := self.get_update_url(self.object):
            return update_url

        return super().get_success_url(form)


class AdminDeleteView(AdminView, DeleteView):
    template_name = "admin/delete.html"
    nav_section = ""

    def get_description(self):
        return repr(self.object)

    def get_list_url(self) -> str | None:
        return None

    def get_create_url(self) -> str | None:
        return None

    def get_detail_url(self, obj) -> str | None:
        return None

    def get_update_url(self, obj) -> str | None:
        return None

    def get_delete_url(self, obj) -> str | None:
        return None

    def get_links(self):
        links = super().get_links()

        if hasattr(self.object, "get_absolute_url"):
            links["View in app"] = self.object.get_absolute_url()

        if detail_url := self.get_detail_url(self.object):
            links["View"] = detail_url

        if update_url := self.get_update_url(self.object):
            links["Edit"] = update_url

        return links

    def get_success_url(self, form):
        if list_url := self.get_list_url():
            return list_url

        return super().get_success_url(form)
