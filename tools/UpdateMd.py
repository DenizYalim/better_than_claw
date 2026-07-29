from .tool import Tool


## TODO much
class UpdateMd(Tool):
    def getToolInformation(self) -> dict:  # str ?
        return "Tool Name: UpdateMd \n Description: Updates the context by reading all markdown files in the specified directory.\n"

    def update(self, context_path: str) -> str:
        """
        Updates the context by reading all markdown files in the specified directory.
        """
        from pathlib import Path

        context_path = Path(context_path)
        if not context_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {context_path}")

        markdown_files = sorted(context_path.glob("*.md"))

        return "\n\n".join(file_path.read_text(encoding="utf-8") for file_path in markdown_files)
