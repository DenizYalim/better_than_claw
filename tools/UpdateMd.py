from .tool import Tool


## TODO much
class UpdateMd(Tool):
    def getToolInformation(self) -> dict:  # str ?
        return "Tool Name: UpdateMd \n Description: Updates the context by reading all markdown files in the specified directory.\n"

    def update(self, context_path: str) -> str:
        pass
