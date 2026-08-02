from dataclasses import dataclass
import json
from llm._openai import Openai, get_conversation_id
from tools import Diary, GoogleTasks
import logging
from pathlib import Path

TOOL_LIST = [{"toolName": "GoogleTasks", "class": GoogleTasks}, {"toolName": "Diary", "class": Diary}]

BASE_DIR = Path(__file__).resolve().parent
HANDLES_PATH = BASE_DIR / "handles.json"
CONVERSATIONS_PATH = BASE_DIR / "conversations.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@dataclass
class Handle:
    description: str
    agent_name: str
    telegram_chat_id: int
    model: str
    context_path: str
    conversation_id: str  # this can be optional

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

        context = self._build_context_from_md(Path(self.context_path))  # should add tools to here as well later
        logging.debug(f"{self.agent_name} GIVEN CONTEXT: {context}")
        response = agent.get_response(text, context=context, model=self.model, conversation_id=self.conversation_id)  # what to do for tool loop calls?
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


def loadHandle(handleName: str = "default", conversation_id: str = None) -> Handle:
    try:
        with open(HANDLES_PATH, "r", encoding="utf-8") as f:
            handles = json.load(f)
    except FileNotFoundError:
        raise ValueError(f"handles.json file not found at {HANDLES_PATH}.")

    for handle in handles:
        if handle.get("handleName") == handleName:

            return Handle(
                description=handle.get("description"),
                agent_name=handle.get("agentName"),
                telegram_chat_id=handle.get("telegramChatId"),
                model=handle.get("model"),
                context_path=handle.get("contextPath"),
                conversation_id=conversation_id or handle.get("conversationId"),
            )

    raise ValueError(f"Handle with name {handleName} not found.")


def conversationIdFor(handleName: str, chat_id: int) -> str:
    """Return a stable OpenAI conversation id per (handle, telegram chat).

    Without this every webhook call would start a fresh conversation, so the
    agent would have no memory between messages.
    """

    key = f"{handleName}:{chat_id}"

    try:
        with open(CONVERSATIONS_PATH, "r", encoding="utf-8") as f:
            conversations = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        conversations = {}

    if key not in conversations:
        conversations[key] = get_conversation_id()

        with open(CONVERSATIONS_PATH, "w", encoding="utf-8") as f:
            json.dump(conversations, f, indent=4)

        logging.info("Started conversation %s for %s", conversations[key], key)

    return conversations[key]


if __name__ == "__main__":
    convo_id = get_conversation_id()
    handle = loadHandle(conversation_id=convo_id)

    while True:
        text = input(f"\nenter text \n")
        resp = handle.sendMessageAgent(text=text, channelType="cli")
        # print(resp.model_dump_json(indent=4))
