"""Production and test agents keep independent knowledge base lists."""

from app.models.database import Agent, KnowledgeBase
from app.services.agents.agent_serializers import agent_to_response
from app.services.knowledge_bases.agent_links import (
    KB_ROLE_TEST,
    get_agent_knowledge_base_ids,
    replace_agent_knowledge_bases,
)


def test_roles_are_replaced_independently(db_session, seed_org, default_workspace):
    org_id, ws_id = seed_org.id, default_workspace.id
    agent = Agent(
        organization_id=org_id,
        workspace_id=ws_id,
        agent_id="161803",
        name="Support Bot",
        call_type="inbound",
        call_medium="chat",
    )
    policies = KnowledgeBase(organization_id=org_id, workspace_id=ws_id, name="Policies")
    customer = KnowledgeBase(organization_id=org_id, workspace_id=ws_id, name="Customer facts")
    db_session.add_all([agent, policies, customer])
    db_session.flush()

    def _replace(ids, role="production"):
        replace_agent_knowledge_bases(
            db_session,
            agent=agent,
            organization_id=org_id,
            workspace_id=ws_id,
            knowledge_base_ids=ids,
            role=role,
        )
        db_session.flush()

    _replace([policies.id])
    _replace([customer.id, policies.id], role=KB_ROLE_TEST)
    _replace([], role=KB_ROLE_TEST)
    _replace([customer.id], role=KB_ROLE_TEST)

    assert get_agent_knowledge_base_ids(db_session, agent_id=agent.id) == [policies.id]
    assert get_agent_knowledge_base_ids(db_session, agent_id=agent.id, role=KB_ROLE_TEST) == [
        customer.id
    ]
    response = agent_to_response(db_session, agent)
    assert response.knowledge_base_ids == [policies.id]
    assert response.test_knowledge_base_ids == [customer.id]
