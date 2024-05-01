# from bolt.exceptions import ValidationError

# class APIFormMixin:
#     def clean(self):
#         cleaned_data = super().clean()

#         # Make sure all the field names are present in the input data
#         for name, field in self.fields.items():
#             if name not in self.data:
#                 raise ValidationError(f"Missing field {name}")

#         return cleaned_data


class APIPartialFormMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # If any field is not present in the JSON input,
        # then act as if it's "disabled" so Bolt
        # will keep the initial value instead of setting it to the default.
        # This is required because stuff like checkbox doesn't submit in HTML form data when false.
        for name, field in self.fields.items():
            if name not in self.data:
                field.disabled = True
