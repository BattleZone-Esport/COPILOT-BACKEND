"""
Custom exception classes for comprehensive error handling.
"""

from typing import Any, Dict, Optional
from fastapi import HTTPException, status


class BaseAppException(Exception):
    """Base exception class for application-specific exceptions."""
    
    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details
        }


class DatabaseException(BaseAppException):
    """Exception for database-related errors."""
    pass


class ConnectionException(DatabaseException):
    """Exception for database connection issues."""
    pass


class QueryException(DatabaseException):
    """Exception for database query errors."""
    pass


class ValidationException(BaseAppException):
    """Exception for input validation errors."""
    pass


class AuthenticationException(BaseAppException):
    """Exception for authentication failures."""
    pass


class AuthorizationException(BaseAppException):
    """Exception for authorization failures."""
    pass


class RateLimitException(BaseAppException):
    """Exception for rate limit violations."""
    pass


class QueueException(BaseAppException):
    """Exception for queue-related errors."""
    pass


class JobException(BaseAppException):
    """Exception for job processing errors."""
    pass


class JobNotFoundException(JobException):
    """Exception when a job is not found."""
    pass


class JobLockedException(JobException):
    """Exception when a job is locked for processing."""
    pass


class JobTimeoutException(JobException):
    """Exception when a job times out."""
    pass


class TerminalException(BaseAppException):
    """Exception for terminal command errors."""
    pass


class CommandNotAllowedException(TerminalException):
    """Exception when a terminal command is not allowed."""
    pass


class CommandTimeoutException(TerminalException):
    """Exception when a terminal command times out."""
    pass


class AIServiceException(BaseAppException):
    """Exception for AI service errors."""
    pass


class ModelException(AIServiceException):
    """Exception for AI model errors."""
    pass


class ExternalServiceException(BaseAppException):
    """Exception for external service integration errors."""
    pass


class WebhookException(BaseAppException):
    """Exception for webhook-related errors."""
    pass


class ConfigurationException(BaseAppException):
    """Exception for configuration errors."""
    pass


class ResourceException(BaseAppException):
    """Exception for resource-related errors."""
    pass


class ResourceNotFoundException(ResourceException):
    """Exception when a resource is not found."""
    pass


class ResourceLimitException(ResourceException):
    """Exception when resource limits are exceeded."""
    pass


# HTTP Exception helpers
def raise_validation_error(
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise a validation error as HTTP 422."""
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "error": "VALIDATION_ERROR",
            "message": message,
            "details": details or {}
        }
    )


def raise_authentication_error(
    message: str = "Authentication required",
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise an authentication error as HTTP 401."""
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "error": "AUTHENTICATION_ERROR",
            "message": message,
            "details": details or {}
        },
        headers={"WWW-Authenticate": "Bearer"}
    )


def raise_authorization_error(
    message: str = "Insufficient permissions",
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise an authorization error as HTTP 403."""
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "error": "AUTHORIZATION_ERROR",
            "message": message,
            "details": details or {}
        }
    )


def raise_not_found_error(
    resource: str,
    identifier: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise a not found error as HTTP 404."""
    message = f"{resource} not found"
    if identifier:
        message = f"{resource} with id '{identifier}' not found"
    
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "error": "NOT_FOUND",
            "message": message,
            "details": details or {}
        }
    )


def raise_rate_limit_error(
    message: str = "Rate limit exceeded",
    retry_after: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise a rate limit error as HTTP 429."""
    headers = {}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "error": "RATE_LIMIT_EXCEEDED",
            "message": message,
            "details": details or {}
        },
        headers=headers
    )


def raise_conflict_error(
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise a conflict error as HTTP 409."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "error": "CONFLICT",
            "message": message,
            "details": details or {}
        }
    )


def raise_bad_request_error(
    message: str,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise a bad request error as HTTP 400."""
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error": "BAD_REQUEST",
            "message": message,
            "details": details or {}
        }
    )


def raise_internal_error(
    message: str = "An internal server error occurred",
    error_code: str = "INTERNAL_ERROR",
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise an internal server error as HTTP 500."""
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail={
            "error": error_code,
            "message": message,
            "details": details or {}
        }
    )


def raise_service_unavailable_error(
    message: str = "Service temporarily unavailable",
    retry_after: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None
) -> None:
    """Raise a service unavailable error as HTTP 503."""
    headers = {}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "error": "SERVICE_UNAVAILABLE",
            "message": message,
            "details": details or {}
        },
        headers=headers
    )