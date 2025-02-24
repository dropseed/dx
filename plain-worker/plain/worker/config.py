from plain.packages import PackageConfig, register_config

MODULE_NAME = "jobs"


@register_config
class PlainJobsConfig(PackageConfig):
    label = "plainworker"
