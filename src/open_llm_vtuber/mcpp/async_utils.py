"""Utilities for handling async operations in different contexts."""
import asyncio
import sys
from typing import Any, Coroutine, TypeVar
from concurrent.futures import ThreadPoolExecutor
import threading

T = TypeVar('T')

def is_nest_asyncio_applied() -> bool:
    """Check if nest_asyncio has been applied to the current event loop."""
    try:
        # Check if nest_asyncio module is imported and has been applied
        if 'nest_asyncio' in sys.modules:
            nest_asyncio = sys.modules['nest_asyncio']
            # Check if apply() has been called
            if hasattr(nest_asyncio, '_patched') and nest_asyncio._patched:
                return True
        
        # Also check the event loop for patches
        try:
            loop = asyncio.get_running_loop()
            # Check for nest_asyncio modifications
            return hasattr(loop, '_nest_patched') or hasattr(loop, '__patched_by_nest_asyncio__')
        except RuntimeError:
            # No running loop
            pass
            
        return False
    except Exception:
        return False

def run_in_thread_pool(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine in a separate thread with its own event loop."""
    def run_in_new_loop():
        # Create a new event loop for this thread
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
            asyncio.set_event_loop(None)
    
    # Run in thread pool
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_in_new_loop)
        return future.result()

async def run_async_safe(coro: Coroutine[Any, Any, T]) -> T:
    """Run a coroutine safely, handling nest_asyncio conflicts."""
    if is_nest_asyncio_applied():
        # If nest_asyncio is applied, run in a separate thread
        return await asyncio.get_event_loop().run_in_executor(
            None, run_in_thread_pool, coro
        )
    else:
        # Normal async execution
        return await coro