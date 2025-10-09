"""
Error handling middleware for comprehensive exception management.
"""

import logging
import sys
import traceback
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions.custom_exceptions import (
    BaseAppException,
    DatabaseException,
    ValidationException,
    AuthenticationException,
    AuthorizationException,
    RateLimitException,
    QueueException,
    JobException,
    TerminalException,
    AIServiceException,
    ExternalServiceException,
    ConfigurationException,
    ResourceException
)

_logger = logging.getLogger(__name__)


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for handling all application exceptions and converting them
    to appropriate HTTP responses.
    """
    
    async def dispatch(self, request: Request, call_next):
        """
        Process the request and handle any exceptions that occur.
        """
        # Generate error ID for tracking
        error_id = str(uuid4())
        
        try:
            response = await call_next(request)
            return response
            
        except BaseAppException as e:
            # Handle custom application exceptions
            return await self._handle_app_exception(e, error_id, request)
            
        except StarletteHTTPException as e:
            # Handle standard HTTP exceptions
            return await self._handle_http_exception(e, error_id, request)
            
        except Exception as e:
            # Handle unexpected exceptions
            return await self._handle_unexpected_exception(e, error_id, request)
    
    async def _handle_app_exception(
        self,
        exc: BaseAppException,
        error_id: str,
        request: Request
    ) -> JSONResponse:
        """
        Handle custom application exceptions.
        """
        # Map exception types to HTTP status codes
        status_map = {
            ValidationException: status.HTTP_422_UNPROCESSABLE_ENTITY,
            AuthenticationException: status.HTTP_401_UNAUTHORIZED,
            AuthorizationException: status.HTTP_403_FORBIDDEN,
            RateLimitException: status.HTTP_429_TOO_MANY_REQUESTS,
            DatabaseException: status.HTTP_503_SERVICE_UNAVAILABLE,
            QueueException: status.HTTP_503_SERVICE_UNAVAILABLE,
            JobException: status.HTTP_400_BAD_REQUEST,
            TerminalException: status.HTTP_400_BAD_REQUEST,
            AIServiceException: status.HTTP_502_BAD_GATEWAY,
            ExternalServiceException: status.HTTP_502_BAD_GATEWAY,
            ConfigurationException: status.HTTP_500_INTERNAL_SERVER_ERROR,
            ResourceException: status.HTTP_404_NOT_FOUND
        }
        
        # Get appropriate status code
        status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        for exc_type, code in status_map.items():
            if isinstance(exc, exc_type):
                status_code = code
                break
        
        # Log the exception
        self._log_exception(exc, error_id, request, status_code)
        
        # Build response
        response_data = {
            "error": {
                "id": error_id,
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details
            }
        }
        
        # Add retry information for rate limit errors
        if isinstance(exc, RateLimitException) and "retry_after" in exc.details:
            headers = {"Retry-After": str(exc.details["retry_after"])}
        else:
            headers = {}
        
        return JSONResponse(
            status_code=status_code,
            content=response_data,
            headers=headers
        )
    
    async def _handle_http_exception(
        self,
        exc: StarletteHTTPException,
        error_id: str,
        request: Request
    ) -> JSONResponse:
        """
        Handle standard HTTP exceptions.
        """
        # Log the exception
        self._log_exception(exc, error_id, request, exc.status_code)
        
        # Build response
        response_data = {
            "error": {
                "id": error_id,
                "code": f"HTTP_{exc.status_code}",
                "message": exc.detail if isinstance(exc.detail, str) else "HTTP Error",
                "details": exc.detail if isinstance(exc.detail, dict) else {}
            }
        }
        
        return JSONResponse(
            status_code=exc.status_code,
            content=response_data,
            headers=exc.headers if hasattr(exc, "headers") else {}
        )
    
    async def _handle_unexpected_exception(
        self,
        exc: Exception,
        error_id: str,
        request: Request
    ) -> JSONResponse:
        """
        Handle unexpected exceptions.
        """
        # Log the full exception with traceback
        _logger.critical(
            "Unexpected exception occurred",
            extra={
                "error_id": error_id,
                "method": request.method,
                "path": request.url.path,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "traceback": traceback.format_exc()
            }
        )
        
        # In production, don't expose internal details
        if request.app.state.settings.ENVIRONMENT == "production":
            message = "An internal server error occurred"
            details = {}
        else:
            message = f"Unexpected error: {str(exc)}"
            details = {
                "type": type(exc).__name__,
                "traceback": traceback.format_exc().split('\n')
            }
        
        response_data = {
            "error": {
                "id": error_id,
                "code": "INTERNAL_SERVER_ERROR",
                "message": message,
                "details": details
            }
        }
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=response_data
        )
    
    def _log_exception(
        self,
        exc: Exception,
        error_id: str,
        request: Request,
        status_code: int
    ) -> None:
        """
        Log exception with appropriate level based on status code.
        """
        log_data = {
            "error_id": error_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "exception_type": type(exc).__name__,
            "exception": str(exc)
        }
        
        # Add query params if present
        if request.url.query:
            log_data["query"] = request.url.query
        
        # Add user info if available
        if hasattr(request.state, "user"):
            log_data["user_id"] = getattr(request.state.user, "id", "unknown")
        
        # Choose log level based on status code
        if status_code >= 500:
            _logger.error("Server error occurred", extra=log_data)
        elif status_code >= 400:
            _logger.warning("Client error occurred", extra=log_data)
        else:
            _logger.info("Exception handled", extra=log_data)


class ValidationErrorHandler:
    """
    Handler for validation errors with detailed field information.
    """
    
    @staticmethod
    def format_validation_errors(errors: list) -> Dict[str, Any]:
        """
        Format Pydantic validation errors into a consistent structure.
        """
        formatted_errors = {}
        
        for error in errors:
            # Get field path
            field = ".".join(str(loc) for loc in error.get("loc", []))
            
            # Add error to field
            if field not in formatted_errors:
                formatted_errors[field] = []
            
            formatted_errors[field].append({
                "type": error.get("type", "unknown"),
                "message": error.get("msg", "Validation error"),
                "context": error.get("ctx", {})
            })
        
        return formatted_errors


def create_error_response(
    status_code: int,
    error_code: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
    error_id: Optional[str] = None
) -> JSONResponse:
    """
    Create a standardized error response.
    """
    if error_id is None:
        error_id = str(uuid4())
    
    response_data = {
        "error": {
            "id": error_id,
            "code": error_code,
            "message": message,
            "details": details or {}
        }
    }
    
    return JSONResponse(
        status_code=status_code,
        content=response_data
    )