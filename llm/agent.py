# this abstraction is not useful as i wont add anything other than openai
from abc import ABC, abstractmethod


class Agent(ABC):
    @abstractmethod
    def get_response(self, prompt: str, context: str, model: str, conversation_id: str, tools=None):
        """Answer prompt, running any tool calls the model makes first.

        tools is a ToolRegistry or None. Returns an AgentResult carrying the
        reply and the token usage summed across every round of the turn.
        """

        pass
