from dataclasses import dataclass, field
import json
from llm._openai import Openai, get_conversation_id
from tools import build_registry
from tools._store import read_json as _loadStore, update_json as _updateStore
import logging
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
HANDLES_PATH = BASE_DIR / "handles.json"
CONVERSATIONS_PATH = BASE_DIR / "conversations.json"
ACTIVE_HANDLES_PATH = BASE_DIR / "active_handles.json"

DEFAULT_HANDLE = "default"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@dataclass
class Handle:
    description: str
    agent_name: str
    telegram_chat_id: int
    model: str
    context_path: str
    conversation_id: str  # this can be optional
    tool_names: list[str] = field(default_factory=list)
    chat_id: int | None = None

    def _build_context_from_md(self, context_path: Path) -> str:
        if not context_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {context_path}")

        markdown_files = sorted(context_path.glob("*.md"))

        return "\n\n".join(file_path.read_text(encoding="utf-8") for file_path in markdown_files)

    def sendMessageAgent(self, channelType: str, text: str) -> str:
        """
        gelen prompt + context + kişilik + memory -> agent -> response|tool calls -> response text

        Returns the reply text. Delivery is the caller's job: the webhook knows
        the real chat_id, this class does not.
        """

        agent = Openai()  # yea so much for abstraction

        context = self._build_context_from_md(Path(self.context_path))
        logging.debug(f"{self.agent_name} GIVEN CONTEXT: {context}")

        # Tools are bound to a chat and to this handle's own context directory,
        # never chosen by the model: goal tools can only touch the conversation
        # they were called from, and context tools can only rewrite this agent's
        # own markdown.
        tools = build_registry(
            self.tool_names,
            self.chat_id or self.telegram_chat_id,
            context_path=self.context_path,
        )

        response = agent.get_response(
            text,
            context=context,
            model=self.model,
            conversation_id=self.conversation_id,
            tools=tools,
        )
        logging.debug(f"{self.agent_name} RESPONSE: {response}")
        response_text = response.output_text.strip()

        if channelType == "cli":
            print(f"R: {response_text}")

        return response_text

    def updatePersona(self):
        pass

    def getToolList(self):
        pass

    def callTool(self, toolName: str, toolArgs: dict):
        pass


def loadHandle(handleName: str = "default", conversation_id: str = None, chat_id: int = None) -> Handle:
    for handle in loadHandleConfigs():
        if handle.get("handleName") == handleName:

            return Handle(
                description=handle.get("description"),
                agent_name=handle.get("agentName"),
                telegram_chat_id=handle.get("telegramChatId"),
                model=handle.get("model"),
                context_path=handle.get("contextPath"),
                conversation_id=conversation_id or handle.get("conversationId"),
                tool_names=handle.get("tools") or [],
                chat_id=chat_id,
            )

    raise ValueError(f"Handle with name {handleName} not found.")


def loadHandleConfigs() -> list[dict]:
    try:
        with open(HANDLES_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError(f"handles.json file not found at {HANDLES_PATH}.")


def handleNames() -> list[str]:
    return [handle.get("handleName") for handle in loadHandleConfigs()]


def activeHandleFor(chat_id: int) -> str:
    """Which agent this chat is currently talking to.

    Falls back to the default if the stored handle has since been renamed or
    removed from handles.json. Without this the chat is stuck: every message
    raises "Handle not found", and the user only sees a generic failure.
    """

    name = _loadStore(ACTIVE_HANDLES_PATH).get(str(chat_id), DEFAULT_HANDLE)

    if name not in handleNames():
        logging.warning(
            "Chat %s points at unknown handle %r; falling back to %s",
            chat_id,
            name,
            DEFAULT_HANDLE,
        )
        return DEFAULT_HANDLE

    return name


def setActiveHandle(chat_id: int, handleName: str) -> None:
    if handleName not in handleNames():
        raise ValueError(f"No handle named {handleName}")

    _updateStore(ACTIVE_HANDLES_PATH, lambda data: data.__setitem__(str(chat_id), handleName))

    logging.info("Chat %s switched to handle %s", chat_id, handleName)


def conversationIdFor(handleName: str, chat_id: int) -> str:
    """Return a stable OpenAI conversation id per (handle, telegram chat).

    Without this every message would start a fresh conversation, so the
    agent would have no memory between messages.
    """

    key = f"{handleName}:{chat_id}"
    existing = _loadStore(CONVERSATIONS_PATH).get(key)

    if existing:
        return existing

    # Create the conversation outside the lock: it is a network call, and
    # holding the lock across it would stall every other write for its
    # duration. The re-check inside the lock settles any race.
    fresh_id = get_conversation_id()

    def mutate(conversations: dict) -> str:
        if key not in conversations:
            conversations[key] = fresh_id
            logging.info("Started conversation %s for %s", fresh_id, key)
        return conversations[key]

    return _updateStore(CONVERSATIONS_PATH, mutate)


def resetConversation(handleName: str, chat_id: int) -> str | None:
    """Forget one chat's history. Returns the dropped id, or None if there
    was nothing to drop.

    The OpenAI conversation object itself is left alone rather than deleted,
    so a reset stays recoverable: the orphaned id goes to the log, and the
    transcript can still be read back through the API.
    """

    key = f"{handleName}:{chat_id}"

    previous = _updateStore(CONVERSATIONS_PATH, lambda conversations: conversations.pop(key, None))

    if previous is None:
        return None

    logging.info("Reset %s. Orphaned conversation left on OpenAI: %s", key, previous)

    return previous


if __name__ == "__main__":
    convo_id = get_conversation_id()
    handle = loadHandle(conversation_id=convo_id)

    while True:
        text = input(f"\nenter text \n")
        resp = handle.sendMessageAgent(text=text, channelType="cli")
        # print(resp.model_dump_json(indent=4))
