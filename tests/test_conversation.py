import pytest
from orchestrator.conversation import ConversationStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "test.db")
    return ConversationStore(db_url=f"sqlite:///{db_path}")


def test_create_conversation(store):
    conv = store.create_conversation()
    assert conv.id is not None
    assert conv.created_at is not None


def test_add_and_get_messages(store):
    conv = store.create_conversation()
    store.add_message(conv.id, role="user", content="Hello")
    store.add_message(conv.id, role="assistant", content="Hi there")

    messages = store.get_messages(conv.id)
    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[0].content == "Hello"
    assert messages[1].role == "assistant"


def test_get_messages_unknown_conversation(store):
    messages = store.get_messages("nonexistent-id")
    assert messages == []


def test_get_conversation(store):
    conv = store.create_conversation()
    fetched = store.get_conversation(conv.id)
    assert fetched.id == conv.id


def test_get_conversation_unknown(store):
    result = store.get_conversation("nonexistent-id")
    assert result is None
