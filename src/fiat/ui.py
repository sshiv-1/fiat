import questionary
from typing import List, Optional

def interactive_select(title: str, options: List[str]) -> Optional[str]:
    if not options:
        return None
    
    # We can customize the style if needed
    custom_style = questionary.Style([
        ('qmark', 'fg:#673ab7 bold'),
        ('question', 'bold'),
        ('answer', 'fg:#f44336 bold'),
        ('pointer', 'fg:#673ab7 bold'),
        ('highlighted', 'fg:#673ab7 bold'),
        ('selected', 'fg:#cc5454'),
        ('separator', 'fg:#cc5454'),
        ('instruction', ''),
        ('text', ''),
        ('disabled', 'fg:#858585 italic')
    ])

    try:
        result = questionary.select(
            title,
            choices=options,
            instruction="(↑/↓ Navigate, Enter Select, Esc Cancel)",
            style=custom_style
        ).ask()
        return result
    except KeyboardInterrupt:
        return None
