from abc import ABC, abstractmethod


class Tool(ABC):
    @abstractmethod
    def getToolInformation(self) -> dict:  # str ?
        """Return information about the tool."""
        pass
