from dataclasses import dataclass
import telegram
from llm._openai import Openai, get_conversation_id
from tools import Diary, GoogleTasks
import logging
from pathlib import Path

TOOL_LIST = [{"toolName": "GoogleTasks", "class": GoogleTasks}, {"toolName": "Diary", "class": Diary}]

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

    def sendMessageAgent(self, channelType: str, text: str):  # TODO add chat id later
        """
        gelen prompt + context + kişilik + memory -> agent -> response|tool calls -> response via telegram
        """

        agent = Openai()  # yea so much for abstraction

        context = self._build_context_from_md(Path(self.context_path))  # should add tools to here as well later
        logging.debug(f"{self.agent_name} GIVEN CONTEXT: {context}")
        response = agent.get_response(text, context=context, model=self.model, conversation_id=self.conversation_id)  # what to do for tool loop calls?
        logging.debug(f"{self.agent_name} RESPONSE: {response}")
        response_text = response.output_text.strip()

        if channelType == "cli":
            print(f"R: {response_text}")
        elif channelType == "telegram":
            telegram.send_message(self.telegram_chat_id, response_text)  ## TODO

        return response

    def updatePersona(self):
        pass

    def getToolList(self):
        pass

    def callTool(self, toolName: str, toolArgs: dict):
        pass


def loadHandle(handleName: str = "default", conversation_id: str = None) -> Handle:
    import json

    try:
        with open("handles.json", "r") as f:
            handles = json.load(f)
    except FileNotFoundError:
        raise ValueError("handles.json file not found.")

    for handle in handles:
        if handle.get("handleName") == handleName:

            return Handle(
                description=handle.get("description"),
                agent_name=handle.get("agentName"),
                telegram_chat_id=handle.get("telegramChatId"),
                model=handle.get("model"),
                context_path=handle.get("contextPath"),
                conversation_id=conversation_id,  # handle.get("conversationId"), # hm
            )

    raise ValueError(f"Handle with name {handleName} not found.")


if __name__ == "__main__":
    convo_id = get_conversation_id()
    handle = loadHandle(conversation_id=convo_id)

    while True:
        text = input(f"\nenter text \n")
        resp = handle.sendMessageAgent(text=text, channelType="cli")
        # print(resp.model_dump_json(indent=4))
