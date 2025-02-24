import datetime
import inspect
import logging
from importlib import import_module

from plain.models import IntegrityError, Model
from plain.utils import timezone

logger = logging.getLogger(__name__)


def load_job(job_class_path, parameters):
    module_path, class_name = job_class_path.rsplit(".", 1)
    module = import_module(module_path)
    job_class = getattr(module, class_name)
    args, kwargs = JobParameters.from_json(parameters)
    return job_class(*args, **kwargs)


class JobParameters:
    @staticmethod
    def to_json(args, kwargs):
        serialized_args = []
        for arg in args:
            if isinstance(arg, Model):
                serialized_args.append(ModelInstanceParameter.from_instance(arg))
            else:
                serialized_args.append(arg)

        serialized_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, Model):
                serialized_kwargs[key] = ModelInstanceParameter.from_instance(value)
            else:
                serialized_kwargs[key] = value

        return {"args": serialized_args, "kwargs": serialized_kwargs}

    @staticmethod
    def from_json(data):
        args = []
        for arg in data["args"]:
            if ModelInstanceParameter.is_gid(arg):
                args.append(ModelInstanceParameter.to_instance(arg))
            else:
                args.append(arg)

        kwargs = {}
        for key, value in data["kwargs"].items():
            if ModelInstanceParameter.is_gid(value):
                kwargs[key] = ModelInstanceParameter.to_instance(value)
            else:
                kwargs[key] = value

        return args, kwargs


class ModelInstanceParameter:
    """
    A string representation of a model instance,
    so we can convert a single parameter (model instance itself)
    into a string that can be serialized and stored in the database.
    """

    @staticmethod
    def from_instance(instance):
        return f"gid://{instance._meta.package_label}/{instance._meta.model_name}/{instance.pk}"

    @staticmethod
    def to_instance(s):
        if not s.startswith("gid://"):
            raise ValueError("Invalid ModelInstanceParameter string")
        package, model, pk = s[6:].split("/")
        from plain.models import models_registry

        model = models_registry.get_model(package, model)
        return model.objects.get(pk=pk)

    @staticmethod
    def is_gid(x):
        if not isinstance(x, str):
            return False
        return x.startswith("gid://")


class JobType(type):
    """
    Metaclass allows us to capture the original args/kwargs
    used to instantiate the job, so we can store them in the database
    when we schedule the job.
    """

    def __call__(self, *args, **kwargs):
        instance = super().__call__(*args, **kwargs)
        instance._init_args = args
        instance._init_kwargs = kwargs
        return instance


class Job(metaclass=JobType):
    def run(self):
        raise NotImplementedError

    def run_in_worker(
        self,
        *,
        queue: str | None = None,
        delay: int | datetime.timedelta | datetime.datetime | None = None,
        priority: int | None = None,
        retries: int | None = None,
        retry_attempt: int = 0,
        unique_key: str | None = None,
    ):
        from .models import JobRequest

        try:
            # Try to automatically annotate the source of the job
            caller = inspect.stack()[1]
            source = f"{caller.filename}:{caller.lineno}"
        except (IndexError, AttributeError):
            source = ""

        parameters = JobParameters.to_json(self._init_args, self._init_kwargs)

        if queue is None:
            queue = self.get_queue()

        if priority is None:
            priority = self.get_priority()

        if retries is None:
            retries = self.get_retries()

        if delay is None:
            start_at = None
        elif isinstance(delay, int):
            start_at = timezone.now() + datetime.timedelta(seconds=delay)
        elif isinstance(delay, datetime.timedelta):
            start_at = timezone.now() + delay
        elif isinstance(delay, datetime.datetime):
            start_at = delay
        else:
            raise ValueError(f"Invalid delay: {delay}")

        if unique_key is None:
            unique_key = self.get_unique_key()

        if unique_key:
            # Only need to look at in progress jobs
            # if we also have a unique key.
            # Otherwise it's up to the user to use _in_progress()
            if running := self._in_progress(unique_key):
                return running

        try:
            job_request = JobRequest(
                job_class=self._job_class_str(),
                parameters=parameters,
                start_at=start_at,
                source=source,
                queue=queue,
                priority=priority,
                retries=retries,
                retry_attempt=retry_attempt,
                unique_key=unique_key,
            )
            job_request.save(
                clean_and_validate=False
            )  # So IntegrityError is raised on unique instead of potentially confusing ValidationError...
            return job_request
        except IntegrityError as e:
            logger.warning("Job already in progress: %s", e)
            # Try to return the _in_progress list again
            return self._in_progress(unique_key)

    def _job_class_str(self):
        return f"{self.__module__}.{self.__class__.__name__}"

    def _in_progress(self, unique_key):
        """Get all JobRequests and Jobs that are currently in progress, regardless of queue."""
        from .models import Job, JobRequest

        job_class = self._job_class_str()

        job_requests = JobRequest.objects.filter(
            job_class=job_class,
            unique_key=unique_key,
        )

        jobs = Job.objects.filter(
            job_class=job_class,
            unique_key=unique_key,
        )

        return list(job_requests) + list(jobs)

    def get_unique_key(self) -> str:
        """
        A unique key to prevent duplicate jobs from being queued.
        Enabled by returning a non-empty string.

        Note that this is not a "once and only once" guarantee, but rather
        an "at least once" guarantee. Jobs should still be idempotent in case
        multiple instances are queued in a race condition.
        """
        return ""

    def get_queue(self) -> str:
        return "default"

    def get_priority(self) -> int:
        return 0

    def get_retries(self) -> int:
        return 0

    def get_retry_delay(self, attempt: int) -> int:
        """
        Calcluate a delay in seconds before the next retry attempt.

        On the first retry, attempt will be 1.
        """
        return 0
