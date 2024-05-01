import json
from typing import TYPE_CHECKING, Any

from bolt.exceptions import ObjectDoesNotExist
from bolt.views.base import View
from bolt.views.csrf import CsrfExemptViewMixin
from bolt.views.exceptions import ResponseException

from .responses import (
    HttpNoContentResponse,
    JsonResponse,
    JsonResponseBadRequest,
    JsonResponseCreated,
    JsonResponseList,
    ResponseBadRequest,
    ResponseNotFound,
)

if TYPE_CHECKING:
    from bolt.forms import BaseForm


class APIBaseView(View):
    form_class: type["BaseForm"] | None = None
    # TODO removed
    http_method_names = [
        "get",
        "head",
        "options",
    ]

    def object_to_dict(self, obj):  # Intentionally untyped
        raise NotImplementedError(
            f"object_to_dict() is not implemented on {self.__class__.__name__}"
        )

    def get_form_response(
        self,
    ) -> JsonResponse | JsonResponseCreated | JsonResponseBadRequest:
        if self.form_class is None:
            raise NotImplementedError(
                f"form_class is not set on {self.__class__.__name__}"
            )

        form = self.form_class(**self.get_form_kwargs())

        if form.is_valid():
            return self.form_valid(form)
        else:
            return self.form_invalid(form)

    def get_form_kwargs(self) -> dict[str, Any]:
        if not self.request.body:
            raise ResponseException(ResponseBadRequest("No JSON body provided"))

        try:
            data = json.loads(self.request.body)
        except json.JSONDecodeError:
            raise ResponseException(
                JsonResponseBadRequest({"error": "Unable to parse JSON"})
            )

        return {
            "data": data,
            "files": self.request.FILES,
        }

    def form_valid(self, form: "BaseForm") -> JsonResponse | JsonResponseCreated:
        """
        Used for PUT and PATCH requests.
        Can check self.request.method if you want different behavior.
        """
        object = form.save()  # type: ignore
        data = self.object_to_dict(object)

        if self.request.method == "POST":
            return JsonResponseCreated(
                data,
                json_dumps_params={
                    "sort_keys": True,
                },
            )
        else:
            return JsonResponse(
                data,
                json_dumps_params={
                    "sort_keys": True,
                },
            )

    def form_invalid(self, form: "BaseForm") -> JsonResponseBadRequest:
        return JsonResponseBadRequest(
            {"message": "Invalid input", "errors": form.errors.get_json_data()},
        )


class APIObjectListView(CsrfExemptViewMixin, APIBaseView):
    def load_objects(self) -> None:
        try:
            self.objects = self.get_objects()
        except ObjectDoesNotExist:
            # Custom 404 with no body
            raise ResponseException(ResponseNotFound())

        if not self.objects:
            # Also raise 404 if the object is None
            raise ResponseException(ResponseNotFound())

    def get_objects(self):  # Intentionally untyped for subclasses to type
        raise NotImplementedError(
            f"get_objects() is not implemented on {self.__class__.__name__}"
        )

    def get(self) -> JsonResponseList | ResponseNotFound | ResponseBadRequest:
        self.load_objects()
        # TODO paginate??
        data = [self.object_to_dict(obj) for obj in self.objects]
        return JsonResponseList(data)

    def post(
        self,
    ) -> JsonResponseCreated | ResponseNotFound | ResponseBadRequest:
        self.load_objects()
        return self.get_form_response()  # type: ignore


class APIObjectView(CsrfExemptViewMixin, APIBaseView):
    """Similar to a DetailView but without all of the context and template logic."""

    def load_object(self) -> None:
        try:
            self.object = self.get_object()
        except ObjectDoesNotExist:
            # Custom 404 with no body
            raise ResponseException(ResponseNotFound())

        if not self.object:
            # Also raise 404 if the object is None
            raise ResponseException(ResponseNotFound())

    def get_object(self):  # Intentionally untyped for subclasses to type
        """
        Get an instance of an object (typically a model instance).

        Authorization should be done here too.
        """
        raise NotImplementedError(
            f"get_object() is not implemented on {self.__class__.__name__}"
        )

    def get_form_kwargs(self) -> dict[str, Any]:
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.object
        return kwargs

    def get(self) -> JsonResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        data = self.object_to_dict(self.object)
        return JsonResponse(data)

    def put(self) -> JsonResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        return self.get_form_response()

    def patch(self) -> JsonResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        return self.get_form_response()

    def delete(
        self,
    ) -> HttpNoContentResponse | ResponseNotFound | ResponseBadRequest:
        self.load_object()
        self.object.delete()
        return HttpNoContentResponse()
