# app/events/base.py
import asyncio
import uuid
import json
import logging
from enum import Enum, auto
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Optional, Dict, List, Union
from pathlib import Path
import threading

logger = logging.getLogger(__name__)

class EventType(Enum):
    """Core event types for LMIM Phase 3"""
    # === Builder Agent Events ===
    BUILD_REQUEST = auto()
    BUILD_STEP = auto()
    BUILD_STEP_COMPLETE = auto()
    BUILD_ERROR = auto()
    BUILD_SUCCESS = auto()
    BUILD_PROJECT = auto()
    BUILD_PROJECT_COMPLETE = auto()
    
    # === Tool Execution Events ===
    TOOL_CALL = auto()
    TOOL_RESULT = auto()
    
    # === Communication Events ===
    USER_MESSAGE = auto()
    AGENT_RESPONSE = auto()
    NOTIFICATION = auto()
    
    # === System Events ===
    WHATSAPP_MESSAGE_INCOMING = auto()
    WHATSAPP_MESSAGE_OUTGOING = auto()
    WHATSAPP_STATUS_UPDATE = auto()  # For 'Searching...' interim messages
    WHATSAPP_SESSION_EXPIRED = auto()
    MEMORY_UPDATE = auto()
    SESSION_START = auto()
    SESSION_END = auto()
    TELEGRAM_MESSAGE_INCOMING = "telegram_message_incoming"
    TELEGRAM_REPLY_READY = "telegram_reply_ready"

@dataclass
class Event:
    """Immutable event payload with metadata"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: EventType = EventType.USER_MESSAGE
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=datetime.utcnow().timestamp)
    correlation_id: Optional[str] = None
    priority: int = 5
    source: str = "lmim_core"
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type.name,
            'payload': self.payload,
            'timestamp': self.timestamp,
            'correlation_id': self.correlation_id,
            'priority': self.priority,
            'source': self.source
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'Event':
        data = data.copy()
        data['type'] = EventType[data['type']]
        return cls(**data)

class EventBus:
    """
    Thread-safe event bus for Phase 3.
    Supports cross-thread publishing via run_coroutine_threadsafe.
    """
    
    def __init__(self):
        self._subscribers: Dict[EventType, List[Callable]] = {}
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._processor_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # ← Store loop reference
        self._lock = threading.Lock()  # ← Thread-safe subscriber management
        logger.info("EventBus initialized")
        
    def subscribe(self, event_type: EventType, handler: Callable, priority: int = 5):
        """Register an async handler for an event type (thread-safe)"""
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            handlers = self._subscribers[event_type]
            handlers.append((priority, handler))
            handlers.sort(key=lambda x: x[0], reverse=True)
            self._subscribers[event_type] = [h for _, h in handlers]
        logger.debug(f"Subscribed handler to {event_type.name} (priority={priority})")
        
    def unsubscribe(self, event_type: EventType, handler: Callable):
        """Remove a handler (thread-safe)"""
        with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type] = [
                    h for h in self._subscribers[event_type] if h != handler
                ]
            
    async def publish(self, event: Event) -> List[Any]:
        """Publish an event to all subscribers (async)"""
        logger.debug(f"Publishing: {event.type.name} [{event.id[:8]}...]")
        
        # Queue for background processing
        await self._event_queue.put(event)
        
        # Immediate fan-out to subscribers
        with self._lock:
            handlers = self._subscribers.get(event.type, [])
        
        if not handlers:
            logger.debug(f"No subscribers for {event.type.name}")
            return []
            
        results = await asyncio.gather(
            *[h(event) for h in handlers],
            return_exceptions=True
        )
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"Handler #{i} failed for {event.type.name}: {result}")
                
        return results
    
    def publish_sync(self, event: Event) -> None:
        """
        Fire-and-forget publish from sync contexts (Flask routes).
        Uses run_coroutine_threadsafe to schedule on EventBus loop.
        """
        # Wait briefly for loop to be ready (startup race condition)
        for _ in range(10):
            if self._loop is not None and self._loop.is_running():
                break
            time.sleep(0.05)
        
        if self._loop and self._loop.is_running():
            try:
                # Schedule on the EventBus thread's loop
                asyncio.run_coroutine_threadsafe(self.publish(event), self._loop)
                logger.debug(f"Scheduled event on EventBus loop: {event.type.name}")
            except Exception as e:
                logger.error(f"Failed to schedule event: {e}")
        else:
            # Fallback: queue for later processing (rare, only during startup)
            logger.warning(f"EventBus loop not ready; queuing event: {event.type.name}")
            # Could add to a pending queue here if needed
            
    async def _process_queue(self):
        """Background processor for queued events"""
        while self._running:
            try:
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                logger.debug(f"Processed queued event: {event.type.name}")
                self._event_queue.task_done()
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                
    async def start(self):
        """Start the background event processor"""
        if self._running:
            return
        self._loop = asyncio.get_running_loop()  # ← Capture this thread's loop
        self._running = True
        self._processor_task = asyncio.create_task(self._process_queue())
        logger.info("EventBus processor started")
        
    def stop(self):
        """Stop the processor"""
        self._running = False
        if self._processor_task:
            self._processor_task.cancel()
        logger.info("EventBus processor stopped")

# Global singleton instance
event_bus = EventBus()

# Convenience function for sync contexts (Flask routes)
def emit(event_type: EventType, payload: Dict, **kwargs) -> None:
    """Quick emit from anywhere in sync code"""
    event = Event(type=event_type, payload=payload, **kwargs)
    event_bus.publish_sync(event)

# Add time import at top if missing
import time


