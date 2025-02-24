"""
Field classes.
"""

import copy
import datetime
import json
import math
import re
import uuid
from decimal import Decimal, DecimalException
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit

from plain import validators
from plain.exceptions import ValidationError
from plain.utils import timezone
from plain.utils.dateparse import parse_datetime, parse_duration
from plain.utils.duration import duration_string
from plain.utils.regex_helper import _lazy_re_compile
from plain.utils.text import pluralize_lazy

from .boundfield import BoundField
from .exceptions import FormFieldMissingError

__all__ = (
    "Field",
    "CharField",
    "IntegerField",
    "DateField",
    "TimeField",
    "DateTimeField",
    "DurationField",
    "RegexField",
    "EmailField",
    "FileField",
    "ImageField",
    "URLField",
    "BooleanField",
    "NullBooleanField",
    "ChoiceField",
    "MultipleChoiceField",
    "FloatField",
    "DecimalField",
    "JSONField",
    "SlugField",
    "TypedChoiceField",
    "UUIDField",
)


FILE_INPUT_CONTRADICTION = object()


class Field:
    default_validators = []  # Default set of validators
    # Add an 'invalid' entry to default_error_message if you want a specific
    # field error message not raised by the field validators.
    default_error_messages = {
        "required": "This field is required.",
    }
    empty_values = list(validators.EMPTY_VALUES)

    def __init__(
        self,
        *,
        required=True,
        initial=None,
        error_messages=None,
        validators=(),
        disabled=False,
    ):
        # required -- Boolean that specifies whether the field is required.
        #             True by default.
        # widget -- A Widget class, or instance of a Widget class, that should
        #           be used for this Field when displaying it. Each Field has a
        #           default Widget that it'll use if you don't specify this. In
        #           most cases, the default widget is TextInput.
        # initial -- A value to use in this Field's initial display. This value
        #            is *not* used as a fallback if data isn't given.
        # error_messages -- An optional dictionary to override the default
        #                   messages that the field will raise.
        # validators -- List of additional validators to use
        # disabled -- Boolean that specifies whether the field is disabled, that
        #             is its widget is shown in the form but not editable.
        self.required, self.initial = required, initial
        self.disabled = disabled

        messages = {}
        for c in reversed(self.__class__.__mro__):
            messages.update(getattr(c, "default_error_messages", {}))
        messages.update(error_messages or {})
        self.error_messages = messages

        self.validators = [*self.default_validators, *validators]

    def prepare_value(self, value):
        return value

    def to_python(self, value):
        return value

    def validate(self, value):
        if value in self.empty_values and self.required:
            raise ValidationError(self.error_messages["required"], code="required")

    def run_validators(self, value):
        if value in self.empty_values:
            return
        errors = []
        for v in self.validators:
            try:
                v(value)
            except ValidationError as e:
                if hasattr(e, "code") and e.code in self.error_messages:
                    e.message = self.error_messages[e.code]
                errors.extend(e.error_list)
        if errors:
            raise ValidationError(errors)

    def clean(self, value):
        """
        Validate the given value and return its "cleaned" value as an
        appropriate Python object. Raise ValidationError for any errors.
        """
        value = self.to_python(value)
        self.validate(value)
        self.run_validators(value)
        return value

    def bound_data(self, data, initial):
        """
        Return the value that should be shown for this field on render of a
        bound form, given the submitted POST data for the field and the initial
        data, if any.

        For most fields, this will simply be data; FileFields need to handle it
        a bit differently.
        """
        if self.disabled:
            return initial
        return data

    def has_changed(self, initial, data):
        """Return True if data differs from initial."""
        # Always return False if the field is disabled since self.bound_data
        # always uses the initial value in this case.
        if self.disabled:
            return False
        try:
            data = self.to_python(data)
            if hasattr(self, "_coerce"):
                return self._coerce(data) != self._coerce(initial)
        except ValidationError:
            return True
        # For purposes of seeing whether something has changed, None is
        # the same as an empty string, if the data or initial value we get
        # is None, replace it with ''.
        initial_value = initial if initial is not None else ""
        data_value = data if data is not None else ""
        return initial_value != data_value

    def get_bound_field(self, form, field_name):
        """
        Return a BoundField instance that will be used when accessing the form
        field in a template.
        """
        return BoundField(form, self, field_name)

    def __deepcopy__(self, memo):
        result = copy.copy(self)
        memo[id(self)] = result
        result.error_messages = self.error_messages.copy()
        result.validators = self.validators[:]
        return result

    def value_from_form_data(self, data, files, html_name):
        try:
            return data[html_name]
        except KeyError as e:
            raise FormFieldMissingError(
                f'The "{html_name}" field is missing from the form data.'
            ) from e


class CharField(Field):
    def __init__(
        self, *, max_length=None, min_length=None, strip=True, empty_value="", **kwargs
    ):
        self.max_length = max_length
        self.min_length = min_length
        self.strip = strip
        self.empty_value = empty_value
        super().__init__(**kwargs)
        if min_length is not None:
            self.validators.append(validators.MinLengthValidator(int(min_length)))
        if max_length is not None:
            self.validators.append(validators.MaxLengthValidator(int(max_length)))
        self.validators.append(validators.ProhibitNullCharactersValidator())

    def to_python(self, value):
        """Return a string."""
        if value not in self.empty_values:
            value = str(value)
            if self.strip:
                value = value.strip()
        if value in self.empty_values:
            return self.empty_value
        return value


class IntegerField(Field):
    default_error_messages = {
        "invalid": "Enter a whole number.",
    }
    re_decimal = _lazy_re_compile(r"\.0*\s*$")

    def __init__(self, *, max_value=None, min_value=None, step_size=None, **kwargs):
        self.max_value, self.min_value, self.step_size = max_value, min_value, step_size
        super().__init__(**kwargs)

        if max_value is not None:
            self.validators.append(validators.MaxValueValidator(max_value))
        if min_value is not None:
            self.validators.append(validators.MinValueValidator(min_value))
        if step_size is not None:
            self.validators.append(validators.StepValueValidator(step_size))

    def to_python(self, value):
        """
        Validate that int() can be called on the input. Return the result
        of int() or None for empty values.
        """
        value = super().to_python(value)
        if value in self.empty_values:
            return None
        # Strip trailing decimal and zeros.
        try:
            value = int(self.re_decimal.sub("", str(value)))
        except (ValueError, TypeError):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return value


class FloatField(IntegerField):
    default_error_messages = {
        "invalid": "Enter a number.",
    }

    def to_python(self, value):
        """
        Validate that float() can be called on the input. Return the result
        of float() or None for empty values.
        """
        value = super(IntegerField, self).to_python(value)
        if value in self.empty_values:
            return None
        try:
            value = float(value)
        except (ValueError, TypeError):
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return value

    def validate(self, value):
        super().validate(value)
        if value in self.empty_values:
            return
        if not math.isfinite(value):
            raise ValidationError(self.error_messages["invalid"], code="invalid")


class DecimalField(IntegerField):
    default_error_messages = {
        "invalid": "Enter a number.",
    }

    def __init__(
        self,
        *,
        max_value=None,
        min_value=None,
        max_digits=None,
        decimal_places=None,
        **kwargs,
    ):
        self.max_digits, self.decimal_places = max_digits, decimal_places
        super().__init__(max_value=max_value, min_value=min_value, **kwargs)
        self.validators.append(validators.DecimalValidator(max_digits, decimal_places))

    def to_python(self, value):
        """
        Validate that the input is a decimal number. Return a Decimal
        instance or None for empty values. Ensure that there are no more
        than max_digits in the number and no more than decimal_places digits
        after the decimal point.
        """
        if value in self.empty_values:
            return None
        try:
            value = Decimal(str(value))
        except DecimalException:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return value

    def validate(self, value):
        super().validate(value)
        if value in self.empty_values:
            return
        if not value.is_finite():
            raise ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )


class BaseTemporalField(Field):
    # Default formats to be used when parsing dates from input boxes, in order
    # See all available format string here:
    # https://docs.python.org/library/datetime.html#strftime-behavior
    # * Note that these format strings are different from the ones to display dates
    DATE_INPUT_FORMATS = [
        "%Y-%m-%d",  # '2006-10-25'
        "%m/%d/%Y",  # '10/25/2006'
        "%m/%d/%y",  # '10/25/06'
        "%b %d %Y",  # 'Oct 25 2006'
        "%b %d, %Y",  # 'Oct 25, 2006'
        "%d %b %Y",  # '25 Oct 2006'
        "%d %b, %Y",  # '25 Oct, 2006'
        "%B %d %Y",  # 'October 25 2006'
        "%B %d, %Y",  # 'October 25, 2006'
        "%d %B %Y",  # '25 October 2006'
        "%d %B, %Y",  # '25 October, 2006'
    ]

    # Default formats to be used when parsing times from input boxes, in order
    # See all available format string here:
    # https://docs.python.org/library/datetime.html#strftime-behavior
    # * Note that these format strings are different from the ones to display dates
    TIME_INPUT_FORMATS = [
        "%H:%M:%S",  # '14:30:59'
        "%H:%M:%S.%f",  # '14:30:59.000200'
        "%H:%M",  # '14:30'
    ]

    # Default formats to be used when parsing dates and times from input boxes,
    # in order
    # See all available format string here:
    # https://docs.python.org/library/datetime.html#strftime-behavior
    # * Note that these format strings are different from the ones to display dates
    DATETIME_INPUT_FORMATS = [
        "%Y-%m-%d %H:%M:%S",  # '2006-10-25 14:30:59'
        "%Y-%m-%d %H:%M:%S.%f",  # '2006-10-25 14:30:59.000200'
        "%Y-%m-%d %H:%M",  # '2006-10-25 14:30'
        "%m/%d/%Y %H:%M:%S",  # '10/25/2006 14:30:59'
        "%m/%d/%Y %H:%M:%S.%f",  # '10/25/2006 14:30:59.000200'
        "%m/%d/%Y %H:%M",  # '10/25/2006 14:30'
        "%m/%d/%y %H:%M:%S",  # '10/25/06 14:30:59'
        "%m/%d/%y %H:%M:%S.%f",  # '10/25/06 14:30:59.000200'
        "%m/%d/%y %H:%M",  # '10/25/06 14:30'
    ]

    def __init__(self, *, input_formats=None, **kwargs):
        super().__init__(**kwargs)
        if input_formats is not None:
            self.input_formats = input_formats

    def to_python(self, value):
        value = value.strip()
        # Try to strptime against each input format.
        for format in self.input_formats:
            try:
                return self.strptime(value, format)
            except (ValueError, TypeError):
                continue
        raise ValidationError(self.error_messages["invalid"], code="invalid")

    def strptime(self, value, format):
        raise NotImplementedError("Subclasses must define this method.")


class DateField(BaseTemporalField):
    input_formats = BaseTemporalField.DATE_INPUT_FORMATS
    default_error_messages = {
        "invalid": "Enter a valid date.",
    }

    def to_python(self, value):
        """
        Validate that the input can be converted to a date. Return a Python
        datetime.date object.
        """
        if value in self.empty_values:
            return None
        if isinstance(value, datetime.datetime):
            return value.date()
        if isinstance(value, datetime.date):
            return value
        return super().to_python(value)

    def strptime(self, value, format):
        return datetime.datetime.strptime(value, format).date()


class TimeField(BaseTemporalField):
    input_formats = BaseTemporalField.TIME_INPUT_FORMATS
    default_error_messages = {"invalid": "Enter a valid time."}

    def to_python(self, value):
        """
        Validate that the input can be converted to a time. Return a Python
        datetime.time object.
        """
        if value in self.empty_values:
            return None
        if isinstance(value, datetime.time):
            return value
        return super().to_python(value)

    def strptime(self, value, format):
        return datetime.datetime.strptime(value, format).time()


class DateTimeFormatsIterator:
    def __iter__(self):
        yield from BaseTemporalField.DATETIME_INPUT_FORMATS
        yield from BaseTemporalField.DATE_INPUT_FORMATS


class DateTimeField(BaseTemporalField):
    input_formats = DateTimeFormatsIterator()
    default_error_messages = {
        "invalid": "Enter a valid date/time.",
    }

    def prepare_value(self, value):
        if isinstance(value, datetime.datetime):
            value = to_current_timezone(value)
        return value

    def to_python(self, value):
        """
        Validate that the input can be converted to a datetime. Return a
        Python datetime.datetime object.
        """
        if value in self.empty_values:
            return None
        if isinstance(value, datetime.datetime):
            return from_current_timezone(value)
        if isinstance(value, datetime.date):
            result = datetime.datetime(value.year, value.month, value.day)
            return from_current_timezone(result)
        try:
            result = parse_datetime(value.strip())
        except ValueError:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        if not result:
            result = super().to_python(value)
        return from_current_timezone(result)

    def strptime(self, value, format):
        return datetime.datetime.strptime(value, format)


class DurationField(Field):
    default_error_messages = {
        "invalid": "Enter a valid duration.",
        "overflow": "The number of days must be between {min_days} and {max_days}.",
    }

    def prepare_value(self, value):
        if isinstance(value, datetime.timedelta):
            return duration_string(value)
        return value

    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, datetime.timedelta):
            return value
        try:
            value = parse_duration(str(value))
        except OverflowError:
            raise ValidationError(
                self.error_messages["overflow"].format(
                    min_days=datetime.timedelta.min.days,
                    max_days=datetime.timedelta.max.days,
                ),
                code="overflow",
            )
        if value is None:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        return value


class RegexField(CharField):
    def __init__(self, regex, **kwargs):
        """
        regex can be either a string or a compiled regular expression object.
        """
        kwargs.setdefault("strip", False)
        super().__init__(**kwargs)
        self._set_regex(regex)

    def _get_regex(self):
        return self._regex

    def _set_regex(self, regex):
        if isinstance(regex, str):
            regex = re.compile(regex)
        self._regex = regex
        if (
            hasattr(self, "_regex_validator")
            and self._regex_validator in self.validators
        ):
            self.validators.remove(self._regex_validator)
        self._regex_validator = validators.RegexValidator(regex=regex)
        self.validators.append(self._regex_validator)

    regex = property(_get_regex, _set_regex)


class EmailField(CharField):
    default_validators = [validators.validate_email]

    def __init__(self, **kwargs):
        super().__init__(strip=True, **kwargs)


class FileField(Field):
    default_error_messages = {
        "invalid": "No file was submitted. Check the encoding type on the form.",
        "missing": "No file was submitted.",
        "empty": "The submitted file is empty.",
        "text": pluralize_lazy(
            "Ensure this filename has at most %(max)d character (it has %(length)d).",
            "Ensure this filename has at most %(max)d characters (it has %(length)d).",
            "max",
        ),
        "contradiction": "Please either submit a file or check the clear checkbox, not both.",
    }

    def __init__(self, *, max_length=None, allow_empty_file=False, **kwargs):
        self.max_length = max_length
        self.allow_empty_file = allow_empty_file
        super().__init__(**kwargs)

    def to_python(self, data):
        if data in self.empty_values:
            return None

        # UploadedFile objects should have name and size attributes.
        try:
            file_name = data.name
            file_size = data.size
        except AttributeError:
            raise ValidationError(self.error_messages["invalid"], code="invalid")

        if self.max_length is not None and len(file_name) > self.max_length:
            params = {"max": self.max_length, "length": len(file_name)}
            raise ValidationError(
                self.error_messages["max_length"], code="max_length", params=params
            )
        if not file_name:
            raise ValidationError(self.error_messages["invalid"], code="invalid")
        if not self.allow_empty_file and not file_size:
            raise ValidationError(self.error_messages["empty"], code="empty")

        return data

    def clean(self, data, initial=None):
        # If the widget got contradictory inputs, we raise a validation error
        if data is FILE_INPUT_CONTRADICTION:
            raise ValidationError(
                self.error_messages["contradiction"], code="contradiction"
            )
        # False means the field value should be cleared; further validation is
        # not needed.
        if data is False:
            if not self.required:
                return False
            # If the field is required, clearing is not possible (the widget
            # shouldn't return False data in that case anyway). False is not
            # in self.empty_value; if a False value makes it this far
            # it should be validated from here on out as None (so it will be
            # caught by the required check).
            data = None
        if not data and initial:
            return initial
        return super().clean(data)

    def bound_data(self, _, initial):
        return initial

    def has_changed(self, initial, data):
        return not self.disabled and data is not None

    def value_from_form_data(self, data, files, html_name):
        return files.get(html_name)


class ImageField(FileField):
    default_validators = [validators.validate_image_file_extension]
    default_error_messages = {
        "invalid_image": "Upload a valid image. The file you uploaded was either not an image or a corrupted image.",
    }

    def to_python(self, data):
        """
        Check that the file-upload field data contains a valid image (GIF, JPG,
        PNG, etc. -- whatever Pillow supports).
        """
        f = super().to_python(data)
        if f is None:
            return None

        from PIL import Image

        # We need to get a file object for Pillow. We might have a path or we might
        # have to read the data into memory.
        if hasattr(data, "temporary_file_path"):
            file = data.temporary_file_path()
        else:
            if hasattr(data, "read"):
                file = BytesIO(data.read())
            else:
                file = BytesIO(data["content"])

        try:
            # load() could spot a truncated JPEG, but it loads the entire
            # image in memory, which is a DoS vector. See #3848 and #18520.
            image = Image.open(file)
            # verify() must be called immediately after the constructor.
            image.verify()

            # Annotating so subclasses can reuse it for their own validation
            f.image = image
            # Pillow doesn't detect the MIME type of all formats. In those
            # cases, content_type will be None.
            f.content_type = Image.MIME.get(image.format)
        except Exception as exc:
            # Pillow doesn't recognize it as an image.
            raise ValidationError(
                self.error_messages["invalid_image"],
                code="invalid_image",
            ) from exc
        if hasattr(f, "seek") and callable(f.seek):
            f.seek(0)
        return f


class URLField(CharField):
    default_error_messages = {
        "invalid": "Enter a valid URL.",
    }
    default_validators = [validators.URLValidator()]

    def __init__(self, **kwargs):
        super().__init__(strip=True, **kwargs)

    def to_python(self, value):
        def split_url(url):
            """
            Return a list of url parts via urlparse.urlsplit(), or raise
            ValidationError for some malformed URLs.
            """
            try:
                return list(urlsplit(url))
            except ValueError:
                # urlparse.urlsplit can raise a ValueError with some
                # misformatted URLs.
                raise ValidationError(self.error_messages["invalid"], code="invalid")

        value = super().to_python(value)
        if value:
            url_fields = split_url(value)
            if not url_fields[0]:
                # If no URL scheme given, assume http://
                url_fields[0] = "http"
            if not url_fields[1]:
                # Assume that if no domain is provided, that the path segment
                # contains the domain.
                url_fields[1] = url_fields[2]
                url_fields[2] = ""
                # Rebuild the url_fields list, since the domain segment may now
                # contain the path too.
                url_fields = split_url(urlunsplit(url_fields))
            value = urlunsplit(url_fields)
        return value


class BooleanField(Field):
    def to_python(self, value):
        """Return a Python boolean object."""
        # Explicitly check for the string 'False', which is what a hidden field
        # will submit for False. Also check for '0', since this is what
        # RadioSelect will provide. Because bool("True") == bool('1') == True,
        # we don't need to handle that explicitly.
        if isinstance(value, str) and value.lower() in ("false", "0"):
            value = False
        else:
            value = bool(value)
        return super().to_python(value)

    def validate(self, value):
        if not value and self.required:
            raise ValidationError(self.error_messages["required"], code="required")

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        # Sometimes data or initial may be a string equivalent of a boolean
        # so we should run it through to_python first to get a boolean value
        return self.to_python(initial) != self.to_python(data)

    def value_from_form_data(self, data, files, html_name):
        if html_name not in data:
            # Unselected checkboxes aren't in HTML form data, so return False
            return False

        value = data.get(html_name)
        # Translate true and false strings to boolean values.
        return {
            True: True,
            "True": True,
            "False": False,
            False: False,
            "true": True,
            "false": False,
            "on": True,
        }.get(value)


class NullBooleanField(BooleanField):
    """
    A field whose valid values are None, True, and False. Clean invalid values
    to None.
    """

    def to_python(self, value):
        """
        Explicitly check for the string 'True' and 'False', which is what a
        hidden field will submit for True and False, for 'true' and 'false',
        which are likely to be returned by JavaScript serializations of forms,
        and for '1' and '0', which is what a RadioField will submit. Unlike
        the Booleanfield, this field must check for True because it doesn't
        use the bool() function.
        """
        if value in (True, "True", "true", "1"):
            return True
        elif value in (False, "False", "false", "0"):
            return False
        else:
            return None

    def validate(self, value):
        pass


class CallableChoiceIterator:
    def __init__(self, choices_func):
        self.choices_func = choices_func

    def __iter__(self):
        yield from self.choices_func()


class ChoiceField(Field):
    default_error_messages = {
        "invalid_choice": "Select a valid choice. %(value)s is not one of the available choices.",
    }

    def __init__(self, *, choices=(), **kwargs):
        super().__init__(**kwargs)
        if hasattr(choices, "choices"):
            choices = choices.choices
        self.choices = choices

    def __deepcopy__(self, memo):
        result = super().__deepcopy__(memo)
        result._choices = copy.deepcopy(self._choices, memo)
        return result

    def _get_choices(self):
        return self._choices

    def _set_choices(self, value):
        # Setting choices also sets the choices on the widget.
        # choices can be any iterable, but we call list() on it because
        # it will be consumed more than once.
        if callable(value):
            value = CallableChoiceIterator(value)
        else:
            value = list(value)

        self._choices = value

    choices = property(_get_choices, _set_choices)

    def to_python(self, value):
        """Return a string."""
        if value in self.empty_values:
            return ""
        return str(value)

    def validate(self, value):
        """Validate that the input is in self.choices."""
        super().validate(value)
        if value and not self.valid_value(value):
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )

    def valid_value(self, value):
        """Check to see if the provided value is a valid choice."""
        text_value = str(value)
        for k, v in self.choices:
            if isinstance(v, list | tuple):
                # This is an optgroup, so look inside the group for options
                for k2, _ in v:
                    if value == k2 or text_value == str(k2):
                        return True
            else:
                if value == k or text_value == str(k):
                    return True
        return False


class TypedChoiceField(ChoiceField):
    def __init__(self, *, coerce=lambda val: val, empty_value="", **kwargs):
        self.coerce = coerce
        self.empty_value = empty_value
        super().__init__(**kwargs)

    def _coerce(self, value):
        """
        Validate that the value can be coerced to the right type (if not empty).
        """
        if value == self.empty_value or value in self.empty_values:
            return self.empty_value
        try:
            value = self.coerce(value)
        except (ValueError, TypeError, ValidationError):
            raise ValidationError(
                self.error_messages["invalid_choice"],
                code="invalid_choice",
                params={"value": value},
            )
        return value

    def clean(self, value):
        value = super().clean(value)
        return self._coerce(value)


class MultipleChoiceField(ChoiceField):
    default_error_messages = {
        "invalid_choice": "Select a valid choice. %(value)s is not one of the available choices.",
        "invalid_list": "Enter a list of values.",
    }

    def to_python(self, value):
        if not value:
            return []
        elif not isinstance(value, list | tuple):
            raise ValidationError(
                self.error_messages["invalid_list"], code="invalid_list"
            )
        return [str(val) for val in value]

    def validate(self, value):
        """Validate that the input is a list or tuple."""
        if self.required and not value:
            raise ValidationError(self.error_messages["required"], code="required")
        # Validate that each value in the value list is in self.choices.
        for val in value:
            if not self.valid_value(val):
                raise ValidationError(
                    self.error_messages["invalid_choice"],
                    code="invalid_choice",
                    params={"value": val},
                )

    def has_changed(self, initial, data):
        if self.disabled:
            return False
        if initial is None:
            initial = []
        if data is None:
            data = []
        if len(initial) != len(data):
            return True
        initial_set = {str(value) for value in initial}
        data_set = {str(value) for value in data}
        return data_set != initial_set

    def value_from_form_data(self, data, files, html_name):
        return data.getlist(html_name)


class SlugField(CharField):
    default_validators = [validators.validate_slug]

    def __init__(self, *, allow_unicode=False, **kwargs):
        self.allow_unicode = allow_unicode
        if self.allow_unicode:
            self.default_validators = [validators.validate_unicode_slug]
        super().__init__(**kwargs)


class UUIDField(CharField):
    default_error_messages = {
        "invalid": "Enter a valid UUID.",
    }

    def prepare_value(self, value):
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return None
        if not isinstance(value, uuid.UUID):
            try:
                value = uuid.UUID(value)
            except ValueError:
                raise ValidationError(self.error_messages["invalid"], code="invalid")
        return value


class InvalidJSONInput(str):
    pass


class JSONString(str):
    pass


class JSONField(CharField):
    default_error_messages = {
        "invalid": "Enter a valid JSON.",
    }

    def __init__(
        self, encoder=None, decoder=None, indent=None, sort_keys=False, **kwargs
    ):
        self.encoder = encoder
        self.decoder = decoder
        self.indent = indent
        self.sort_keys = sort_keys
        super().__init__(**kwargs)

    def to_python(self, value):
        if self.disabled:
            return value
        if value in self.empty_values:
            return None
        elif isinstance(value, list | dict | int | float | JSONString):
            return value
        try:
            converted = json.loads(value, cls=self.decoder)
        except json.JSONDecodeError:
            raise ValidationError(
                self.error_messages["invalid"],
                code="invalid",
                params={"value": value},
            )
        if isinstance(converted, str):
            return JSONString(converted)
        else:
            return converted

    def bound_data(self, data, initial):
        if self.disabled:
            return initial
        if data is None:
            return None
        try:
            return json.loads(data, cls=self.decoder)
        except json.JSONDecodeError:
            return InvalidJSONInput(data)

    def prepare_value(self, value):
        if isinstance(value, InvalidJSONInput):
            return value
        return json.dumps(
            value,
            indent=self.indent,
            sort_keys=self.sort_keys,
            ensure_ascii=False,
            cls=self.encoder,
        )

    def has_changed(self, initial, data):
        if super().has_changed(initial, data):
            return True
        # For purposes of seeing whether something has changed, True isn't the
        # same as 1 and the order of keys doesn't matter.
        return json.dumps(initial, sort_keys=True, cls=self.encoder) != json.dumps(
            self.to_python(data), sort_keys=True, cls=self.encoder
        )


def from_current_timezone(value):
    """
    When time zone support is enabled, convert naive datetimes
    entered in the current time zone to aware datetimes.
    """
    if value is not None and timezone.is_naive(value):
        current_timezone = timezone.get_current_timezone()
        try:
            if timezone._datetime_ambiguous_or_imaginary(value, current_timezone):
                raise ValueError("Ambiguous or non-existent time.")
            return timezone.make_aware(value, current_timezone)
        except Exception as exc:
            raise ValidationError(
                (
                    "%(datetime)s couldn’t be interpreted "
                    "in time zone %(current_timezone)s; it "
                    "may be ambiguous or it may not exist."
                ),
                code="ambiguous_timezone",
                params={"datetime": value, "current_timezone": current_timezone},
            ) from exc
    return value


def to_current_timezone(value):
    """
    When time zone support is enabled, convert aware datetimes
    to naive datetimes in the current time zone for display.
    """
    if value is not None and timezone.is_aware(value):
        return timezone.make_naive(value)
    return value
