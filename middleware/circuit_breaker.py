"""
Circuit Breaker Pattern Implementation for MASTERDB.

Implements a circuit breaker pattern to prevent cascading failures
when external services become unavailable.
"""

import time
import threading
from enum import Enum
from typing import Callable, Any, Optional


class CircuitBreakerState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerError(Exception):
    """Raised when circuit breaker prevents execution."""
    pass


class CircuitBreaker:
    """
    A circuit breaker implementation that monitors external service calls.
    
    The circuit breaker tracks failures and prevents further calls when
    a threshold is reached, allowing a recovery period before attempting
    to call the service again.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        timeout_seconds: float = 60.0,
        recovery_timeout_seconds: float = 30.0,
        expected_exceptions: tuple = (Exception,)
    ):
        """
        Initialize the circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening the circuit
            timeout_seconds: Time to wait before attempting recovery
            recovery_timeout_seconds: Time to wait before attempting recovery
            expected_exceptions: Tuple of exceptions that count as failures
        """
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.expected_exceptions = expected_exceptions
        
        # State management
        self.state = CircuitBreakerState.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.lock = threading.Lock()
        
        # Statistics
        self.success_count = 0
        self.total_calls = 0
        
    def call(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """
        Execute a function with circuit breaker protection.
        
        Args:
            func: The function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
            
        Returns:
            The result of the function call
            
        Raises:
            CircuitBreakerError: If the circuit is open
            Exception: If the underlying function raises an exception
        """
        with self.lock:
            self._check_state()
            
            if self.state == CircuitBreakerState.OPEN:
                raise CircuitBreakerError(
                    f"Circuit breaker is OPEN for {func.__name__}. "
                    f"Will retry after {self.timeout_seconds} seconds."
                )
            
            self.total_calls += 1
            
        try:
            result = func(*args, **kwargs)
            self._handle_success()
            return result
        except self.expected_exceptions as exc:
            self._handle_failure()
            raise
            
    def _check_state(self) -> None:
        """Check and update the circuit breaker state."""
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - (self.last_failure_time or 0) > self.timeout_seconds:
                self.state = CircuitBreakerState.HALF_OPEN
            else:
                # Still in OPEN state
                pass
                
    def _handle_success(self) -> None:
        """Handle successful call."""
        with self.lock:
            self.success_count += 1
            self.failure_count = 0
            self.state = CircuitBreakerState.CLOSED
            
    def _handle_failure(self) -> None:
        """Handle failed call."""
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitBreakerState.OPEN
                
    def reset(self) -> None:
        """Reset the circuit breaker to closed state."""
        with self.lock:
            self.state = CircuitBreakerState.CLOSED
            self.failure_count = 0
            self.success_count = 0
            self.total_calls = 0
            self.last_failure_time = None
            
    def get_stats(self) -> dict:
        """Get circuit breaker statistics."""
        with self.lock:
            return {
                "state": self.state.value,
                "failure_count": self.failure_count,
                "success_count": self.success_count,
                "total_calls": self.total_calls,
                "failure_rate": (
                    self.failure_count / self.total_calls if self.total_calls > 0 else 0
                )
            }