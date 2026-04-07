"""Domain-specific errors surfaced by the CLI."""


class NetBoxCLIError(Exception):
    """Base class for expected CLI failures."""


class ConfigError(NetBoxCLIError):
    """Base class for configuration issues."""


class ConfigFileNotFoundError(ConfigError):
    """Raised when no explicit config file is available."""


class ConfigPermissionError(ConfigError):
    """Raised when config file permissions are too open."""


class ConfigValidationError(ConfigError):
    """Raised when config values are malformed or incomplete."""


class NetBoxAuthError(NetBoxCLIError):
    """Raised when NetBox rejects the configured token."""


class NetBoxConnectionError(NetBoxCLIError):
    """Raised when the CLI cannot connect to NetBox."""


class APIError(NetBoxCLIError):
    """Raised when NetBox returns an unexpected API response."""


class InvalidEndpointError(NetBoxCLIError):
    """Raised when an app or endpoint path is invalid."""


class InvalidFilterError(NetBoxCLIError):
    """Raised when a query filter is invalid for the target endpoint."""


class NoResultsError(NetBoxCLIError):
    """Raised when a query returns no rows."""


class MultipleResultsError(NetBoxCLIError):
    """Raised when a supposedly singular lookup matches multiple rows."""


class CommandUsageError(NetBoxCLIError):
    """Raised when a shell command is malformed or used in the wrong context."""


class FeatureNotReadyError(NetBoxCLIError):
    """Raised for commands intentionally staged for later phases."""
