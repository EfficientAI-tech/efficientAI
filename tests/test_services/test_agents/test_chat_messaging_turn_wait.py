from app.services.agents.chat_messaging_turn_wait import (
    _phone_lookup_variants,
    abandon_messaging_sms_turn,
    complete_messaging_inbound_routed,
    complete_messaging_sms_turn,
    register_messaging_sms_turn,
)


def test_phone_lookup_variants_india():
    assert "917051228092" in _phone_lookup_variants("+917051228092")
    assert "7051228092" in _phone_lookup_variants("+917051228092")


def test_register_replaces_stale_lock(monkeypatch):
    import app.services.agents.chat_messaging_turn_wait as mod

    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, val, ex=None, nx=False):
            if nx and key in store:
                return False
            store[key] = val
            return True

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

    monkeypatch.setattr(mod, "_redis", lambda: FakeRedis())
    first = register_messaging_sms_turn(
        agent_id="a1",
        twilio_from="1395406326980468",
        messaging_recipient="917051228092",
    )
    assert first
    second = register_messaging_sms_turn(
        agent_id="a1",
        twilio_from="1395406326980468",
        messaging_recipient="917051228092",
        replace_stale_lock=True,
    )
    assert second
    assert second != first


def test_complete_turn_matches_national_from_format(monkeypatch):
    import app.services.agents.chat_messaging_turn_wait as mod

    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, val, ex=None, nx=False):
            if nx and key in store:
                return False
            store[key] = val
            return True

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def rpush(self, key, val):
            store.setdefault(key, val)

        def expire(self, key, ttl):
            pass

    monkeypatch.setattr(mod, "_redis", lambda: FakeRedis())
    turn_id = register_messaging_sms_turn(
        agent_id="agent-1",
        twilio_from="1395406326980468",
        messaging_recipient="917051228092",
    )
    assert turn_id
    ok = complete_messaging_sms_turn(
        agent_id="agent-1",
        line_to="1395406326980468",
        reply_from="7051228092",
        body="hey",
    )
    assert ok
    assert store.get(f"chat:messaging:reply:{turn_id}") == "hey"


def test_routed_complete_without_db_agent(monkeypatch):
    import app.services.agents.chat_messaging_turn_wait as mod

    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, val, ex=None, nx=False):
            if nx and key in store:
                return False
            store[key] = val
            return True

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def rpush(self, key, val):
            store.setdefault(key, val)

        def expire(self, key, ttl):
            pass

    monkeypatch.setattr(mod, "_redis", lambda: FakeRedis())
    turn_id = register_messaging_sms_turn(
        agent_id="agent-1",
        twilio_from="1395406326980468",
        messaging_recipient="917051228092",
    )
    ok = complete_messaging_inbound_routed(
        line_to="1395406326980468",
        reply_from="917051228092",
        body="hey i need help",
    )
    assert ok
    assert store.get(f"chat:messaging:reply:{turn_id}") == "hey i need help"
