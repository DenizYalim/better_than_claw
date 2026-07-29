# this abstraction is not useful as i wont add anything other than openai
from abc import ABC, abstractmethod


class Agent(ABC):
    @abstractmethod
    def get_response(self, prompt: str, context: str, model: str) -> str:
        """ """

        pass
