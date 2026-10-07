from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion

COMMANDS = [
    {
        "name": "/provider",
        "description": "View or change the current LLM provider.",
    },
    {
        "name": "/model",
        "description": "View or change the current model.",
    },
]

class CommandCompleter(Completer):
    def get_completions(self, document, complete_event):
        text = document.text
        if text.startswith('/'):
            for cmd in COMMANDS:
                if cmd["name"].startswith(text):
                    yield Completion(
                        cmd["name"],
                        start_position=-len(text),
                        display=cmd["name"].ljust(12),
                        display_meta=cmd["description"]
                    )

def main():
    session = PromptSession(completer=CommandCompleter())
    while True:
        try:
            text = session.prompt('You: ')
            print('You entered:', text)
        except KeyboardInterrupt:
            break
        except EOFError:
            break

if __name__ == '__main__':
    main()
