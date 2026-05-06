''' import anthropic

client = anthropic.Anthropic(
    api_key="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"
)

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=20,
    messages=[
        {"role": "user", "content": "Say hello"}
    ]
)

print(response.content[0].text)'''
