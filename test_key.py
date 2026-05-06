import anthropic

client = anthropic.Anthropic(
    api_key="YOUR_ANTHROPIC_API_KEY_HERE"
)

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=20,
    messages=[
        {"role": "user", "content": "Say hello"}
    ]
)

print(response.content[0].text)
