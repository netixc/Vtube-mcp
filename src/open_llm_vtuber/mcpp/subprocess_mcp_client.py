"""Direct subprocess MCP client that bypasses SDK issues with nest_asyncio."""
import asyncio
import json
import os
import subprocess
from typing import Dict, Any, List, Optional, Callable
from loguru import logger
from datetime import timedelta
import uuid

from .server_registry import ServerRegistry


class SubprocessMCPClient:
    """MCP Client that directly manages subprocess communication."""
    
    def __init__(self, server_registry: ServerRegistry, send_text: Callable = None, client_uid: str = None):
        """Initialize the subprocess MCP client."""
        self.server_registry = server_registry
        self._send_text = send_text
        self._client_uid = client_uid
        self._processes: Dict[str, subprocess.Popen] = {}
        self._initialized_servers: set = set()
        logger.info("SubprocessMCPClient: Initialized")
    
    async def _ensure_server_running(self, server_name: str) -> subprocess.Popen:
        """Ensure server is running and return the process."""
        if server_name in self._processes:
            proc = self._processes[server_name]
            if proc.poll() is None:  # Still running
                return proc
            else:
                # Process died, remove it
                del self._processes[server_name]
                self._initialized_servers.discard(server_name)
        
        logger.info(f"Starting MCP server '{server_name}'...")
        server = self.server_registry.get_server(server_name)
        if not server:
            raise ValueError(f"Server '{server_name}' not found")
        
        # Prepare environment
        env = os.environ.copy()
        if server.env:
            env.update(server.env)
        
        # Start subprocess
        cmd = [server.command] + server.args
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1  # Line buffered
        )
        
        self._processes[server_name] = proc
        
        # Initialize if needed
        if server_name not in self._initialized_servers:
            await self._initialize_server(server_name, proc)
            self._initialized_servers.add(server_name)
        
        return proc
    
    async def _initialize_server(self, server_name: str, proc: subprocess.Popen):
        """Initialize the MCP server."""
        # Send initialize request
        request = {
            "jsonrpc": "2.0",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "open-llm-vtuber",
                    "version": "1.0"
                }
            },
            "id": str(uuid.uuid4())
        }
        
        response = await self._send_request(proc, request)
        if "error" in response:
            raise RuntimeError(f"Failed to initialize server: {response['error']}")
        
        logger.info(f"Server '{server_name}' initialized successfully")
    
    async def _send_request(self, proc: subprocess.Popen, request: dict, timeout: float = 10.0) -> dict:
        """Send a JSON-RPC request and get response."""
        # Send request
        request_str = json.dumps(request) + "\n"
        proc.stdin.write(request_str)
        proc.stdin.flush()
        
        # Read response with timeout
        try:
            # Use asyncio to read with timeout
            response_line = await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(None, proc.stdout.readline),
                timeout=timeout
            )
            
            if not response_line:
                raise RuntimeError("No response from server")
            
            return json.loads(response_line)
        except asyncio.TimeoutError:
            raise TimeoutError(f"Request timed out after {timeout}s")
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response: {e}")
    
    async def list_tools(self, server_name: str) -> List[Dict[str, Any]]:
        """List tools from a server."""
        proc = await self._ensure_server_running(server_name)
        
        request = {
            "jsonrpc": "2.0",
            "method": "tools/list",
            "params": {},
            "id": str(uuid.uuid4())
        }
        
        response = await self._send_request(proc, request)
        
        if "error" in response:
            raise RuntimeError(f"Error listing tools: {response['error']}")
        
        # Convert to expected format
        tools = response.get("result", {}).get("tools", [])
        return tools
    
    async def call_tool(self, server_name: str, tool_name: str, tool_args: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on a server."""
        logger.info(f"Calling tool '{tool_name}' on server '{server_name}'")
        proc = await self._ensure_server_running(server_name)
        
        request = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": tool_args
            },
            "id": str(uuid.uuid4())
        }
        
        # Get timeout from server config
        server = self.server_registry.get_server(server_name)
        timeout = server.timeout.total_seconds() if server and server.timeout else 120.0
        
        response = await self._send_request(proc, request, timeout=timeout)
        
        if "error" in response:
            return {
                "metadata": {},
                "content_items": [{"type": "error", "text": str(response["error"])}]
            }
        
        # Extract content from response
        result = response.get("result", {})
        content = result.get("content", [])
        
        # Convert to expected format
        content_items = []
        for item in content:
            if isinstance(item, dict):
                content_items.append(item)
            elif isinstance(item, str):
                content_items.append({"type": "text", "text": item})
        
        if not content_items and isinstance(result, str):
            content_items.append({"type": "text", "text": result})
        
        return {
            "metadata": result.get("metadata", {}),
            "content_items": content_items
        }
    
    async def aclose(self):
        """Close all server connections."""
        logger.info("Closing SubprocessMCPClient...")
        for server_name, proc in self._processes.items():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self._processes.clear()
        self._initialized_servers.clear()
        logger.info("SubprocessMCPClient closed")
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()