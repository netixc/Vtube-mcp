"""MCP Client for Open-LLM-Vtuber."""
import json
import os
import asyncio
from contextlib import AsyncExitStack
from typing import Dict, Any, List, Callable
from loguru import logger
from datetime import timedelta
import threading
from concurrent.futures import ThreadPoolExecutor

from mcp import ClientSession, StdioServerParameters
from mcp.types import Tool
from mcp.client.stdio import stdio_client

from .server_registry import ServerRegistry
from ..message_handler import message_handler
from .async_utils import is_nest_asyncio_applied, run_in_thread_pool

DEFAULT_TIMEOUT = timedelta(seconds=120)


class MCPClient:
    """MCP Client for Open-LLM-Vtuber.
    Manages persistent connections to multiple MCP servers.
    """

    def __init__(self, server_registery: ServerRegistry, send_text: Callable = None, client_uid: str = None) -> None:
        """Initialize the MCP Client."""
        self.exit_stack: AsyncExitStack = AsyncExitStack()
        self.active_sessions: Dict[str, ClientSession] = {}
        self._list_tools_cache: Dict[str, List[Tool]] = {}  # Cache for list_tools
        self._send_text: Callable = send_text
        self._client_uid: str = client_uid

        if isinstance(server_registery, ServerRegistry):
            self.server_registery = server_registery
        else:
            raise TypeError(
                "MCPC: Invalid server manager. Must be an instance of ServerRegistry."
            )
        logger.info("MCPC: Initialized MCPClient instance.")

    async def _ensure_server_running_and_get_session(
        self, server_name: str
    ) -> ClientSession:
        """Gets the existing session or creates a new one."""
        if server_name in self.active_sessions:
            return self.active_sessions[server_name]

        logger.info(f"MCPC: Starting and connecting to server '{server_name}'...")
        server = self.server_registery.get_server(server_name)
        if not server:
            raise ValueError(
                f"MCPC: Server '{server_name}' not found in available servers."
            )

        timeout = server.timeout if server.timeout else DEFAULT_TIMEOUT
        logger.info(f"MCPC: Using timeout of {timeout.total_seconds()} seconds for server '{server_name}'")

        # Prepare environment - merge server env with current env
        env = dict(os.environ) if server.env else os.environ.copy()
        if server.env:
            env.update(server.env)
        
        server_params = StdioServerParameters(
            command=server.command,
            args=server.args,
            env=env,
        )

        try:
            logger.debug(f"MCPC: Creating stdio transport for '{server_name}' with command: {server.command} {server.args}")
            
            # Create stdio transport and session
            stdio_transport = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            read, write = stdio_transport
            logger.debug(f"MCPC: Stdio transport created successfully for '{server_name}'")

            # ClientSession expects timedelta, not float
            logger.debug(f"MCPC: Creating ClientSession for '{server_name}' with timeout: {timeout}")
            session = await self.exit_stack.enter_async_context(
                ClientSession(read, write, read_timeout_seconds=timeout)
            )
            logger.debug(f"MCPC: ClientSession created, initializing for '{server_name}'")
            await session.initialize()
            logger.debug(f"MCPC: Session initialized successfully for '{server_name}'")

            self.active_sessions[server_name] = session
            logger.info(f"MCPC: Successfully connected to server '{server_name}'.")
            return session
        except Exception as e:
            logger.exception(f"MCPC: Failed to connect to server '{server_name}': {e}")
            logger.error(f"MCPC: Server config - command: {server.command}, args: {server.args}, env: {server.env}")
            raise RuntimeError(
                f"MCPC: Failed to connect to server '{server_name}'."
            ) from e

    async def list_tools(self, server_name: str) -> List[Tool]:
        """List all available tools on the specified server."""
        # Check cache first
        if server_name in self._list_tools_cache:
            logger.debug(f"MCPC: Cache hit for list_tools on server '{server_name}'.")
            return self._list_tools_cache[server_name]

        logger.debug(f"MCPC: Cache miss for list_tools on server '{server_name}'. Fetching...")
        session = await self._ensure_server_running_and_get_session(server_name)
        response = await session.list_tools()

        # Store in cache before returning
        self._list_tools_cache[server_name] = response.tools
        logger.debug(f"MCPC: Cached list_tools result for server '{server_name}'.")
        return response.tools

    async def call_tool(
        self, server_name: str, tool_name: str, tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Call a tool on the specified server.

        Returns:
            Dict containing the metadata and content_items from the tool response.
        """
        logger.info(f"🔧 MCPC: Starting tool call '{tool_name}' on server '{server_name}'")
        logger.info(f"📥 Tool arguments: {tool_args}")
        
        # Check if we need to run in a separate thread due to nest_asyncio
        if is_nest_asyncio_applied():
            logger.info("Detected nest_asyncio environment, using thread pool execution")
            
            async def _call_tool_async():
                return await self._call_tool_internal(server_name, tool_name, tool_args)
            
            # Run in thread pool to avoid nest_asyncio conflicts
            result = await asyncio.get_event_loop().run_in_executor(
                None, run_in_thread_pool, _call_tool_async()
            )
            return result
        else:
            # Normal async execution
            return await self._call_tool_internal(server_name, tool_name, tool_args)
    
    async def _call_tool_internal(
        self, server_name: str, tool_name: str, tool_args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Internal method to call a tool."""
        session = await self._ensure_server_running_and_get_session(server_name)
        logger.info(f"✅ Got session for server '{server_name}'")
        
        logger.info(f"MCPC: Calling tool '{tool_name}' on server '{server_name}'...")
        
        try:
            logger.info(f"⏳ Sending request to MCP server...")
            # Get timeout for this server
            server = self.server_registery.get_server(server_name)
            timeout = server.timeout if server and server.timeout else DEFAULT_TIMEOUT
            
            # Ensure timeout is a timedelta object
            if isinstance(timeout, (int, float)):
                timeout = timedelta(seconds=timeout)
            logger.info(f"Using timeout of {timeout.total_seconds()} seconds for tool call")
            logger.debug(f"Session state before call: {session}")
            logger.debug(f"Calling tool with args: {tool_args}")
            
            response = await session.call_tool(tool_name, tool_args, read_timeout_seconds=timeout)
            logger.info(f"✅ Received response from MCP server")
        except Exception as e:
            logger.error(f"❌ Error during tool call: {e}")
            raise

        if response.isError:
            error_text = (
                response.content[0].text if response.content and hasattr(response.content[0], "text") else "Unknown server error"
            )
            logger.error(f"MCPC: Error calling tool '{tool_name}': {error_text}")
            # Return error information within the standard structure
            return {
                "metadata": getattr(response, "metadata", {}),
                "content_items": [{"type": "error", "text": error_text}]
            }

        content_items = []
        if response.content:
            for item in response.content:
                item_dict = {"type": getattr(item, "type", "text")}
                # Extract available attributes from content item
                for attr in ["text", "data", "mimeType", "url", "altText"]: # Added url and altText
                    if hasattr(item, attr) and getattr(item, attr) is not None: # Check for None
                        item_dict[attr] = getattr(item, attr)
                content_items.append(item_dict)
        else:
            logger.warning(
                f"MCPC: Tool '{tool_name}' returned no content. Returning empty content_items."
            )
            content_items.append({"type": "text", "text": ""}) # Ensure content_items is not empty

        result = {
            "metadata": getattr(response, "metadata", {}),
            "content_items": content_items,
        }
        logger.info(f"📤 Tool call complete. Content items: {len(content_items)}")
        logger.debug(f"Full result: {result}")
        return result

    async def aclose(self) -> None:
        """Closes all active server connections."""
        logger.info(
            f"MCPC: Closing client instance and {len(self.active_sessions)} active connections..."
        )
        
        await self.exit_stack.aclose()
        self.active_sessions.clear()
        self._list_tools_cache.clear() # Clear cache on close
        self.exit_stack = AsyncExitStack()
        logger.info("MCPC: Client instance closed.")

    async def __aenter__(self) -> "MCPClient":
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """Exit the async context manager."""
        await self.aclose()
        if exc_type:
            logger.error(f"MCPC: Exception in async context: {exc_value}")


# if __name__ == "__main__":
#     # Test the MCPClient.
#     async def main():
#         server_registery = ServerRegistry()
#         async with MCPClient(server_registery) as client:
#             # Assuming 'example' server and 'example_tool' exist
#             # The old call used: await client.call_tool("example_tool", {"arg1": "value1"})
#             # The new call needs server name:
#             try:
#                 result = await client.call_tool("example", "example_tool", {"arg1": "value1"})
#                 print(f"Tool result: {result}")
#                 # Test error handling by calling a non-existent tool
#                 await client.call_tool("example", "non_existent_tool", {})
#             except ValueError as e:
#                 print(f"Caught expected error: {e}")
#             except Exception as e:
#                 print(f"Caught unexpected error: {e}")

#     asyncio.run(main())
