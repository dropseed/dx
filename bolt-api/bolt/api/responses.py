from bolt import http


class JsonResponseList(http.JsonResponse):
    openapi_description = "List of objects"

    def __init__(self, data, *args, **kwargs):
        if not isinstance(data, list):
            raise TypeError("data must be a list")
        kwargs["safe"] = False  # Allow a list to be dumped instead of a dict
        super().__init__(data, *args, **kwargs)


class JsonResponseCreated(http.JsonResponse):
    status_code = 201
    openapi_description = "Created"


class JsonResponseBadRequest(http.JsonResponse):
    status_code = 400
    openapi_description = "Bad request"


class HttpNoContentResponse(http.Response):
    status_code = 204
    openapi_description = "No content"


class Response(http.Response):
    openapi_description = "OK"


class ResponseBadRequest(http.ResponseBadRequest):
    openapi_description = "Bad request"


class ResponseNotFound(http.ResponseNotFound):
    openapi_description = "Not found"


class JsonResponse(http.JsonResponse):
    openapi_description = "OK"
