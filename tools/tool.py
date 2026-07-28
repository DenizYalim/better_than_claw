import abc


@abc
class Tool(abc.ABC):
    @abc.abstractmethod
    def getToolInformation(self) -> dict:  # str ?
        """Return information about the tool."""
        pass
