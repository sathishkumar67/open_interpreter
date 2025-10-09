import os
from autogen import AssistantAgent, UserProxyAgent

# Azure OpenAI configuration
azure_config = {
    "model": "gpt-4.1",  # use deployment name, not model name
    "api_key": os.getenv("AZURE_OPENAI_API_KEY"),
    "api_type": "azure",
    "base_url": os.getenv("AZURE_OPENAI_ENDPOINT"),
    "api_version": os.getenv("AZURE_OPENAI_API_VERSION"),
}

# Create an assistant agent using Azure
# assistant = AssistantAgent(
#     name="azure_agent",
#     llm_config=azure_config,
# )

# # Create a user proxy agent
# user = UserProxyAgent(name="user", code_execution_config={"use_docker": False})

# # Start a conversation
# user.initiate_chat(assistant, message="Write a Python function that sorts a list of numbers.")

from autogen import AssistantAgent, UserProxyAgent, GroupChat, GroupChatManager

# Create specialized agents
planner = AssistantAgent(
    name="Planner",
    system_message="You are a planning assistant. Create step-by-step plans for complex tasks.",
    llm_config=azure_config
)

coder = AssistantAgent(
    name="Coder", 
    system_message="You are a Python coding expert. Write and debug code based on plans.",
    llm_config= azure_config
)

executor = UserProxyAgent(
    name="Executor",
    system_message="You execute code and report results.",
    human_input_mode="NEVER",
    code_execution_config={"use_docker": False}
)

# Create and manage group chat
groupchat = GroupChat(
    agents=[planner, coder, executor], 
    messages=[], 
    max_round=6
)

manager = GroupChatManager(groupchat=groupchat, llm_config=azure_config)

# Start the collaborative task
executor.initiate_chat(
    manager,
    message="create a python script to print hello world"
)