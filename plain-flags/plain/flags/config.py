from plain.packages import PackageConfig, register_config


@register_config
class Config(PackageConfig):
    label = "plainflags"  # Primarily for migrations
