from .agent import Agent
from openai import OpenAI
import dotenv
import os

dotenv.load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class Openai(Agent):
    def get_response(self, prompt: str, context: str, model: str) -> str:
        return client.responses.create(
            model=model,
            # reasoning={"effort": "low"},
            # instructions=context,
            input=prompt,
        )
