import dataclasses
from telegram import send_message
from agents._openai import Openai
from tools import Diary, GoogleTasks


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

    def sendMessage2Agent(self, text: str):
        """
        gelen prompt + context + kişilik + memory -> agent -> response|tool calls -> response via telegram
        """

        agent = Openai()  # yea so much for abstraction
        response = agent.get_response(text, self.description, self.model)  # what to do for tool loop calls?

        send_message(self.telegramChatId, response)

    def updatePersona(self):
        pass

    def getToolList(self):
        pass

    def callTool(self, toolName: str, toolArgs: dict):
        pass


toolList = [{"toolName": "GoogleTasks", "class": GoogleTasks}, {"toolName": "Diary", "class": Diary}]
