"""
This file defines the Interpreter class.
It's the main file. `from interpreter import interpreter` will import an instance of this class.
"""
import json
import os
import threading
import time
from datetime import datetime

from ..terminal_interface.local_setup import local_setup
from ..terminal_interface.terminal_interface import terminal_interface
from ..terminal_interface.utils.display_markdown_message import display_markdown_message
from ..terminal_interface.utils.local_storage_path import get_storage_path
from ..terminal_interface.utils.oi_dir import oi_dir
from .computer.computer import Computer
from .default_system_message import default_system_message
from .llm.llm import Llm
from .respond import respond
from .utils.telemetry import send_telemetry
from .utils.truncate_output import truncate_output
from ..capture import take_screenshot


class OpenInterpreter:
    """
    This class (one instance is called an `interpreter`) is the "grand central station" of this project.

    Its responsibilities are to:

    1. Given some user input, prompt the language model.
    2. Parse the language models responses, converting them into LMC Messages.
    3. Send code to the computer.
    4. Parse the computer's response (which will already be LMC Messages).
    5. Send the computer's response back to the language model.
    ...

    The above process should repeat—going back and forth between the language model and the computer— until:

    6. Decide when the process is finished based on the language model's response.
    """

    def __init__(
        self,
        messages=None,
        offline=False,
        auto_run=False,
        verbose=False,
        debug=False,
        max_output=2800,
        safe_mode="off",
        shrink_images=True,
        loop=False,
        loop_message="""Proceed. You CAN run code on my machine. If the entire task I asked for is done, say exactly 'The task is done.' If you need some specific information (like username or password) say EXACTLY 'Please provide more information.' If it's impossible, say 'The task is impossible.' (If I haven't provided a task, say exactly 'Let me know what you'd like to do next.') Otherwise keep going.""",
        loop_breakers=[
            "The task is done.",
            "The task is impossible.",
            "Let me know what you'd like to do next.",
            "Please provide more information.",
        ],
        disable_telemetry=False,
        in_terminal_interface=False,
        conversation_history=True,
        conversation_filename=None,
        conversation_history_path=get_storage_path("conversations"),
        os=False,
        speak_messages=False,
        llm=None,
        system_message=default_system_message,
        custom_instructions="",
        user_message_template="{content}",
        always_apply_user_message_template=False,
        code_output_template="Code output: {content}\n\nWhat does this output mean / what's next (if anything, or are we done)?",
        empty_code_output_template="The code above was executed on my machine. It produced no text output. what's next (if anything, or are we done?)",
        code_output_sender="user",
        computer=None,
        sync_computer=False,
        import_computer_api=False,
        skills_path=None,
        import_skills=False,
        multi_line=True,
        contribute_conversation=False,
        plain_text_display=False,
    ):
        # State
        self.messages = [] if messages is None else messages
        self.responding = False
        self.last_messages_count = 0

        # Settings
        self.offline = offline
        self.auto_run = auto_run
        self.verbose = verbose
        self.debug = debug
        self.max_output = max_output
        self.safe_mode = safe_mode
        self.shrink_images = shrink_images
        self.disable_telemetry = disable_telemetry
        self.in_terminal_interface = in_terminal_interface
        self.multi_line = multi_line
        self.contribute_conversation = contribute_conversation
        self.plain_text_display = plain_text_display
        self.highlight_active_line = True  # additional setting to toggle active line highlighting. Defaults to True

        # Loop messages
        self.loop = loop
        self.loop_message = loop_message
        self.loop_breakers = loop_breakers

        # Conversation history
        self.conversation_history = conversation_history
        self.conversation_filename = conversation_filename
        self.conversation_history_path = conversation_history_path

        # OS control mode related attributes
        self.os = os
        self.speak_messages = speak_messages

        # Computer
        self.computer = Computer(self) if computer is None else computer
        self.sync_computer = sync_computer
        self.computer.import_computer_api = import_computer_api

        # Skills
        if skills_path:
            self.computer.skills.path = skills_path

        self.computer.import_skills = import_skills

        # LLM
        self.llm = Llm(self) if llm is None else llm

        # These are LLM related
        self.system_message = system_message
        self.custom_instructions = custom_instructions
        self.user_message_template = user_message_template
        self.always_apply_user_message_template = always_apply_user_message_template
        self.code_output_template = code_output_template
        self.empty_code_output_template = empty_code_output_template
        self.code_output_sender = code_output_sender

    def local_setup(self):
        """
        Opens a wizard that lets terminal users pick a local model.
        """
        self = local_setup(self)

    def wait(self):
        """
        Block until the current responding loop finishes and return any
        messages that were added during the current response cycle.

        This is a convenience for callers that want to synchronously wait for
        the interpreter to complete handling a message. The method polls the
        `self.responding` flag and returns the slice of `self.messages`
        produced since the last call (using `self.last_messages_count`).

        Returns:
            list: A list of messages appended during the last response.
        """
        while self.responding:
            time.sleep(0.2)
        # Return new messages (messages appended since last_messages_count)
        return self.messages[self.last_messages_count :]

    @property
    def anonymous_telemetry(self) -> bool:
        """
        Decide whether anonymous telemetry is enabled.

        The interpreter only sends anonymous telemetry when telemetry hasn't
        been explicitly disabled and the interpreter is not operating in
        offline mode. This property centralizes that logic for callers.
        """
        return not self.disable_telemetry and not self.offline

    @property
    def will_contribute(self):
        """
        Determine whether the interpreter should contribute conversations
        (e.g., upload or save telemetry/usage data).

        Contributing is disabled when any of the following override flags are
        set: offline mode, conversation_history disabled, or telemetry
        explicitly disabled. If `contribute_conversation` is True and no
        overrides are present, this property returns True.
        """
        overrides = (
            self.offline or not self.conversation_history or self.disable_telemetry
        )
        return self.contribute_conversation and not overrides

    def chat(self, message=None, display=True, stream=False, blocking=True):
        """
        Primary chat entrypoint.

        This method orchestrates sending a message (or messages) into the
        interpreter and returning the resulting messages. It supports three
        modes:
          - display=True with stream=True: returns a generator that yields
            rendering/display events (used by the terminal UI).
          - stream=False: consumes the streaming generator and returns the
            completed set of messages added during the call.
          - blocking=False: runs the chat operation in a background thread.

        Parameters:
            message (str|dict|list): The incoming message(s) to process.
            display (bool): Whether to render via the terminal interface.
            stream (bool): If True, return a generator that yields streaming
                chunks instead of materializing the full response.
            blocking (bool): If False, run in a background thread and return
                immediately.

        Returns:
            list|generator|None: Depending on the mode, returns the new
            messages list, a streaming generator, or None for background
            invocations.
        """
        try:
            self.responding = True
            if self.anonymous_telemetry:
                message_type = type(
                    message
                ).__name__  # Only send message type, no content
                send_telemetry(
                    "started_chat",
                    properties={
                        "in_terminal_interface": self.in_terminal_interface,
                        "message_type": message_type,
                        "os_mode": self.os,
                    },
                )

            if not blocking:
                chat_thread = threading.Thread(
                    target=self.chat, args=(message, display, stream, True)
                )  # True as in blocking = True
                chat_thread.start()
                return

            if stream:
                return self._streaming_chat(message=message, display=display)

            # If stream=False, *pull* from the stream.
            for _ in self._streaming_chat(message=message, display=display):
                pass

            # Return new messages
            self.responding = False
            return self.messages[self.last_messages_count :]

        except GeneratorExit:
            self.responding = False
            # It's fine
        except Exception as e:
            self.responding = False
            if self.anonymous_telemetry:
                message_type = type(message).__name__
                send_telemetry(
                    "errored",
                    properties={
                        "error": str(e),
                        "in_terminal_interface": self.in_terminal_interface,
                        "message_type": message_type,
                        "os_mode": self.os,
                    },
                )

            raise

    def _streaming_chat(self, message=None, display=True):
        """
        Internal streaming chat implementation.

        When `display=True` this delegates to `terminal_interface(...)` which
        handles rendering UI components, progress indicators, and user
        interactions. When `display=False` this method implements the
        non-UI streaming behavior that appends LMC message chunks to
        `self.messages` by pulling from `respond(self)`.
        """
        # If display/rendering is requested, hand control to the UI layer.
        if display:
            yield from terminal_interface(self, message)
            return

        # One-off message
        if message or message == "":
            ## We support multiple formats for the incoming message:
            # Dict (these are passed directly in)
            if isinstance(message, dict):
                if "role" not in message:
                    message["role"] = "user"
                self.messages.append(message)
            # String (we construct a user message dict)
            elif isinstance(message, str):
                self.messages.append(
                    {"role": "user", "type": "message", "content": message}
                )
            # List (this is like the OpenAI API)
            elif isinstance(message, list):
                self.messages = message

            # Now that the user's messages have been added, we set last_messages_count.
            # This way we will only return the messages after what they added.
            self.last_messages_count = len(self.messages)

            # DISABLED because I think we should just not transmit images to non-multimodal models?
            # REENABLE this when multimodal becomes more common:

            # Make sure we're using a model that can handle this
            # if not self.llm.supports_vision:
            #     for message in self.messages:
            #         if message["type"] == "image":
            #             raise Exception(
            #                 "Use a multimodal model and set `interpreter.llm.supports_vision` to True to handle image messages."
            #             )

            # This is where it all happens!
            yield from self._respond_and_store()

            # Save conversation if we've turned conversation_history on
            if self.conversation_history:
                # If it's the first message, set the conversation name
                if not self.conversation_filename:
                    first_few_words_list = self.messages[0]["content"][:25].split(" ")
                    if (
                        len(first_few_words_list) >= 2
                    ):  # for languages like English with blank between words
                        first_few_words = "_".join(first_few_words_list[:-1])
                    else:  # for languages like Chinese without blank between words
                        first_few_words = self.messages[0]["content"][:15]
                    for char in '<>:"/\\|?*!\n':  # Invalid characters for filenames
                        first_few_words = first_few_words.replace(char, "")

                    date = datetime.now().strftime("%B_%d_%Y_%H-%M-%S")
                    self.conversation_filename = (
                        "__".join([first_few_words, date]) + ".json"
                    )

                # Check if the directory exists, if not, create it
                if not os.path.exists(self.conversation_history_path):
                    os.makedirs(self.conversation_history_path)
                # Write or overwrite the file
                with open(
                    os.path.join(
                        self.conversation_history_path, self.conversation_filename
                    ),
                    "w",
                ) as f:
                    json.dump(self.messages, f)
            return

        raise Exception(
            "`interpreter.chat()` requires a display. Set `display=True` or pass a message into `interpreter.chat(message)`."
        )

    def _respond_and_store(self):
        """
        Consume the `respond(self)` generator, persist messages, and yield
        streaming flags/chunks for the UI layer.

        This implementation preserves the original behavior: grouping
        consecutive chunks into messages, emitting `start`/`end` flags,
        handling special chunk types (confirmation, active_line), and
        truncating long console outputs.
        """
        # Ensure we are not noisy by default during the respond/store loop.
        self.verbose = False

        def is_ephemeral(chunk):
            """Return True for chunks that should not be saved to conversation history.

            Ephemeral chunks include active_line markers and review chunks.
            """
            if "format" in chunk and chunk["format"] == "active_line":
                return True
            if chunk.get("type") == "review":
                return True
            return False

        last_flag_base = None

        try:
            for chunk in respond(self):
                # For async usage: stop if requested
                if hasattr(self, "stop_event") and self.stop_event.is_set():
                    print("Open Interpreter stopping.")
                    break

                # Skip empty content chunks
                if chunk.get("content", "") == "":
                    continue

                # If active_line is None, we finished running code.
                if (
                    chunk.get("format") == "active_line"
                    and chunk.get("content", None) is None
                ):
                    # If output wasn't yet produced, add an empty output message
                    if self.messages and self.messages[-1].get("role") != "computer":
                        self.messages.append(
                            {
                                "role": "computer",
                                "type": "console",
                                "format": "output",
                                "content": "",
                            }
                        )

                # Handle the special "confirmation" chunk, which neither triggers a flag nor creates a message
                if chunk.get("type") == "confirmation":
                    # Emit an end flag for the last message type, and reset last_flag_base
                    if last_flag_base:
                        yield {**last_flag_base, "end": True}
                        last_flag_base = None

                    if not self.auto_run:
                        yield chunk
                    continue

                # Determine whether this chunk continues the previous message
                if (
                    last_flag_base
                    and "role" in chunk
                    and "type" in chunk
                    and last_flag_base["role"] == chunk["role"]
                    and last_flag_base["type"] == chunk["type"]
                    and (
                        "format" not in last_flag_base
                        or ("format" in chunk and chunk.get("format") == last_flag_base.get("format"))
                    )
                ):
                    # Append content to the existing message unless ephemeral
                    if not is_ephemeral(chunk):
                        if any(
                            [
                                (prop in self.messages[-1])
                                and (self.messages[-1].get(prop) != chunk.get(prop))
                                for prop in ["role", "type", "format"]
                            ]
                        ):
                            self.messages.append(chunk)
                        else:
                            self.messages[-1]["content"] += chunk.get("content", "")
                else:
                    # New message boundary: yield end for previous and start for new
                    if last_flag_base:
                        yield {**last_flag_base, "end": True}

                    last_flag_base = {"role": chunk.get("role"), "type": chunk.get("type")}

                    # Don't add format to type: "console" flags, to accommodate active_line AND output formats
                    if "format" in chunk and chunk.get("type") != "console":
                        last_flag_base["format"] = chunk.get("format")

                    yield {**last_flag_base, "start": True}

                    # Add the chunk as a new message (unless ephemeral)
                    if not is_ephemeral(chunk):
                        # If the incoming chunk is a code message, capture the current
                        # screen and append an image message immediately BEFORE the
                        # code message. This records the UI state the model saw.
                        if chunk.get("type") == "code":
                            try:
                                screenshot_path = take_screenshot()
                                self.messages.append(
                                    {
                                        "role": chunk.get("role", "assistant"),
                                        "type": "image",
                                        "format": "path",
                                        "content": screenshot_path,
                                    }
                                )
                            except Exception as e:
                                if getattr(self, "debug", False):
                                    print(
                                        "Warning: failed to capture screenshot before code output:", e
                                    )

                        self.messages.append(chunk)

                # Yield the chunk itself for the streaming UI
                yield chunk

                # Truncate console outputs to a reasonable length to avoid OOM/UI issues
                if chunk.get("type") == "console" and chunk.get("format") == "output":
                    self.messages[-1]["content"] = truncate_output(
                        self.messages[-1].get("content", ""),
                        self.max_output,
                        add_scrollbars=self.computer.import_computer_api,
                    )

            # Yield a final end flag for the last open message
            if last_flag_base:
                yield {**last_flag_base, "end": True}
        except GeneratorExit:
            raise  # propagate generator exit

    def reset(self):
        """
        Reset interpreter runtime state.

        This method terminates any running language backends, clears the
        imported-computer-api flag, and wipes the in-memory message buffer.
        It does not modify persistent conversation files on disk.
        """
        # Terminate running language processes and reset import flags.
        self.computer.terminate()  # Terminates all languages
        self.computer._has_imported_computer_api = False  # Flag reset
        # Clear in-memory conversation state.
        self.messages = []
        self.last_messages_count = 0

    def display_message(self, markdown):
        """
        Display a markdown message to the user.

        In terminal-less or scripting contexts `plain_text_display` can be
        enabled to simply print markdown as plain text; otherwise the
        terminal UI helper `display_markdown_message` is used to render
        formatted output.
        """
        # This is used by profile start scripts and other programmatic flows.
        if self.plain_text_display:
            print(markdown)
        else:
            display_markdown_message(markdown)

    def get_oi_dir(self):
        """
        Return the project-local Open Interpreter directory helper.

        This convenience method is used by scripts and profiles that need
        to access the repo-specific storage directory (user-level config,
        caches, etc.). It simply returns the `oi_dir` helper imported from
        the terminal_interface utilities.
        """
        return oi_dir
