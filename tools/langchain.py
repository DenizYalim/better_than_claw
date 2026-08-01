# from langchain.agents import create_agent


def get_weather(city: str) -> str:
    """Return weather information for a city."""
    return f"It is sunny in {city}."


agent = create_agent(
    model="openai:gpt-5.4",
    tools=[get_weather],
    system_prompt="You are a helpful assistant.",
)

result = agent.invoke({"messages": [{"role": "user", "content": "What is the weather in Warsaw?"}]})

print(result["messages"][-1].content)
