from typing import Any
from uuid import UUID

from bolt.forms import fields
from bolt.urls.converters import get_converters
from bolt.views import View

from .responses import JsonResponse, JsonResponseCreated, JsonResponseList
from .views import APIBaseView


class OpenAPISchemaView(View):
    openapi_title: str
    openapi_version: str
    openapi_urlconf: str

    def get(self):
        # TODO can heaviliy cache this - browser headers? or cache the schema obj?
        return JsonResponse(
            OpenAPISchema(
                title=self.openapi_title,
                version=self.openapi_version,
                urlconf=self.openapi_urlconf,
            ),
            json_dumps_params={"sort_keys": True},
        )


class OpenAPISchema(dict):
    def __init__(self, *, title: str, version: str, urlconf="api.urls"):
        self.urlconf = urlconf
        self.url_converters = {
            class_instance.__class__: key
            for key, class_instance in get_converters().items()
        }
        paths = self.get_paths()
        super().__init__(
            openapi="3.0.0",
            info={
                "title": title,
                "version": version,
                # **moreinfo, or info is a dict?
            },
            paths=paths,
            #               "404": {
            #     "$ref": "#/components/responses/not_found"
            #   },
            #   "422": {
            #     "$ref": "#/components/responses/validation_failed_simple"
            #   }
        )

    # def extract_components(self, paths):
    #     """Look through the paths and find and repeated definitions
    #     that can be pulled out as components."""
    #     from collections import Counter
    #     components = Counter()
    #     for path in paths.values():

    def get_paths(self) -> dict[str, dict[str, Any]]:
        from bolt.urls import get_resolver

        resolver = get_resolver(self.urlconf)
        paths = {}

        for url_pattern in resolver.url_patterns:
            for pattern, root_path in self.url_patterns_from_url_pattern(
                url_pattern, "/"
            ):
                path = self.path_from_url_pattern(pattern, root_path)
                if operations := self.operations_from_url_pattern(pattern):
                    paths[path] = operations
                    if parameters := self.parameters_from_url_patterns(
                        [url_pattern, pattern]
                    ):
                        # Assume all methods have the same parameters for now (path params)
                        for method in operations:
                            operations[method]["parameters"] = parameters

        return paths

    def url_patterns_from_url_pattern(self, url_pattern, root_path) -> list:
        if hasattr(url_pattern, "url_patterns"):
            include_path = self.path_from_url_pattern(url_pattern, root_path)
            url_patterns = []
            for u in url_pattern.url_patterns:
                url_patterns.extend(self.url_patterns_from_url_pattern(u, include_path))
            return url_patterns
        else:
            return [(url_pattern, root_path)]

    def path_from_url_pattern(self, url_pattern, root_path) -> str:
        path = root_path + str(url_pattern.pattern)

        for name, converter in url_pattern.pattern.converters.items():
            key = self.url_converters[converter.__class__]
            path = path.replace(f"<{key}:{name}>", f"{{{name}}}")
        return path

    def parameters_from_url_patterns(self, url_patterns) -> list[dict[str, Any]]:
        """Need to process any parent/included url patterns too"""
        parameters = []

        for url_pattern in url_patterns:
            for name, converter in url_pattern.pattern.converters.items():
                parameters.append(
                    {
                        "name": name,
                        "in": "path",
                        "required": True,
                        "schema": {
                            "type": "string",
                            "pattern": converter.regex,
                            # "format": "uuid",
                        },
                    }
                )

        return parameters

    def operations_from_url_pattern(self, url_pattern) -> dict[str, Any]:
        view_class = url_pattern.callback.view_class

        if not issubclass(view_class, APIBaseView):
            return {}

        operations = {}
        # TODO removed
        for method in view_class.http_method_names:
            if method in ("head", "options", "trace"):
                # Techinically these can be listed too...
                continue

            if responses := self.responses_from_class_method(view_class, method):
                operations[method] = {
                    "responses": responses,
                }

            if parameters := self.request_body_from_class_method(view_class, method):
                operations[method]["requestBody"] = parameters

        return operations

    def request_body_from_class_method(self, view_class, method: str) -> dict:
        """Gets parameters from the form_class on a view"""

        if method not in ("post", "put", "patch"):
            return {}

        form_class = view_class.form_class
        if not form_class:
            return {}

        parameters = []
        # Any args or kwargs in form.__init__ need to be optional
        # for this to work...
        for name, field in form_class().fields.items():
            parameters.append(
                {
                    "name": name,
                    # "in": "query",
                    # "required": field.required,
                    "schema": self.type_to_schema_obj(field),
                }
            )

        return {
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {p["name"]: p["schema"] for p in parameters},
                    }
                },
            },
        }

    def responses_from_class_method(
        self, view_class, method: str
    ) -> dict[str, dict[str, Any]]:
        class_method = getattr(view_class, method)
        return_type = class_method.__annotations__["return"]

        if hasattr(return_type, "status_code"):
            return_types = [return_type]
        else:
            # Assume union...
            return_types = return_type.__args__

        responses: dict[str, dict[str, Any]] = {}

        for return_type in return_types:
            if return_type is JsonResponse or return_type is JsonResponseCreated:
                schema = self.type_to_schema_obj(
                    view_class.object_to_dict.__annotations__["return"]
                )

                content = {"application/json": {"schema": schema}}
            elif return_type is JsonResponseList:
                schema = self.type_to_schema_obj(
                    view_class.object_to_dict.__annotations__["return"]
                )

                content = {
                    "application/json": {
                        "schema": {
                            "type": "array",
                            "items": schema,
                        }
                    }
                }
            else:
                content = None

            response_key = str(return_type.status_code)
            responses[response_key] = {}

            if description := getattr(return_type, "openapi_description", ""):
                responses[response_key]["description"] = description

            responses["5XX"] = {
                "description": "Server error",
            }

            if content:
                responses[response_key]["content"] = content

        return responses

    def type_to_schema_obj(self, t) -> dict[str, Any]:
        # if it's a union with None, add nullable: true

        # if t has a comment, add description
        # import inspect
        # if description := inspect.getdoc(t):
        #     extra_fields = {"description": description}
        # else:
        extra_fields: dict[str, Any] = {}

        if hasattr(t, "__annotations__") and t.__annotations__:
            # It's a TypedDict...
            return {
                "type": "object",
                "properties": {
                    k: self.type_to_schema_obj(v) for k, v in t.__annotations__.items()
                },
                **extra_fields,
            }

        if hasattr(t, "__origin__"):
            if t.__origin__ is list:
                return {
                    "type": "array",
                    "items": self.type_to_schema_obj(t.__args__[0]),
                    **extra_fields,
                }
            elif t.__origin__ is dict:
                return {
                    "type": "object",
                    "properties": {
                        k: self.type_to_schema_obj(v)
                        for k, v in t.__args__[1].__annotations__.items()
                    },
                    **extra_fields,
                }
            else:
                raise ValueError(f"Unknown type: {t}")

        if hasattr(t, "__args__") and len(t.__args__) == 2 and type(None) in t.__args__:
            return {
                **self.type_to_schema_obj(t.__args__[0]),
                "nullable": True,
                **extra_fields,
            }

        type_mappings: dict[Any, dict] = {
            str: {
                "type": "string",
            },
            int: {
                "type": "integer",
            },
            float: {
                "type": "number",
            },
            bool: {
                "type": "boolean",
            },
            dict: {
                "type": "object",
            },
            list: {
                "type": "array",
            },
            UUID: {
                "type": "string",
                "format": "uuid",
            },
            fields.IntegerField: {
                "type": "integer",
            },
            fields.FloatField: {
                "type": "number",
            },
            fields.DateTimeField: {
                "type": "string",
                "format": "date-time",
            },
            fields.DateField: {
                "type": "string",
                "format": "date",
            },
            fields.TimeField: {
                "type": "string",
                "format": "time",
            },
            fields.EmailField: {
                "type": "string",
                "format": "email",
            },
            fields.URLField: {
                "type": "string",
                "format": "uri",
            },
            fields.UUIDField: {
                "type": "string",
                "format": "uuid",
            },
            fields.DecimalField: {
                "type": "number",
            },
            # fields.FileField: {
            #     "type": "string",
            #     "format": "binary",
            # },
            fields.ImageField: {
                "type": "string",
                "format": "binary",
            },
            fields.BooleanField: {
                "type": "boolean",
            },
            fields.NullBooleanField: {
                "type": "boolean",
                "nullable": True,
            },
            fields.CharField: {
                "type": "string",
            },
            fields.SlugField: {
                "type": "string",
            },
            fields.EmailField: {
                "type": "string",
                "format": "email",
            },
            fields.FilePathField: {
                "type": "string",
            },
        }

        schema = type_mappings.get(t, {})
        if not schema:
            schema = type_mappings.get(t.__class__, {})
            if not schema:
                raise ValueError(f"Unknown type: {t}")

        return {**schema, **extra_fields}
