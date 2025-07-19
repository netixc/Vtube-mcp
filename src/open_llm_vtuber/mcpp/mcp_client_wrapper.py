"""Thread-safe wrapper for MCP Client to avoid nest_asyncio conflicts."""
import asyncio
import threading
import queue
from typing import Dict, Any, List, Optional, Callable
from loguru import logger
import sys

from .mcp_client import MCPClient
from .server_registry import ServerRegistry
from mcp.types import Tool


class ThreadSafeMCPClient:
    """Thread-safe wrapper that runs MCP client in a separate thread."""
    
    def __init__(self, server_registry: ServerRegistry, send_text: Callable = None, client_uid: str = None):
        """Initialize the thread-safe MCP client."""
        self.server_registry = server_registry
        self._send_text = send_text
        self._client_uid = client_uid
        
        # Communication queues
        self._request_queue = queue.Queue()
        self._response_queue = queue.Queue()
        
        # Start worker thread
        self._shutdown = threading.Event()
        self._thread = threading.Thread(target=self._worker_thread, daemon=True)
        self._thread.start()
        
        # Wait for initialization
        self._wait_for_response("init")
        logger.info("ThreadSafeMCPClient: Initialized successfully")
    
    def _worker_thread(self):
        """Worker thread that runs the async event loop."""
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self._async_worker())
        finally:
            loop.close()
    
    async def _async_worker(self):
        """Async worker that processes requests."""
        # Initialize MCP client
        self._mcp_client = MCPClient(self.server_registry, self._send_text, self._client_uid)
        
        # Signal initialization complete
        self._response_queue.put(("init", True, None))
        
        # Process requests
        while not self._shutdown.is_set():
            try:
                # Check for requests (non-blocking)
                try:
                    request = self._request_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                request_id, method, args = request
                
                try:
                    if method == "list_tools":
                        result = await self._mcp_client.list_tools(*args)
                        self._response_queue.put((request_id, result, None))
                    elif method == "call_tool":
                        result = await self._mcp_client.call_tool(*args)
                        self._response_queue.put((request_id, result, None))
                    elif method == "close":
                        await self._mcp_client.aclose()
                        self._response_queue.put((request_id, True, None))
                        break
                    else:
                        self._response_queue.put((request_id, None, f"Unknown method: {method}"))
                except Exception as e:
                    logger.error(f"Error in async worker: {e}")
                    self._response_queue.put((request_id, None, str(e)))
                    
            except Exception as e:
                logger.error(f"Fatal error in async worker: {e}")
                break
    
    def _send_request(self, method: str, *args) -> Any:
        """Send a request to the worker thread and wait for response."""
        import uuid
        request_id = str(uuid.uuid4())
        
        # Send request
        self._request_queue.put((request_id, method, args))
        
        # Wait for response
        return self._wait_for_response(request_id)
    
    def _wait_for_response(self, request_id: str, timeout: float = 120.0) -> Any:
        """Wait for a response with the given request ID."""
        import time
        start_time = time.time()
        
        while True:
            try:
                resp_id, result, error = self._response_queue.get(timeout=1.0)
                if resp_id == request_id:
                    if error:
                        raise RuntimeError(f"MCP operation failed: {error}")
                    return result
                else:
                    # Put it back for other waiters
                    self._response_queue.put((resp_id, result, error))
                    
            except queue.Empty:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    raise TimeoutError(f"Timeout waiting for MCP response after {timeout}s")
    
    def list_tools(self, server_name: str) -> List[Tool]:
        """List tools from a server."""
        return self._send_request("list_tools", server_name)
    
    def call_tool(self, server_name: str, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a server."""
        return self._send_request("call_tool", server_name, tool_name, tool_args)
    
    async def alist_tools(self, server_name: str) -> List[Tool]:
        """Async version of list_tools."""
        return await asyncio.get_event_loop().run_in_executor(None, self.list_tools, server_name)
    
    async def acall_tool(self, server_name: str, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Async version of call_tool."""
        return await asyncio.get_event_loop().run_in_executor(None, self.call_tool, server_name, tool_name, tool_args)
    
    def close(self):
        """Close the client."""
        try:
            self._send_request("close")
        except Exception as e:
            logger.error(f"Error closing MCP client: {e}")
        finally:
            self._shutdown.set()
            if self._thread.is_alive():
                self._thread.join(timeout=5)
    
    async def aclose(self):
        """Async close."""
        await asyncio.get_event_loop().run_in_executor(None, self.close)
    
    def __enter__(self):
        """Context manager entry."""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()