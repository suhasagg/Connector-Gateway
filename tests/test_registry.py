from app.registry import ToolRegistry
def test_seeded_connectors():
    kinds = {x.connector.value for x in ToolRegistry().list()}
    assert {"mcp","rest","graphql","cli"} <= kinds
