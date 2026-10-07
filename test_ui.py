from fiat.ui import interactive_select
print("Before")
result = interactive_select("Choose provider", ["Gemini", "OpenAI"])
print("Result:", result)
print("After")
