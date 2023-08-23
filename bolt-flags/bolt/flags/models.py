import re
import uuid

from bolt.checks import Info
from bolt.exceptions import ValidationError
from bolt.db import models, ProgrammingError

from .bridge import get_flag_class
from .exceptions import FlagImportError
from .settings import FLAGS_MODULE


def validate_flag_name(value):
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", value):
        raise ValidationError(f"{value} is not a valid Python identifier name")


class FlagResult(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    flag = models.ForeignKey("Flag", on_delete=models.CASCADE)
    key = models.CharField(max_length=255)
    value = models.JSONField()

    class Meta:
        unique_together = ("flag", "key")

    def __str__(self):
        return self.key


class Flag(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    name = models.CharField(
        max_length=255, unique=True, validators=[validate_flag_name]
    )

    # Optional description that can be filled in after the flag is used/created
    description = models.TextField(blank=True)

    # To manually disable a flag before completing deleting
    # (good to disable first to make sure the code doesn't use the flag anymore)
    enabled = models.BooleanField(default=True)

    # To provide an easier way to see if a flag is still being used
    used_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return self.name

    @classmethod
    def check(cls, **kwargs):
        """
        Check for flags that are in the database, but no longer defined in code.

        Only returns Info errors because it is valid to leave them if you're worried about
        putting the flag back, but they should probably be deleted eventually.
        """
        errors = super().check(**kwargs)

        databases = kwargs["databases"]
        if not databases:
            return errors

        for database in databases:
            flag_names = (
                cls.objects.using(database).all().values_list("name", flat=True)
            )

            try:
                flag_names = set(flag_names)
            except ProgrammingError:
                # The table doesn't exist yet
                # (migrations probably haven't run yet),
                # so we can't check it.
                continue

            for flag_name in flag_names:
                try:
                    get_flag_class(flag_name)
                except FlagImportError:
                    errors.append(
                        Info(
                            f"Flag {flag_name} is not used.",
                            hint=f"Remove the flag from the database or define it in the {FLAGS_MODULE()} module.",
                            id="bolt.flags.I001",
                        )
                    )

        return errors
