from typing import TYPE_CHECKING

from plain.auth.views import AuthViewMixin
from plain.urls import reverse
from plain.utils import timezone
from plain.views import (
    TemplateView,
)

from .registry import registry
from .types import Img

if TYPE_CHECKING:
    from ..cards import Card


URL_NAMESPACE = "admin"


class AdminView(AuthViewMixin, TemplateView):
    admin_required = True

    title: str = ""
    path: str = ""
    description: str = ""
    image: Img | None = None

    # Leave empty to hide from nav
    #
    # An explicit disabling of showing this url/page in the nav
    # which importantly effects the (future) recent pages list
    # so you can also use this for pages that can never be bookmarked
    nav_section = "App"
    nav_title = ""

    links: dict[str] = {}

    parent_view_class: "AdminView" = None

    template_name = "admin/page.html"
    cards: list["Card"] = []

    def get_response(self):
        response = super().get_response()
        response.headers["Cache-Control"] = (
            "no-cache, no-store, must-revalidate, max-age=0"
        )
        return response

    def get_template_context(self):
        context = super().get_template_context()
        context["title"] = self.get_title()
        context["image"] = self.get_image()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["links"] = self.get_links()
        context["parent_view_classes"] = self.get_parent_view_classes()
        context["admin_registry"] = registry
        context["cards"] = self.get_cards()
        context["render_card"] = lambda card: card().render(self, self.request)
        context["time_zone"] = timezone.get_current_timezone_name()
        return context

    @classmethod
    def view_name(cls) -> str:
        return f"view_{cls.get_slug()}"

    @classmethod
    def get_slug(cls) -> str:
        return f"{cls.__module__}.{cls.__qualname__}".lower().replace(".", "_")

    # Can actually use @classmethod, @staticmethod or regular method for these?
    def get_title(self) -> str:
        return self.title

    def get_image(self) -> Img | None:
        return self.image

    def get_description(self) -> str:
        return self.description

    @classmethod
    def get_path(cls) -> str:
        return cls.path

    @classmethod
    def get_parent_view_classes(cls) -> list["AdminView"]:
        parents = []
        parent = cls.parent_view_class
        while parent:
            parents.append(parent)
            parent = parent.parent_view_class
        return parents

    @classmethod
    def get_nav_section(cls) -> bool:
        if not cls.nav_section:
            return ""

        if cls.parent_view_class:
            # Don't show child views by default
            return ""

        return cls.nav_section

    @classmethod
    def get_nav_title(cls) -> str:
        if cls.nav_title:
            return cls.nav_title

        if cls.title:
            return cls.title

        raise NotImplementedError(
            f"Please set a title or nav_title on the {cls} class or implement get_nav_title()."
        )

    @classmethod
    def get_view_url(cls, obj=None) -> str:
        if obj:
            return reverse(f"{URL_NAMESPACE}:" + cls.view_name(), pk=obj.pk)
        else:
            return reverse(f"{URL_NAMESPACE}:" + cls.view_name())

    def get_links(self) -> dict[str]:
        return self.links.copy()

    def get_cards(self):
        return self.cards.copy()
