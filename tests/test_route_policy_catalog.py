from app.main import app
from app.security.policy import PERMISSIONS
from app.security.route_policy import BUSINESS_ROUTE_POLICIES, BranchBinding


def _business_routes():
    return {
        (method, route.path)
        for route in app.routes
        if route.path.startswith("/api/v1/")
        and not route.path.startswith("/api/v1/security/")
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }


def test_every_business_route_has_exactly_one_security_policy():
    assert set(BUSINESS_ROUTE_POLICIES) == _business_routes()


def test_route_catalog_contains_only_known_actions_and_explicit_branch_binding():
    for route, policy in BUSINESS_ROUTE_POLICIES.items():
        assert policy.actions
        assert len(policy.actions) == len(set(policy.actions))
        assert all(action in PERMISSIONS for action in policy.actions), route
        assert isinstance(policy.branch_binding, BranchBinding)


def test_every_browser_supplied_actor_field_is_tracked_for_removal():
    tracked_fields = {
        field
        for policy in BUSINESS_ROUTE_POLICIES.values()
        for field in policy.untrusted_actor_fields
    }
    assert tracked_fields == {
        "actualizada_por",
        "actualizado_por",
        "autorizada_por",
        "cancelado_por",
        "creada_por",
        "creado_por",
        "descartado_por",
        "eliminado_por",
        "importado_por",
        "rechazada_por",
        "registrada_por",
        "revisada_por",
        "rol_creador",
    }
