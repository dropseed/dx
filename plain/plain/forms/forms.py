"""
Form classes
"""

import copy

from plain.exceptions import NON_FIELD_ERRORS
from plain.utils.datastructures import MultiValueDict
from plain.utils.functional import cached_property

from .exceptions import ValidationError
from .fields import Field, FileField

__all__ = ("BaseForm", "Form")


class DeclarativeFieldsMetaclass(type):
    """Collect Fields declared on the base classes."""

    def __new__(mcs, name, bases, attrs):
        # Collect fields from current class and remove them from attrs.
        attrs["declared_fields"] = {
            key: attrs.pop(key)
            for key, value in list(attrs.items())
            if isinstance(value, Field)
        }

        new_class = super().__new__(mcs, name, bases, attrs)

        # Walk through the MRO.
        declared_fields = {}
        for base in reversed(new_class.__mro__):
            # Collect fields from base class.
            if hasattr(base, "declared_fields"):
                declared_fields.update(base.declared_fields)

            # Field shadowing.
            for attr, value in base.__dict__.items():
                if value is None and attr in declared_fields:
                    declared_fields.pop(attr)

        new_class.base_fields = declared_fields
        new_class.declared_fields = declared_fields

        return new_class


class BaseForm:
    """
    The main implementation of all the Form logic. Note that this class is
    different than Form. See the comments by the Form class for more info. Any
    improvements to the form API should be made to this class, not to the Form
    class.
    """

    prefix = None

    def __init__(
        self,
        data=None,
        files=None,
        auto_id="id_%s",
        prefix=None,
        initial=None,
    ):
        self.is_bound = data is not None or files is not None
        self.data = MultiValueDict() if data is None else data
        self.files = MultiValueDict() if files is None else files
        self._auto_id = auto_id
        if prefix is not None:
            self.prefix = prefix
        self.initial = initial or {}
        self._errors = None  # Stores the errors after clean() has been called.

        # The base_fields class attribute is the *class-wide* definition of
        # fields. Because a particular *instance* of the class might want to
        # alter self.fields, we create self.fields here by copying base_fields.
        # Instances should always modify self.fields; they should not modify
        # self.base_fields.
        self.fields = copy.deepcopy(self.base_fields)
        self._bound_fields_cache = {}

    def __repr__(self):
        if self._errors is None:
            is_valid = "Unknown"
        else:
            is_valid = self.is_bound and not self._errors
        return "<{cls} bound={bound}, valid={valid}, fields=({fields})>".format(
            cls=self.__class__.__name__,
            bound=self.is_bound,
            valid=is_valid,
            fields=";".join(self.fields),
        )

    def _bound_items(self):
        """Yield (name, bf) pairs, where bf is a BoundField object."""
        for name in self.fields:
            yield name, self[name]

    def __iter__(self):
        """Yield the form's fields as BoundField objects."""
        for name in self.fields:
            yield self[name]

    def __getitem__(self, name):
        """Return a BoundField with the given name."""
        try:
            field = self.fields[name]
        except KeyError:
            raise KeyError(
                "Key '{}' not found in '{}'. Choices are: {}.".format(
                    name,
                    self.__class__.__name__,
                    ", ".join(sorted(self.fields)),
                )
            )
        if name not in self._bound_fields_cache:
            self._bound_fields_cache[name] = field.get_bound_field(self, name)
        return self._bound_fields_cache[name]

    @property
    def errors(self):
        """Return an error dict for the data provided for the form."""
        if self._errors is None:
            self.full_clean()
        return self._errors

    def is_valid(self):
        """Return True if the form has no errors, or False otherwise."""
        return self.is_bound and not self.errors

    def add_prefix(self, field_name):
        """
        Return the field name with a prefix appended, if this Form has a
        prefix set.

        Subclasses may wish to override.
        """
        return f"{self.prefix}-{field_name}" if self.prefix else field_name

    @property
    def non_field_errors(self):
        """
        Return a list of errors that aren't associated with a particular
        field -- i.e., from Form.clean(). Return an empty list if there
        are none.
        """
        return self.errors.get(
            NON_FIELD_ERRORS,
            [],
        )

    def add_error(self, field, error):
        """
        Update the content of `self._errors`.

        The `field` argument is the name of the field to which the errors
        should be added. If it's None, treat the errors as NON_FIELD_ERRORS.

        The `error` argument can be a single error, a list of errors, or a
        dictionary that maps field names to lists of errors. An "error" can be
        either a simple string or an instance of ValidationError with its
        message attribute set and a "list or dictionary" can be an actual
        `list` or `dict` or an instance of ValidationError with its
        `error_list` or `error_dict` attribute set.

        If `error` is a dictionary, the `field` argument *must* be None and
        errors will be added to the fields that correspond to the keys of the
        dictionary.
        """
        if not isinstance(error, ValidationError):
            raise TypeError(
                "The argument `error` must be an instance of "
                f"`ValidationError`, not `{type(error).__name__}`."
            )

        if hasattr(error, "error_dict"):
            if field is not None:
                raise TypeError(
                    "The argument `field` must be `None` when the `error` "
                    "argument contains errors for multiple fields."
                )
            else:
                error = error.error_dict
        else:
            error = {field or NON_FIELD_ERRORS: error.error_list}

        class ValidationErrors(list):
            def __iter__(self):
                for err in super().__iter__():
                    # TODO make sure this works...
                    yield next(iter(err))

        for field, error_list in error.items():
            if field not in self.errors:
                if field != NON_FIELD_ERRORS and field not in self.fields:
                    raise ValueError(
                        f"'{self.__class__.__name__}' has no field named '{field}'."
                    )
                self._errors[field] = ValidationErrors()

            self._errors[field].extend(error_list)

            # The field had an error, so removed it from the final data
            # (we use getattr here so errors can be added to uncleaned forms)
            if field in getattr(self, "cleaned_data", {}):
                del self.cleaned_data[field]

    def full_clean(self):
        """
        Clean all of self.data and populate self._errors and self.cleaned_data.
        """
        self._errors = {}
        if not self.is_bound:  # Stop further processing.
            return
        self.cleaned_data = {}

        self._clean_fields()
        self._clean_form()
        self._post_clean()

    def _field_data_value(self, field, html_name):
        if hasattr(self, f"parse_{html_name}"):
            # Allow custom parsing from form data/files at the form level
            return getattr(self, f"parse_{html_name}")()

        return field.value_from_form_data(self.data, self.files, html_name)

    def _clean_fields(self):
        for name, bf in self._bound_items():
            field = bf.field

            if field.disabled:
                value = bf.initial
            else:
                value = self._field_data_value(bf.field, bf.html_name)

            try:
                if isinstance(field, FileField):
                    value = field.clean(value, bf.initial)
                else:
                    value = field.clean(value)
                self.cleaned_data[name] = value
                if hasattr(self, f"clean_{name}"):
                    value = getattr(self, f"clean_{name}")()
                    self.cleaned_data[name] = value
            except ValidationError as e:
                self.add_error(name, e)

    def _clean_form(self):
        try:
            cleaned_data = self.clean()
        except ValidationError as e:
            self.add_error(None, e)
        else:
            if cleaned_data is not None:
                self.cleaned_data = cleaned_data

    def _post_clean(self):
        """
        An internal hook for performing additional cleaning after form cleaning
        is complete. Used for model validation in model forms.
        """
        pass

    def clean(self):
        """
        Hook for doing any extra form-wide cleaning after Field.clean() has been
        called on every field. Any ValidationError raised by this method will
        not be associated with a particular field; it will have a special-case
        association with the field named '__all__'.
        """
        return self.cleaned_data

    @cached_property
    def changed_data(self):
        return [name for name, bf in self._bound_items() if bf._has_changed()]

    def get_initial_for_field(self, field, field_name):
        """
        Return initial data for field on form. Use initial data from the form
        or the field, in that order. Evaluate callable values.
        """
        value = self.initial.get(field_name, field.initial)
        if callable(value):
            value = value()
        return value


class Form(BaseForm, metaclass=DeclarativeFieldsMetaclass):
    "A collection of Fields, plus their associated data."

    # This is a separate class from BaseForm in order to abstract the way
    # self.fields is specified. This class (Form) is the one that does the
    # fancy metaclass stuff purely for the semantic sugar -- it allows one
    # to define a form using declarative syntax.
    # BaseForm itself has no way of designating self.fields.
