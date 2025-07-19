"""Synchronous wrapper for MCP Client to avoid nest_asyncio conflicts."""
import asyncio
import json
import os
import threading
import queue
from typing import Dict, Any, List, Optional, Callable
from loguru import logger
from datetime import timedelta

from mcp import ClientSession, StdioServerParameters
from mcp.types import Tool
from mcp.client.stdio import stdio_client

from .server_registry import ServerRegistry


class SyncMCPClient:
    """Synchronous wrapper for MCP Client that runs in a separate thread."""
    
    def __init__(self, server_registry: ServerRegistry, send_text: Callable = None, client_uid: str = None) -> None:
        """Initialize the Sync MCP Client."""
        self.server_registry = server_registry
        self._send_text = send_text
        self._client_uid = client_uid
        
        # Create a separate thread for async operations
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._shutdown = threading.Event()
        self._result_queue = queue.Queue()
        
        # Start the async thread
        self._start_async_thread()
        
        # Wait for thread to be ready
        if not self._ready.wait(timeout=10):
            raise RuntimeError("Failed to start async thread")
            
        logger.info("SyncMCPClient: Initialized successfully")
    
    def _start_async_thread(self):
        """Start the async thread."""
        def run_loop():
            # Create new event loop for this thread
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # Initialize async client
            self._loop.run_until_complete(self._init_async())
            
            # Signal ready
            self._ready.set()
            
            # Run until shutdown
            self._loop.run_until_complete(self._run_async())
            
        self._thread = threading.Thread(target=run_loop, daemon=True)
        self._thread.start()
    
    async def _init_async(self):
        """Initialize async components."""
        self._sessions: Dict[str, ClientSession] = {}
        self._tools_cache: Dict[str, List[Tool]] = {}
        logger.info("SyncMCPClient: Async components initialized")
    
    async def _run_async(self):
        """Run the async event loop."""
        while not self._shutdown.is_set():
            await asyncio.sleep(0.1)
        
        # Cleanup
        await self._cleanup_async()
    
    async def _cleanup_async(self):
        """Clean up async resources."""
        for server_name, session in self._sessions.items():
            try:
                await session.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"Error closing session for {server_name}: {e}")
        self._sessions.clear()
        self._tools_cache.clear()
    
    async def _get_or_create_session(self, server_name: str) -> ClientSession:
        """Get existing session or create new one."""
        if server_name in self._sessions:
            return self._sessions[server_name]
            
        logger.info(f"SyncMCPClient: Creating session for '{server_name}'...")
        server = self.server_registry.get_server(server_name)
        if not server:
            raise ValueError(f"Server '{server_name}' not found")
            
        # Prepare environment
        env = os.environ.copy()
        if server.env:
            env.update(server.env)
            
        server_params = StdioServerParameters(
            command=server.command,
            args=server.args,
            env=env,
        )
        
        # Create stdio client
        async with stdio_client(server_params) as (read, write):
            # Create session
            timeout = server.timeout if server.timeout else timedelta(seconds=120)
            session = ClientSession(read, write, read_timeout_seconds=timeout)
            
            async with session:
                await session.initialize()
                self._sessions[server_name] = session
                logger.info(f"SyncMCPClient: Session created for '{server_name}'")
                
                # Keep session alive
                while server_name in self._sessions:
                    await asyncio.sleep(0.1)
                    
        return session
    
    def _run_in_thread(self, coro):
        """Run coroutine in async thread and return result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=120)  # 2 minute timeout
    
    def list_tools(self, server_name: str) -> List[Tool]:
        """List tools from a server (synchronous)."""
        # Check cache first
        if server_name in self._tools_cache:
            return self._tools_cache[server_name]
            
        async def _list_tools():
            session = await self._get_or_create_session(server_name)
            response = await session.list_tools()
            self._tools_cache[server_name] = response.tools
            return response.tools
            
        return self._run_in_thread(_list_tools())
    
    def call_tool(self, server_name: str, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a server (synchronous)."""
        logger.info(f"SyncMCPClient: Calling tool '{tool_name}' on '{server_name}'")
        
        async def _call_tool():
            session = await self._get_or_create_session(server_name)
            
            # Get timeout
            server = self.server_registry.get_server(server_name)
            timeout = server.timeout if server and server.timeout else timedelta(seconds=120)
            
            # Call tool
            response = await session.call_tool(tool_name, tool_args, read_timeout_seconds=timeout)
            
            # Process response
            if response.isError:
                error_text = (
                    response.content[0].text if response.content and hasattr(response.content[0], "text") 
                    else "Unknown server error"
                )
                return {
                    "metadata": getattr(response, "metadata", {}),
                    "content_items": [{"type": "error", "text": error_text}]
                }
            
            # Extract content items
            content_items = []
            if response.content:
                for item in response.content:
                    item_dict = {"type": getattr(item, "type", "text")}
                    for attr in ["text", "data", "mimeType", "url", "altText"]:
                        if hasattr(item, attr) and getattr(item, attr) is not None:
                            item_dict[attr] = getattr(item, attr)
                    content_items.append(item_dict)
            else:
                content_items.append({"type": "text", "text": ""})
                
            return {
                "metadata": getattr(response, "metadata", {}),
                "content_items": content_items,
            }
            
        return self._run_in_thread(_call_tool())
    
    def close(self):
        """Close the client."""
        logger.info("SyncMCPClient: Shutting down...")
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("SyncMCPClient: Shutdown complete")
    
    def __enter__(self):
        """Enter context manager."""
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager."""
        self.close()