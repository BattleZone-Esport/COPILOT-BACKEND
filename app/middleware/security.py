"""
Security middleware for rate limiting, request validation, and security headers.
"""

import hashlib
import hmac
import logging
import time
from typing import Dict, Optional, Tuple
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.datastructures import Headers, MutableHeaders

from app.core.config import get_settings
from app.exceptions.custom_exceptions import (
    RateLimitException,
    ValidationException,
    raise_rate_limit_error
)

_logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token bucket algorithm implementation for rate limiting.
    """
    
    def __init__(
        self,
        rate: int = 100,  # requests per period
        period: int = 60,  # period in seconds
        burst: int = 10    # burst allowance
    ):
        self.rate = rate
        self.period = period
        self.burst = burst
        self.buckets: Dict[str, Tuple[float, float]] = defaultdict(
            lambda: (float(rate), time.time())
        )
        self._cleanup_interval = 300  # Clean up old buckets every 5 minutes
        self._last_cleanup = time.time()
    
    def is_allowed(self, key: str) -> Tuple[bool, Optional[int]]:
        """
        Check if request is allowed for the given key.
        Returns (allowed, retry_after_seconds).
        """
        current_time = time.time()
        
        # Periodic cleanup
        if current_time - self._last_cleanup > self._cleanup_interval:
            self._cleanup_old_buckets(current_time)
        
        tokens, last_update = self.buckets[key]
        
        # Calculate tokens to add based on elapsed time
        elapsed = current_time - last_update
        tokens_to_add = elapsed * (self.rate / self.period)
        tokens = min(self.rate + self.burst, tokens + tokens_to_add)
        
        if tokens >= 1:
            # Request allowed, consume a token
            self.buckets[key] = (tokens - 1, current_time)
            return True, None
        else:
            # Request denied, calculate retry time
            retry_after = int((1 - tokens) * (self.period / self.rate))
            return False, retry_after
    
    def _cleanup_old_buckets(self, current_time: float) -> None:
        """
        Remove old bucket entries to prevent memory leaks.
        """
        cutoff_time = current_time - (self.period * 2)
        keys_to_remove = [
            key for key, (_, last_update) in self.buckets.items()
            if last_update < cutoff_time
        ]
        for key in keys_to_remove:
            del self.buckets[key]
        
        if keys_to_remove:
            _logger.info("Cleaned up %d old rate limit buckets", len(keys_to_remove))
        
        self._last_cleanup = current_time


class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive security middleware for the application.
    """
    
    def __init__(self, app, **kwargs):
        super().__init__(app)
        settings = get_settings()
        
        # Initialize rate limiters for different endpoints
        self.rate_limiters = {
            "default": RateLimiter(rate=100, period=60, burst=10),
            "auth": RateLimiter(rate=10, period=60, burst=2),
            "jobs": RateLimiter(rate=50, period=60, burst=5),
            "terminal": RateLimiter(rate=20, period=60, burst=3),
        }
        
        # Request size limits
        self.max_request_size = 10 * 1024 * 1024  # 10 MB
        self.max_json_size = 1 * 1024 * 1024      # 1 MB
        
        # Security headers configuration
        self.security_headers = self._get_security_headers(settings)
    
    def _get_security_headers(self, settings) -> Dict[str, str]:
        """
        Get security headers based on environment.
        """
        headers = {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Referrer-Policy": "strict-origin-when-cross-origin",
            "Permissions-Policy": "geolocation=(), microphone=(), camera=()"
        }
        
        if settings.ENVIRONMENT == "production":
            # Strict CSP for production
            headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https:; "
                "font-src 'self' data: https://cdn.jsdelivr.net; "
                "connect-src 'self'; "
                "frame-ancestors 'none';"
            )
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        return headers
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request with security checks.
        """
        # Check request size
        if not await self._check_request_size(request):
            return JSONResponse(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                content={
                    "error": {
                        "code": "REQUEST_TOO_LARGE",
                        "message": "Request size exceeds maximum allowed size"
                    }
                }
            )
        
        # Apply rate limiting
        rate_limit_result = await self._apply_rate_limiting(request)
        if rate_limit_result:
            return rate_limit_result
        
        # Validate request headers
        if not self._validate_request_headers(request):
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "error": {
                        "code": "INVALID_REQUEST",
                        "message": "Invalid request headers"
                    }
                }
            )
        
        # Process request
        response = await call_next(request)
        
        # Add security headers
        for header, value in self.security_headers.items():
            response.headers[header] = value
        
        # Add request ID header
        if hasattr(request.state, "request_id"):
            response.headers["X-Request-ID"] = request.state.request_id
        
        return response
    
    async def _check_request_size(self, request: Request) -> bool:
        """
        Check if request size is within limits.
        """
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
                if size > self.max_request_size:
                    _logger.warning(
                        "Request size %d exceeds limit %d",
                        size,
                        self.max_request_size
                    )
                    return False
            except ValueError:
                return False
        return True
    
    async def _apply_rate_limiting(self, request: Request) -> Optional[JSONResponse]:
        """
        Apply rate limiting based on endpoint and user.
        """
        # Determine rate limiter to use
        path = request.url.path
        if path.startswith("/api/v1/auth"):
            limiter = self.rate_limiters["auth"]
        elif path.startswith("/api/v1/jobs"):
            limiter = self.rate_limiters["jobs"]
        elif path.startswith("/api/v1/terminal"):
            limiter = self.rate_limiters["terminal"]
        else:
            limiter = self.rate_limiters["default"]
        
        # Create rate limit key
        # Use user ID if authenticated, otherwise use IP address
        if hasattr(request.state, "user") and request.state.user:
            key = f"user:{request.state.user.get('id', 'unknown')}"
        else:
            # Get client IP (considering proxy headers)
            client_ip = request.client.host
            if "X-Forwarded-For" in request.headers:
                client_ip = request.headers["X-Forwarded-For"].split(",")[0].strip()
            elif "X-Real-IP" in request.headers:
                client_ip = request.headers["X-Real-IP"]
            key = f"ip:{client_ip}"
        
        # Check rate limit
        allowed, retry_after = limiter.is_allowed(key)
        
        if not allowed:
            _logger.warning(
                "Rate limit exceeded for %s on %s",
                key,
                path
            )
            
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests. Please try again later.",
                        "details": {
                            "retry_after": retry_after
                        }
                    }
                }
            )
            
            if retry_after:
                response.headers["Retry-After"] = str(retry_after)
                response.headers["X-RateLimit-Limit"] = str(limiter.rate)
                response.headers["X-RateLimit-Remaining"] = "0"
                response.headers["X-RateLimit-Reset"] = str(
                    int(time.time()) + retry_after
                )
            
            return response
        
        return None
    
    def _validate_request_headers(self, request: Request) -> bool:
        """
        Validate request headers for security issues.
        """
        # Check for suspicious headers
        suspicious_headers = [
            "X-Forwarded-Host",
            "X-Original-URL",
            "X-Rewrite-URL"
        ]
        
        for header in suspicious_headers:
            if header in request.headers:
                value = request.headers[header]
                # Check for potential header injection
                if "\n" in value or "\r" in value:
                    _logger.warning(
                        "Potential header injection detected in %s",
                        header
                    )
                    return False
        
        # Validate content type for POST/PUT/PATCH requests
        if request.method in ["POST", "PUT", "PATCH"]:
            content_type = request.headers.get("content-type", "")
            if not content_type:
                return True  # Allow empty content type
            
            # Check for valid content types
            valid_content_types = [
                "application/json",
                "application/x-www-form-urlencoded",
                "multipart/form-data"
            ]
            
            if not any(ct in content_type for ct in valid_content_types):
                _logger.warning(
                    "Invalid content type: %s",
                    content_type
                )
                return False
        
        return True


class CSRFMiddleware:
    """
    CSRF protection middleware.
    """
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    def generate_token(self, session_id: str) -> str:
        """
        Generate CSRF token for session.
        """
        timestamp = str(int(time.time()))
        message = f"{session_id}:{timestamp}"
        signature = hmac.new(
            self.secret_key.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"{timestamp}:{signature}"
    
    def validate_token(self, token: str, session_id: str, max_age: int = 3600) -> bool:
        """
        Validate CSRF token.
        """
        try:
            timestamp_str, signature = token.split(":", 1)
            timestamp = int(timestamp_str)
            
            # Check token age
            if time.time() - timestamp > max_age:
                return False
            
            # Verify signature
            message = f"{session_id}:{timestamp_str}"
            expected_signature = hmac.new(
                self.secret_key.encode(),
                message.encode(),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, expected_signature)
            
        except (ValueError, AttributeError):
            return False