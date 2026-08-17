"""Structured failures raised by the ROS runtime protocol layer."""


class RuntimeProtocolError(RuntimeError):
    """Base class for failures with stable machine-readable codes."""

    code = "runtime_protocol_error"


class InvalidProtocolValueError(RuntimeProtocolError, ValueError):
    """A caller supplied a value that cannot satisfy the wire contract."""

    code = "invalid_protocol_value"


class ResetRequestConflictError(RuntimeProtocolError):
    """A request ID was reused for a different reset request."""

    code = "reset_request_conflict"


class ServiceDiscoveryTimeoutError(RuntimeProtocolError, TimeoutError):
    """A service did not become discoverable before its deadline."""

    code = "service_discovery_timeout"


class ServiceCallTimeoutError(RuntimeProtocolError, TimeoutError):
    """A discovered service did not complete before its call deadline."""

    code = "service_call_timeout"


class ServiceCallError(RuntimeProtocolError):
    """A service future completed with an exception or without a result."""

    code = "service_call_error"


class ConversionError(RuntimeProtocolError, ValueError):
    """A domain object or ROS message cannot be converted safely."""

    code = "conversion_error"
