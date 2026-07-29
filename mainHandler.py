import dataclasses
import telegram
from agents._openai import Openai
from tools import Diary, GoogleTasks
import logging


@dataclasses.dataclass
class Handle:
    description: str
    agentName: str
    telegramChatId: int
    model: str

    def __init__(self, description: str, agentName: str, telegramChatId: int, model: str):
        self.description = description
        self.agentName = agentName
        self.telegramChatId = telegramChatId
        self.model = model

    def sendMessageAgent(self, channelType: str, text: str):  # TODO add chat id later
        """
        gelen prompt + context + kişilik + memory -> agent -> response|tool calls -> response via telegram
        """

        agent = Openai()  # yea so much for abstraction
        response = agent.get_response(text, self.description, self.model)  # what to do for tool loop calls?
        logging.info(f"{self.agentName} RESPONSE: {response}")

        if channelType == "cli":
            print(f"{self.agentName} RESPONSE: {response}")
        elif channelType == "telegram":
            telegram.send_message(self.telegramChatId, response)  ## TODO

        return response

    def updatePersona(self):
        pass

    def getToolList(self):
        pass

    def callTool(self, toolName: str, toolArgs: dict):
        pass


toolList = [{"toolName": "GoogleTasks", "class": GoogleTasks}, {"toolName": "Diary", "class": Diary}]


def loadHandle(handleName: str = "default") -> Handle:
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
                agentName=handle.get("agentName"),
                telegramChatId=handle.get("telegramChatId"),
                model=handle.get("model"),
            )

    raise ValueError(f"Handle with name {handleName} not found.")


if __name__ == "__main__":
    handle = loadHandle()

    while True:
        text = input(f"\nenter text \n")
        resp = handle.sendMessageAgent(text=text, channelType="cli")
        print(resp.model_dump_json(indent=4))
