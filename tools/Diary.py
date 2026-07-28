# creates diary logs
from tool import Tool


class Diary(Tool):
    def getToolInformation(self):
        return """Diary tool for logging and reading diary entries.
        Methods:
        - read_diary(): Reads the diary entries from a file.
        - write_diary(entry): Writes a new diary entry to the file. Additive.
        """

    def read_diary(self):
        with open("diary.txt", "r") as f:
            return f.read()

    def write_diary(self, entry):
        with open("diary.txt", "a") as f:
            f.write(entry + "\n")
