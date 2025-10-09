"""
Monitoring middleware for logging, metrics collection, and performance tracking.
"""

import logging
import time
import json
import asyncio
from typing import Any, Dict, Optional
from uuid import uuid4
from datetime import datetime, timezone

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from prometheus_client import Counter, Histogram, Gauge
import psutil

from app.core.config import get_settings

_logger = logging.getLogger(__name__)

# Prometheus metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint']
)

active_requests = Gauge(
    'active_requests',
    'Number of active requests'
)

error_counter = Counter(
    'application_errors_total',
    'Total application errors',
    ['error_type', 'endpoint']
)

db_operations = Counter(
    'database_operations_total',
    'Total database operations',
    ['operation', 'collection']
)

db_operation_duration = Histogram(
    'database_operation_duration_seconds',
    'Database operation duration in seconds',
    ['operation', 'collection']
)

queue_operations = Counter(
    'queue_operations_total',
    'Total queue operations',
    ['operation', 'queue_type']
)

ai_requests = Counter(
    'ai_requests_total',
    'Total AI model requests',
    ['model', 'agent_type']
)

ai_request_duration = Histogram(
    'ai_request_duration_seconds',
    'AI request duration in seconds',
    ['model', 'agent_type']
)

terminal_commands = Counter(
    'terminal_commands_total',
    'Total terminal commands executed',
    ['command_type', 'status']
)


class MonitoringMiddleware(BaseHTTPMiddleware):
    """
    Middleware for request monitoring, logging, and metrics collection.
    """
    
    def __init__(self, app, **kwargs):
        super().__init__(app)
        self.settings = get_settings()
        self.system_monitor = SystemMonitor()
    
    async def dispatch(self, request: Request, call_next):
        """
        Process request with monitoring.
        """
        # Generate request ID
        request_id = str(uuid4())
        request.state.request_id = request_id
        
        # Start timing
        start_time = time.time()
        
        # Track active requests
        active_requests.inc()
        
        # Log request
        await self._log_request(request, request_id)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate duration
            duration = time.time() - start_time
            
            # Log response
            await self._log_response(request, response, duration, request_id)
            
            # Update metrics
            self._update_metrics(request, response.status_code, duration)
            
            # Add monitoring headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration:.3f}"
            
            return response
            
        except Exception as e:
            # Calculate duration
            duration = time.time() - start_time
            
            # Log error
            await self._log_error(request, e, duration, request_id)
            
            # Update error metrics
            error_counter.labels(
                error_type=type(e).__name__,
                endpoint=request.url.path
            ).inc()
            
            # Re-raise exception
            raise
            
        finally:
            # Track active requests
            active_requests.dec()
    
    async def _log_request(self, request: Request, request_id: str) -> None:
        """
        Log incoming request.
        """
        log_data = {
            "event": "request_received",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "headers": dict(request.headers),
            "client_ip": self._get_client_ip(request),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Add user info if available
        if hasattr(request.state, "user") and request.state.user:
            log_data["user_id"] = request.state.user.get("id", "unknown")
            log_data["user_email"] = request.state.user.get("email", "unknown")
        
        # Don't log sensitive headers
        sensitive_headers = ["authorization", "cookie", "x-csrf-token"]
        for header in sensitive_headers:
            if header in log_data["headers"]:
                log_data["headers"][header] = "***REDACTED***"
        
        _logger.info(
            "Request received",
            extra=log_data
        )
    
    async def _log_response(
        self,
        request: Request,
        response,
        duration: float,
        request_id: str
    ) -> None:
        """
        Log response.
        """
        log_data = {
            "event": "request_completed",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_seconds": duration,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Add user info if available
        if hasattr(request.state, "user") and request.state.user:
            log_data["user_id"] = request.state.user.get("id", "unknown")
        
        # Choose log level based on status code
        if response.status_code >= 500:
            _logger.error("Request failed with server error", extra=log_data)
        elif response.status_code >= 400:
            _logger.warning("Request failed with client error", extra=log_data)
        else:
            _logger.info("Request completed successfully", extra=log_data)
    
    async def _log_error(
        self,
        request: Request,
        error: Exception,
        duration: float,
        request_id: str
    ) -> None:
        """
        Log request error.
        """
        log_data = {
            "event": "request_error",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "duration_seconds": duration,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Add user info if available
        if hasattr(request.state, "user") and request.state.user:
            log_data["user_id"] = request.state.user.get("id", "unknown")
        
        _logger.exception(
            "Request failed with exception",
            extra=log_data
        )
    
    def _update_metrics(
        self,
        request: Request,
        status_code: int,
        duration: float
    ) -> None:
        """
        Update Prometheus metrics.
        """
        # Normalize endpoint for metrics (remove IDs)
        endpoint = self._normalize_endpoint(request.url.path)
        
        # Update request counter
        http_requests_total.labels(
            method=request.method,
            endpoint=endpoint,
            status=status_code
        ).inc()
        
        # Update request duration
        http_request_duration.labels(
            method=request.method,
            endpoint=endpoint
        ).observe(duration)
    
    def _normalize_endpoint(self, path: str) -> str:
        """
        Normalize endpoint path for metrics (replace IDs with placeholders).
        """
        # Common patterns to replace
        import re
        
        # UUID pattern
        path = re.sub(
            r'/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}',
            '/{id}',
            path
        )
        
        # Numeric ID pattern
        path = re.sub(r'/\d+', '/{id}', path)
        
        # MongoDB ObjectId pattern
        path = re.sub(r'/[a-f0-9]{24}', '/{id}', path)
        
        return path
    
    def _get_client_ip(self, request: Request) -> str:
        """
        Get client IP address considering proxy headers.
        """
        # Check proxy headers
        if "X-Forwarded-For" in request.headers:
            return request.headers["X-Forwarded-For"].split(",")[0].strip()
        elif "X-Real-IP" in request.headers:
            return request.headers["X-Real-IP"]
        
        # Fall back to direct client IP
        if request.client:
            return request.client.host
        
        return "unknown"


class SystemMonitor:
    """
    Monitor system resources and health.
    """
    
    def __init__(self):
        self.cpu_usage = Gauge('system_cpu_usage_percent', 'System CPU usage percentage')
        self.memory_usage = Gauge('system_memory_usage_percent', 'System memory usage percentage')
        self.disk_usage = Gauge('system_disk_usage_percent', 'System disk usage percentage')
        self.open_connections = Gauge('system_open_connections', 'Number of open network connections')
        
        # Start monitoring in background
        self._start_monitoring()
    
    def _start_monitoring(self):
        """
        Start background monitoring task.
        """
        import asyncio
        import threading
        
        def monitor_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._monitor())
        
        thread = threading.Thread(target=monitor_loop, daemon=True)
        thread.start()
    
    async def _monitor(self):
        """
        Continuously monitor system resources.
        """
        while True:
            try:
                # CPU usage
                cpu_percent = psutil.cpu_percent(interval=1)
                self.cpu_usage.set(cpu_percent)
                
                # Memory usage
                memory = psutil.virtual_memory()
                self.memory_usage.set(memory.percent)
                
                # Disk usage
                disk = psutil.disk_usage('/')
                self.disk_usage.set(disk.percent)
                
                # Network connections
                connections = len(psutil.net_connections())
                self.open_connections.set(connections)
                
                # Log if resources are high
                if cpu_percent > 80:
                    _logger.warning("High CPU usage: %.1f%%", cpu_percent)
                
                if memory.percent > 90:
                    _logger.warning("High memory usage: %.1f%%", memory.percent)
                
                if disk.percent > 85:
                    _logger.warning("High disk usage: %.1f%%", disk.percent)
                
            except Exception as e:
                _logger.error("Error monitoring system resources: %s", str(e))
            
            # Wait before next check
            await asyncio.sleep(30)
    
    def get_health_metrics(self) -> Dict[str, Any]:
        """
        Get current health metrics.
        """
        return {
            "cpu": {
                "usage_percent": psutil.cpu_percent(interval=1),
                "count": psutil.cpu_count()
            },
            "memory": {
                "usage_percent": psutil.virtual_memory().percent,
                "available_mb": psutil.virtual_memory().available / 1024 / 1024,
                "total_mb": psutil.virtual_memory().total / 1024 / 1024
            },
            "disk": {
                "usage_percent": psutil.disk_usage('/').percent,
                "free_gb": psutil.disk_usage('/').free / 1024 / 1024 / 1024,
                "total_gb": psutil.disk_usage('/').total / 1024 / 1024 / 1024
            },
            "network": {
                "connections": len(psutil.net_connections())
            },
            "process": {
                "pid": psutil.Process().pid,
                "threads": psutil.Process().num_threads(),
                "memory_mb": psutil.Process().memory_info().rss / 1024 / 1024
            }
        }


class PerformanceTracker:
    """
    Track performance metrics for specific operations.
    """
    
    def __init__(self, operation: str, labels: Optional[Dict[str, str]] = None):
        self.operation = operation
        self.labels = labels or {}
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            
            # Log slow operations
            if duration > 1.0:
                _logger.warning(
                    "Slow operation detected: %s took %.2f seconds",
                    self.operation,
                    duration,
                    extra={"labels": self.labels}
                )


# Helper function for tracking database operations
def track_db_operation(operation: str, collection: str):
    """
    Decorator for tracking database operations.
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                # Update metrics
                db_operations.labels(
                    operation=operation,
                    collection=collection
                ).inc()
                
                duration = time.time() - start_time
                db_operation_duration.labels(
                    operation=operation,
                    collection=collection
                ).observe(duration)
                
                return result
                
            except Exception as e:
                # Track failed operations
                db_operations.labels(
                    operation=f"{operation}_failed",
                    collection=collection
                ).inc()
                raise
        
        return wrapper
    return decorator