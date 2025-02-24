from typing import TYPE_CHECKING

from plain import models
from plain.models import Manager, Q

from .objects import (
    AdminCreateView,
    AdminDeleteView,
    AdminDetailView,
    AdminListView,
    AdminUpdateView,
)

if TYPE_CHECKING:
    from plain import models


def get_model_field(instance, field):
    if "__" in field:
        # Allow __ syntax like querysets use,
        # also automatically calling callables (like __date)
        result = instance
        for part in field.split("__"):
            result = getattr(result, part)

            # If we hit a None, just return it
            if not result:
                return result

            if callable(result):
                result = result()

        return result

    attr = getattr(instance, field)

    if isinstance(attr, Manager):
        # Automatically get .all() of related managers
        return attr.all()

    return attr


class AdminModelListView(AdminListView):
    show_search = True
    allow_global_search = True

    model: "models.Model"

    fields: list = ["pk"]
    queryset_order = []
    search_fields: list = ["pk"]

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return self.model._meta.model_name.capitalize() + "s"

    @classmethod
    def get_nav_title(cls) -> str:
        if cls.nav_title:
            return cls.nav_title

        if cls.title:
            return cls.title

        return cls.model._meta.model_name.capitalize() + "s"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model._meta.model_name}/"

    def get_template_context(self):
        context = super().get_template_context()

        order_by = self.request.GET.get("order_by", "")
        if order_by.startswith("-"):
            order_by_field = order_by[1:]
            order_by_direction = "-"
        else:
            order_by_field = order_by
            order_by_direction = ""

        context["order_by_field"] = order_by_field
        context["order_by_direction"] = order_by_direction

        return context

    def get_objects(self):
        queryset = self.get_initial_queryset()
        queryset = self.order_queryset(queryset)
        queryset = self.search_queryset(queryset)
        return queryset

    def get_initial_queryset(self):
        # Separate override for the initial queryset
        # so that annotations can be added BEFORE order_by, etc.
        return self.model.objects.all()

    def order_queryset(self, queryset):
        if order_by := self.request.GET.get("order_by"):
            queryset = queryset.order_by(order_by)
        elif self.queryset_order:
            queryset = queryset.order_by(*self.queryset_order)

        return queryset

    def search_queryset(self, queryset):
        if search := self.request.GET.get("search"):
            filters = Q()
            for field in self.search_fields:
                filters |= Q(**{f"{field}__icontains": search})

            queryset = queryset.filter(filters)

        return queryset

    def get_field_value(self, obj, field: str):
        try:
            return super().get_field_value(obj, field)
        except (AttributeError, TypeError):
            return get_model_field(obj, field)

    def get_field_value_template(self, obj, field: str, value):
        templates = super().get_field_value_template(obj, field, value)
        if hasattr(obj, f"get_{field}_display"):
            # Insert before the last default template,
            # so it can still be overriden by the user
            templates.insert(-1, "admin/values/get_display.html")
        return templates


class AdminModelDetailView(AdminDetailView):
    model: "models.Model"

    def get_title(self) -> str:
        return str(self.object)

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model._meta.model_name}/<int:pk>/"

    def get_fields(self):
        if fields := super().get_fields():
            return fields

        return ["pk"] + [f.name for f in self.object._meta.get_fields() if f.concrete]

    def get_field_value(self, obj, field: str):
        try:
            return super().get_field_value(obj, field)
        except (AttributeError, TypeError):
            return get_model_field(obj, field)

    def get_object(self):
        return self.model.objects.get(pk=self.url_kwargs["pk"])

    def get_template_names(self) -> list[str]:
        template_names = super().get_template_names()

        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            template_names = [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ] + template_names

        return template_names


class AdminModelCreateView(AdminCreateView):
    model: "models.Model"
    form_class = None  # TODO type annotation

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return f"New {self.model._meta.model_name}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model._meta.model_name}/create/"

    def get_template_names(self):
        template_names = super().get_template_names()

        if not self.template_name and issubclass(self.model, models.Model):
            model_meta = self.model._meta
            template_names = [
                f"admin/{model_meta.package_label}/{model_meta.model_name}{self.template_name_suffix}.html"
            ] + template_names

        return template_names


class AdminModelUpdateView(AdminUpdateView):
    model: "models.Model"
    form_class = None  # TODO type annotation
    success_url = "."  # Redirect back to the same update page by default

    def get_title(self) -> str:
        if title := super().get_title():
            return title

        return f"Update {self.object}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model._meta.model_name}/<int:pk>/update/"

    def get_object(self):
        return self.model.objects.get(pk=self.url_kwargs["pk"])

    def get_template_names(self):
        template_names = super().get_template_names()

        if not self.template_name and isinstance(self.object, models.Model):
            object_meta = self.object._meta
            template_names = [
                f"admin/{object_meta.package_label}/{object_meta.model_name}{self.template_name_suffix}.html"
            ] + template_names

        return template_names


class AdminModelDeleteView(AdminDeleteView):
    model: "models.Model"

    def get_title(self) -> str:
        return f"Delete {self.object}"

    @classmethod
    def get_path(cls) -> str:
        if path := super().get_path():
            return path

        return f"{cls.model._meta.model_name}/<int:pk>/delete/"

    def get_object(self):
        return self.model.objects.get(pk=self.url_kwargs["pk"])
