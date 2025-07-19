import os
import json

from loguru import logger
from fastapi import WebSocket

from prompts import prompt_loader
from .live2d_model import Live2dModel
from .asr.asr_interface import ASRInterface
from .tts.tts_interface import TTSInterface
from .vad.vad_interface import VADInterface
from .agent.agents.agent_interface import AgentInterface
from .translate.translate_interface import TranslateInterface

from .asr.asr_factory import ASRFactory
from .tts.tts_factory import TTSFactory
from .vad.vad_factory import VADFactory
from .agent.agent_factory import AgentFactory
from .translate.translate_factory import TranslateFactory

from .config_manager import (
    Config,
    AgentConfig,
    CharacterConfig,
    SystemConfig,
    ASRConfig,
    TTSConfig,
    VADConfig,
    TranslatorConfig,
    read_yaml,
    validate_config,
)


class ServiceContext:
    """Initializes, stores, and updates the asr, tts, and llm instances and other
    configurations for a connected client."""

    def __init__(self):
        self.config: Config = None
        self.system_config: SystemConfig = None
        self.character_config: CharacterConfig = None

        self.live2d_model: Live2dModel = None
        self.asr_engine: ASRInterface = None
        self.tts_engine: TTSInterface = None
        self.agent_engine: AgentInterface = None
        # translate_engine can be none if translation is disabled
        self.vad_engine: VADInterface | None = None
        self.translate_engine: TranslateInterface | None = None

        # the system prompt is a combination of the persona prompt and live2d expression prompt
        self.system_prompt: str = None

        self.history_uid: str = ""  # Add history_uid field

    def __str__(self):
        return (
            f"ServiceContext:\n"
            f"  System Config: {'Loaded' if self.system_config else 'Not Loaded'}\n"
            f"    Details: {json.dumps(self.system_config.model_dump(), indent=6) if self.system_config else 'None'}\n"
            f"  Live2D Model: {self.live2d_model.model_info if self.live2d_model else 'Not Loaded'}\n"
            f"  ASR Engine: {type(self.asr_engine).__name__ if self.asr_engine else 'Not Loaded'}\n"
            f"    Config: {json.dumps(self.character_config.asr_config.model_dump(), indent=6) if self.character_config.asr_config else 'None'}\n"
            f"  TTS Engine: {type(self.tts_engine).__name__ if self.tts_engine else 'Not Loaded'}\n"
            f"    Config: {json.dumps(self.character_config.tts_config.model_dump(), indent=6) if self.character_config.tts_config else 'None'}\n"
            f"  LLM Engine: {type(self.agent_engine).__name__ if self.agent_engine else 'Not Loaded'}\n"
            f"    Agent Config: {json.dumps(self.character_config.agent_config.model_dump(), indent=6) if self.character_config.agent_config else 'None'}\n"
            f"  VAD Engine: {type(self.vad_engine).__name__ if self.vad_engine else 'Not Loaded'}\n"
            f"    Agent Config: {json.dumps(self.character_config.vad_config.model_dump(), indent=6) if self.character_config.vad_config else 'None'}\n"
            f"  System Prompt: {self.system_prompt or 'Not Set'}"
        )

    # ==== Initializers

    def load_cache(
        self,
        config: Config,
        system_config: SystemConfig,
        character_config: CharacterConfig,
        live2d_model: Live2dModel,
        asr_engine: ASRInterface,
        tts_engine: TTSInterface,
        vad_engine: VADInterface,
        agent_engine: AgentInterface,
        translate_engine: TranslateInterface | None,
    ) -> None:
        """
        Load the ServiceContext with the reference of the provided instances.
        Pass by reference so no reinitialization will be done.
        """
        if not character_config:
            raise ValueError("character_config cannot be None")
        if not system_config:
            raise ValueError("system_config cannot be None")

        self.config = config
        self.system_config = system_config
        self.character_config = character_config
        self.live2d_model = live2d_model
        self.asr_engine = asr_engine
        self.tts_engine = tts_engine
        self.vad_engine = vad_engine
        self.agent_engine = agent_engine
        self.translate_engine = translate_engine

        logger.debug(f"Loaded service context with cache: {character_config}")

    def load_from_config(self, config: Config) -> None:
        """
        Load the ServiceContext with the config.
        Reinitialize the instances if the config is different.

        Parameters:
        - config (Dict): The configuration dictionary.
        """
        if not self.config:
            self.config = config

        if not self.system_config:
            self.system_config = config.system_config

        if not self.character_config:
            self.character_config = config.character_config

        # update all sub-configs

        # init live2d from character config
        self.init_live2d(config.character_config.live2d_model_name)

        # init asr from character config
        self.init_asr(config.character_config.asr_config)

        # init tts from character config
        self.init_tts(config.character_config.tts_config)

        # init vad from character config
        self.init_vad(config.character_config.vad_config)

        # init agent from character config
        self.init_agent(
            config.character_config.agent_config,
            config.character_config.persona_prompt,
        )

        self.init_translate(
            config.character_config.tts_preprocessor_config.translator_config
        )

        # store typed config references
        self.config = config
        self.system_config = config.system_config or self.system_config
        self.character_config = config.character_config

    def init_live2d(self, live2d_model_name: str) -> None:
        logger.info(f"Initializing Live2D: {live2d_model_name}")
        try:
            self.live2d_model = Live2dModel(live2d_model_name)
            self.character_config.live2d_model_name = live2d_model_name
        except Exception as e:
            logger.critical(f"Error initializing Live2D: {e}")
            logger.critical("Try to proceed without Live2D...")

    def init_asr(self, asr_config: ASRConfig) -> None:
        if not self.asr_engine or (self.character_config.asr_config != asr_config):
            logger.info(f"Initializing ASR: {asr_config.asr_model}")
            self.asr_engine = ASRFactory.get_asr_system(
                asr_config.asr_model,
                **getattr(asr_config, asr_config.asr_model).model_dump(),
            )
            # saving config should be done after successful initialization
            self.character_config.asr_config = asr_config
        else:
            logger.info("ASR already initialized with the same config.")

    def init_tts(self, tts_config: TTSConfig) -> None:
        if not self.tts_engine or (self.character_config.tts_config != tts_config):
            logger.info(f"Initializing TTS: {tts_config.tts_model}")
            self.tts_engine = TTSFactory.get_tts_engine(
                tts_config.tts_model,
                **getattr(tts_config, tts_config.tts_model.lower()).model_dump(),
            )
            # saving config should be done after successful initialization
            self.character_config.tts_config = tts_config
        else:
            logger.info("TTS already initialized with the same config.")

    def init_vad(self, vad_config: VADConfig) -> None:
        if not self.vad_engine or (self.character_config.vad_config != vad_config):
            logger.info(f"Initializing VAD: {vad_config.vad_model}")
            self.vad_engine = VADFactory.get_vad_engine(
                vad_config.vad_model,
                **getattr(vad_config, vad_config.vad_model.lower()).model_dump(),
            )
            # saving config should be done after successful initialization
            self.character_config.vad_config = vad_config
        else:
            logger.info("VAD already initialized with the same config.")

    def init_agent(self, agent_config: AgentConfig, persona_prompt: str) -> None:
        """Initialize or update the LLM engine based on agent configuration."""
        logger.info(f"Initializing Agent: {agent_config.conversation_agent_choice}")

        if (
            self.agent_engine is not None
            and agent_config == self.character_config.agent_config
            and persona_prompt == self.character_config.persona_prompt
        ):
            logger.debug("Agent already initialized with the same config.")
            return

        system_prompt = self.construct_system_prompt(persona_prompt)

        # Pass avatar to agent factory
        avatar = self.character_config.avatar or ""  # Get avatar from config

        # Initialize MCP components if enabled
        mcp_components = {}
        if agent_config.conversation_agent_choice == "basic_memory_agent":
            basic_memory_settings = agent_config.agent_settings.basic_memory_agent
            if basic_memory_settings and basic_memory_settings.use_mcpp:
                from .mcpp.server_registry import ServerRegistry
                from .mcpp.mcp_client import MCPClient
                from .mcpp.subprocess_mcp_client import SubprocessMCPClient
                from .mcpp.tool_manager import ToolManager
                from .mcpp.tool_adapter import ToolAdapter
                from .mcpp.tool_executor import ToolExecutor
                
                logger.info("Initializing MCP components...")
                
                # Initialize MCP components
                server_registry = ServerRegistry()
                tool_adapter = ToolAdapter()
                
                # Load tools from enabled servers
                enabled_servers = basic_memory_settings.mcp_enabled_servers or []
                if enabled_servers:
                    import asyncio
                    
                    # Handle async loading of tools
                    all_tools = []
                    import nest_asyncio
                    nest_asyncio.apply()
                    
                    # Always use SubprocessMCPClient when nest_asyncio is needed
                    logger.info("Using SubprocessMCPClient for compatibility with nest_asyncio")
                    mcp_client = SubprocessMCPClient(server_registry)
                    
                    async def load_tools_async():
                        tools = []
                        for server_name in enabled_servers:
                            try:
                                # List tools from each server (server starts automatically on first access)
                                server_tools = await mcp_client.list_tools(server_name)
                                logger.info(f"Loaded {len(server_tools)} tools from MCP server: {server_name}")
                                
                                # Add server name to each tool for grouping
                                for tool in server_tools:
                                    # Handle both dict and object formats
                                    if isinstance(tool, dict):
                                        name = tool.get('name', '')
                                        description = tool.get('description', '')
                                        input_schema = tool.get('inputSchema', {})
                                    else:
                                        name = tool.name
                                        description = tool.description
                                        input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                                    
                                    # Override description for exec tool to be clearer
                                    if name == "exec" and server_name == "MacOS-Control":
                                        description = "Execute a shell command on the user's Mac computer. Can be used to open applications like Safari, control the system, and perform various tasks."
                                    
                                    tool_dict = {
                                        "name": name,
                                        "description": description,
                                        "server_name": server_name,
                                        "input_schema": input_schema
                                    }
                                    tools.append(tool_dict)
                                    
                            except Exception as e:
                                logger.error(f"Failed to load tools from MCP server {server_name}: {e}")
                        return tools
                    
                    loop = asyncio.new_event_loop()
                    all_tools = loop.run_until_complete(load_tools_async())
                    
                    logger.info(f"Total tools loaded from MCP servers: {len(all_tools)}")
                    
                    # Format tools for different APIs
                    tools_dict = {}
                    formatted_tools_openai = []
                    formatted_tools_claude = []
                    
                    if all_tools:
                        # Convert tool list to FormattedTool objects
                        from .mcpp.types import FormattedTool
                        for tool in all_tools:
                            formatted_tool = FormattedTool(
                                input_schema=tool.get("input_schema", {}),
                                related_server=tool["server_name"],
                                description=tool["description"]
                            )
                            tools_dict[tool["name"]] = formatted_tool
                        
                        # Format tools for each API
                        formatted_tools_openai, formatted_tools_claude = tool_adapter.format_tools_for_api(
                            tools_dict
                        )
                    
                    # Initialize tool manager with formatted tools
                    tool_manager = ToolManager(
                        formatted_tools_openai=formatted_tools_openai,
                        formatted_tools_claude=formatted_tools_claude,
                        initial_tools_dict=tools_dict
                    )
                    
                    # Initialize tool executor with correct parameters
                    tool_executor = ToolExecutor(mcp_client, tool_manager)
                    
                    # Generate MCP prompt string
                    mcp_prompt_string = self._generate_mcp_prompt_string(all_tools)
                    
                    mcp_components = {
                        "tool_manager": tool_manager,
                        "tool_executor": tool_executor,
                        "mcp_prompt_string": mcp_prompt_string,
                    }
                else:
                    logger.warning("MCP is enabled but no servers are configured")

        try:
            self.agent_engine = AgentFactory.create_agent(
                conversation_agent_choice=agent_config.conversation_agent_choice,
                agent_settings=agent_config.agent_settings.model_dump(),
                llm_configs=agent_config.llm_configs.model_dump(),
                system_prompt=system_prompt,
                live2d_model=self.live2d_model,
                tts_preprocessor_config=self.character_config.tts_preprocessor_config,
                character_avatar=avatar,  # Add avatar parameter
                system_config=self.system_config.model_dump(),
                **mcp_components,
            )

            logger.debug(f"Agent choice: {agent_config.conversation_agent_choice}")
            logger.debug(f"System prompt: {system_prompt}")

            # Save the current configuration
            self.character_config.agent_config = agent_config
            self.system_prompt = system_prompt

        except Exception as e:
            logger.error(f"Failed to initialize agent: {e}")
            raise

    def init_translate(self, translator_config: TranslatorConfig) -> None:
        """Initialize or update the translation engine based on the configuration."""

        if not translator_config.translate_audio:
            logger.debug("Translation is disabled.")
            return

        if (
            not self.translate_engine
            or self.character_config.tts_preprocessor_config.translator_config
            != translator_config
        ):
            logger.info(
                f"Initializing Translator: {translator_config.translate_provider}"
            )
            self.translate_engine = TranslateFactory.get_translator(
                translator_config.translate_provider,
                getattr(
                    translator_config, translator_config.translate_provider
                ).model_dump(),
            )
            self.character_config.tts_preprocessor_config.translator_config = (
                translator_config
            )
        else:
            logger.info("Translation already initialized with the same config.")

    # ==== utils

    def construct_system_prompt(self, persona_prompt: str) -> str:
        """
        Append tool prompts to persona prompt.

        Parameters:
        - persona_prompt (str): The persona prompt.

        Returns:
        - str: The system prompt with all tool prompts appended.
        """
        logger.debug(f"constructing persona_prompt: '''{persona_prompt}'''")

        for prompt_name, prompt_file in self.system_config.tool_prompts.items():
            if prompt_name == "group_conversation_prompt":
                continue

            prompt_content = prompt_loader.load_util(prompt_file)

            if prompt_name == "live2d_expression_prompt":
                prompt_content = prompt_content.replace(
                    "[<insert_emomap_keys>]", self.live2d_model.emo_str
                )

            persona_prompt += prompt_content

        logger.debug("\n === System Prompt ===")
        logger.debug(persona_prompt)

        return persona_prompt

    def _generate_mcp_prompt_string(self, tools: list) -> str:
        """
        Generate MCP prompt string from available tools.
        
        Parameters:
        - tools: List of available tools from MCP servers
        
        Returns:
        - str: The formatted MCP prompt string
        """
        try:
            # Load the MCP prompt template
            mcp_prompt_template = prompt_loader.load_util("mcp_prompt")
            
            # Group tools by server
            tools_by_server = {}
            for tool in tools:
                server_name = tool.get("server_name", "unknown")
                if server_name not in tools_by_server:
                    tools_by_server[server_name] = []
                tools_by_server[server_name].append(tool)
            
            # Format tools for the prompt
            formatted_tools = []
            for server_name, server_tools in tools_by_server.items():
                formatted_tools.append(f"**{server_name}**:")
                for tool in server_tools:
                    tool_name = tool.get("name", "unknown")
                    description = tool.get("description", "No description")
                    formatted_tools.append(f"  - `{tool_name}`: {description}")
                formatted_tools.append("")  # Empty line between servers
            
            # Replace placeholder in template
            mcp_prompt_string = mcp_prompt_template.replace(
                "[<insert_mcp_servers_with_tools>]",
                "\n".join(formatted_tools)
            )
            
            return mcp_prompt_string
            
        except Exception as e:
            logger.error(f"Failed to generate MCP prompt string: {e}")
            return ""

    async def handle_config_switch(
        self,
        websocket: WebSocket,
        config_file_name: str,
    ) -> None:
        """
        Handle the configuration switch request.
        Change the configuration to a new config and notify the client.

        Parameters:
        - websocket (WebSocket): The WebSocket connection.
        - config_file_name (str): The name of the configuration file.
        """
        try:
            new_character_config_data = None

            if config_file_name == "conf.yaml":
                # Load base config
                new_character_config_data = read_yaml("conf.yaml").get(
                    "character_config"
                )
            else:
                # Load alternative config and merge with base config
                characters_dir = self.system_config.config_alts_dir
                file_path = os.path.normpath(
                    os.path.join(characters_dir, config_file_name)
                )
                if not file_path.startswith(characters_dir):
                    raise ValueError("Invalid configuration file path")

                alt_config_data = read_yaml(file_path).get("character_config")

                # Start with original config data and perform a deep merge
                new_character_config_data = deep_merge(
                    self.config.character_config.model_dump(), alt_config_data
                )

            if new_character_config_data:
                new_config = {
                    "system_config": self.system_config.model_dump(),
                    "character_config": new_character_config_data,
                }
                new_config = validate_config(new_config)
                self.load_from_config(new_config)
                logger.debug(f"New config: {self}")
                logger.debug(
                    f"New character config: {self.character_config.model_dump()}"
                )

                # Send responses to client
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "set-model-and-conf",
                            "model_info": self.live2d_model.model_info,
                            "conf_name": self.character_config.conf_name,
                            "conf_uid": self.character_config.conf_uid,
                        }
                    )
                )

                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "config-switched",
                            "message": f"Switched to config: {config_file_name}",
                        }
                    )
                )

                logger.info(f"Configuration switched to {config_file_name}")
            else:
                raise ValueError(
                    f"Failed to load configuration from {config_file_name}"
                )

        except Exception as e:
            logger.error(f"Error switching configuration: {e}")
            logger.debug(self)
            await websocket.send_text(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error switching configuration: {str(e)}",
                    }
                )
            )
            raise e


def deep_merge(dict1, dict2):
    """
    Recursively merges dict2 into dict1, prioritizing values from dict2.
    """
    result = dict1.copy()
    for key, value in dict2.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result
