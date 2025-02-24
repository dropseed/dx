from enum import Enum

from plain.http import HttpRequest
from plain.templates import Template
from plain.views import View


class Card:
    class Sizes(Enum):
        # Four column grid
        SMALL = 1
        MEDIUM = 2
        LARGE = 3
        FULL = 4

    template_name = "admin/cards/card.html"
    size: Sizes = Sizes.SMALL
    # unique_id: str  # Use for tying to dashboards, require it

    # Required fields
    title: str

    # Optional fields
    description: str = ""
    text: str = ""
    link: str = ""
    number: int | None = None
    displays: list[str] | Enum | None = None

    # These will be accessible at render time
    view: View
    request: HttpRequest

    def render(self, view, request):
        self.view = view
        self.request = request
        return Template(self.template_name).render(self.get_template_context())

    @classmethod
    def view_name(cls) -> str:
        return f"card_{cls.get_slug()}"

    def get_template_context(self):
        context = {}

        context["size"] = self.size
        context["title"] = self.get_title()
        context["slug"] = self.get_slug()
        context["description"] = self.get_description()
        context["number"] = self.get_number()
        context["text"] = self.get_text()
        context["link"] = self.get_link()
        context["displays"] = self.get_displays()
        context["current_display"] = self.get_current_display()

        return context

    def get_title(self) -> str:
        return self.title

    @classmethod
    def get_slug(cls) -> str:
        return f"{cls.__module__}.{cls.__name__}".lower().replace(".", "_")

    def get_description(self) -> str:
        return self.description

    def get_number(self) -> int | None:
        return self.number

    def get_text(self) -> str:
        return self.text

    def get_link(self) -> str:
        return self.link

    def get_current_display(self) -> str:
        return self.request.GET.get(f"{self.get_slug()}.display", "")

    def get_displays(self) -> list[str] | Enum | None:
        if hasattr(self.displays, "copy"):
            # Avoid mutating the class attribute
            return self.displays.copy()
        else:
            return self.displays
