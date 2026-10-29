"""Acceptance tests for the multi-user / multi-device design.

Covers the stdlib-testable core: migrations, bootstrap-once, admin user
lifecycle, device registration/credentials/access, idempotent ingestion,
spoof rejection, stream ACL and the server-as-device path.  Run with::

    python -m unittest vira.tests.test_multi_device -v

bcrypt/loguru are replaced by light stubs only when they are not installed.
"""
import asyncio
import json
import sys
import tempfile
import types
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

try:  # pragma: no cover
    import bcrypt  # noqa: F401
except ImportError:  # pragma: no cover
    fake = types.ModuleType("bcrypt")
    fake.gensalt = lambda: b"s"
    fake.hashpw = lambda pw, salt: b"h:" + pw
    fake.checkpw = lambda pw, h: h == b"h:" + pw
    sys.modules["bcrypt"] = fake
try:  # pragma: no cover
    import loguru  # noqa: F401
except ImportError:  # pragma: no cover
    fake = types.ModuleType("loguru")

    class _L:
        def __getattr__(self, name):
            return lambda *a, **k: None

    fake.logger = _L()
    sys.modules["loguru"] = fake

from vira import errors
from vira.auth import auth, database
from vira.auth.admin import UserAdminService
from vira.devices import (DeviceService, EventIngestionService, EventPolicy,
                          LocalDeviceDispatcher, LocalDeviceManager)
from vira.devices import store
from vira.devices.policy import EventPolicy as Policy
from vira.devices.ratelimit import RateLimiter
from vira.devices.service import can_transition
from vira.devices.visibility import AccessCache, authorize_event


def run(coro):
    return asyncio.run(coro)


def principal_for(user_id):
    user = database.get_user_by_id(user_id)
    return auth.UserPrincipal(user_id=user_id, username=user["username"],
                              roles=(user["role"],), session_id="s", public_id=user["public_id"])


def ev(event_type="sensor.hardware.state", payload=None, **over):
    item = {
        "event_id": str(uuid.uuid4()), "type": event_type, "schema_version": 1,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source_component": "hardware_sensor", "device_sequence": 1,
        "payload": payload if payload is not None else {"cpu": {"usage_percent": 5}},
    }
    item.update(over)
    return item


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.tmp.name) / "t.sqlite3"
        database.init_db()
        auth.create_admin("root", "rootpass1")
        self.admin = principal_for(1)
        self.users = UserAdminService()
        self.policy = Policy()
        self.devs = DeviceService(self.policy)
        self.ing = EventIngestionService(self.policy)

    def tearDown(self):
        self.tmp.cleanup()

    def new_user(self, name, role="user"):
        created = self.users.create_user(self.admin, name, role, "password1")
        uid = database.get_user_by_public_id(created["user_id"])["id"]
        return principal_for(uid)

    def active_device(self, owner, name="dev"):
        reg = self.devs.register_device(owner, name, "linux", "laptop", capabilities=["hardware_state"])
        dp = self.devs.authenticate_credential(reg["credential"]["token"])
        self.devs.heartbeat(dp, reg["device_id"])
        return reg, self.devs.authenticate_credential(reg["credential"]["token"])


class IdentityTests(Base):
    def test_migrations_idempotent_and_public_id(self):
        database.init_db()
        user = database.get_user_by_id(1)
        self.assertTrue(uuid.UUID(user["public_id"]))
        self.assertEqual(user["status"], "active")

    def test_bootstrap_only_once(self):
        with self.assertRaises(RuntimeError):
            auth.create_admin("second", "secondpass")

    def test_admin_only_user_management(self):
        user = self.new_user("alice")
        with self.assertRaises(errors.Forbidden):
            self.users.create_user(user, "bob", "user", "password1")
        with self.assertRaises(errors.Forbidden):
            self.users.list_users(user)

    def test_duplicate_username_and_validation(self):
        self.new_user("alice")
        with self.assertRaises(errors.Conflict):
            self.users.create_user(self.admin, "alice", "user", "password1")
        with self.assertRaises(errors.ValidationFailed):
            self.users.create_user(self.admin, "x", "user", "password1")
        with self.assertRaises(errors.ValidationFailed):
            self.users.create_user(self.admin, "carol", "user", "short")

    def test_temp_password_returned_once_and_not_in_audit(self):
        created = self.users.create_user(self.admin, "dave", "user")
        self.assertIn("temporary_password", created)
        self.assertTrue(auth.authenticate_user_record("dave", created["temporary_password"]))
        blob = json.dumps(database.list_audit(500))
        self.assertNotIn(created["temporary_password"], blob)
        self.assertNotIn(created["recovery_code"], blob)

    def test_last_admin_protection(self):
        root = self.admin.__class__  # noqa
        with self.assertRaises(errors.Conflict):
            self.users.update_user(self.admin, self.admin.public_id, status="disabled")
        with self.assertRaises(errors.Conflict):
            self.users.update_user(self.admin, self.admin.public_id, role="user")
        with self.assertRaises(errors.Conflict):
            self.users.delete_user(self.admin, self.admin.public_id)
        other = self.users.create_user(self.admin, "admin2", "admin", "password1")
        self.users.update_user(self.admin, self.admin.public_id, role="user")  # allowed now
        self.assertEqual(other["role"], "admin")

    def test_disable_revokes_sessions_and_blocks_login(self):
        alice = self.new_user("alice")
        sid = auth.create_authenticated_session(database.get_user_by_id(alice.user_id), 3600)
        self.assertIsNotNone(auth.resolve_principal(sid))
        self.users.update_user(self.admin, alice.public_id, status="disabled")
        self.assertIsNone(auth.resolve_principal(sid))
        self.assertIsNone(auth.authenticate_user_record("alice", "password1"))

    def test_delete_is_soft_and_revokes_grants(self):
        alice = self.new_user("alice")
        reg, _ = self.active_device(alice)
        self.users.delete_user(self.admin, alice.public_id)
        user = database.get_user_by_id(alice.user_id)
        self.assertEqual(user["status"], "deleted")
        self.assertIsNone(store.get_access(alice.user_id, reg["device_id"]))
        self.assertIsNone(auth.authenticate_user_record("alice", "password1"))

    def test_change_password_revokes_sessions(self):
        alice = self.new_user("alice")
        sid = auth.create_authenticated_session(database.get_user_by_id(alice.user_id), 3600)
        self.assertFalse(auth.change_password(alice.user_id, "wrong", "newpassword1"))
        self.assertTrue(auth.change_password(alice.user_id, "password1", "newpassword1"))
        self.assertIsNone(auth.resolve_principal(sid))

    def test_cursor_pagination(self):
        for n in ("user1", "user2", "user3"):
            self.new_user(n)
        page1 = self.users.list_users(self.admin, limit=2)
        self.assertEqual(len(page1["users"]), 2)
        page2 = self.users.list_users(self.admin, limit=2, cursor=page1["next_cursor"])
        self.assertEqual(len(page2["users"]), 2)
        self.assertIsNone(page2["next_cursor"])


class DeviceTests(Base):
    def test_register_issues_credential_once_and_stores_hash_only(self):
        alice = self.new_user("alice")
        reg = self.devs.register_device(alice, "Phone", "android", "phone")
        token = reg["credential"]["token"]
        self.assertEqual(reg["status"], "pending")
        self.assertEqual(reg["access_role"], "owner")
        with database.get_connection() as conn:
            dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM device_credentials")])
        self.assertNotIn(token, dump)
        self.assertNotIn("token", self.devs.get_device(alice, reg["device_id"]).get("credential", {}))
        self.assertNotIn(token, json.dumps(self.devs.list_devices(alice)))

    def test_validation_of_enums(self):
        alice = self.new_user("alice")
        with self.assertRaises(errors.ValidationFailed):
            self.devs.register_device(alice, "x", "palmos", "phone")
        with self.assertRaises(errors.ValidationFailed):
            self.devs.register_device(alice, "x", "linux", "phone", capabilities=["Bad Cap!"])

    def test_multiple_devices_per_user_and_isolation(self):
        alice, bob = self.new_user("alice"), self.new_user("bob")
        d1, _ = self.active_device(alice, "a1")
        d2, _ = self.active_device(alice, "a2")
        self.assertEqual(len(self.devs.list_devices(alice)["devices"]), 2)
        self.assertEqual(self.devs.list_devices(bob)["devices"], [])
        with self.assertRaises(errors.NotFound):  # concealed, not 403
            self.devs.get_device(bob, d1["device_id"])
        with self.assertRaises(errors.NotFound):
            self.devs.revoke_device(bob, d1["device_id"])

    def test_shared_device_roles(self):
        alice, bob = self.new_user("alice"), self.new_user("bob")
        reg, _ = self.active_device(alice)
        did = reg["device_id"]
        self.devs.grant_access(alice, did, bob.public_id, "viewer")
        self.assertEqual(len(self.devs.list_devices(bob)["devices"]), 1)
        with self.assertRaises(errors.Forbidden):
            self.devs.rotate_credential(bob, did, "password1")
        with self.assertRaises(errors.Forbidden):
            self.devs.list_events(bob, did, include_payload=True)
        with self.assertRaises(errors.Forbidden):
            self.devs.latest_state(bob, did)
        with self.assertRaises(errors.NotFound):
            self.devs.validate_user_device(bob, did)  # viewer cannot act via device
        self.devs.grant_access(alice, did, bob.public_id, "operator")
        self.assertEqual(self.devs.validate_user_device(bob, did), did)
        self.devs.revoke_access(alice, did, bob.public_id)
        self.assertEqual(self.devs.list_devices(bob)["devices"], [])

    def test_last_owner_protected(self):
        alice = self.new_user("alice")
        reg, _ = self.active_device(alice)
        with self.assertRaises(errors.Conflict):
            self.devs.revoke_access(alice, reg["device_id"], alice.public_id)
        with self.assertRaises(errors.Conflict):
            self.devs.grant_access(alice, reg["device_id"], alice.public_id, "viewer")

    def test_rotate_requires_step_up_and_invalidates_old(self):
        alice = self.new_user("alice")
        reg, _ = self.active_device(alice)
        old = reg["credential"]["token"]
        with self.assertRaises(errors.Forbidden):
            self.devs.rotate_credential(alice, reg["device_id"], "wrongpass")
        new = self.devs.rotate_credential(alice, reg["device_id"], "password1")["credential"]["token"]
        with self.assertRaises(errors.Unauthorized):
            self.devs.authenticate_credential(old)
        self.assertEqual(self.devs.authenticate_credential(new).device_id, reg["device_id"])

    def test_revoke_blocks_device_and_is_terminal(self):
        alice = self.new_user("alice")
        reg, dp = self.active_device(alice)
        self.devs.revoke_device(alice, reg["device_id"])
        with self.assertRaises(errors.Unauthorized):
            self.devs.authenticate_credential(reg["credential"]["token"])
        with self.assertRaises(errors.Unauthorized):
            self.devs.heartbeat(dp, reg["device_id"])
        with self.assertRaises(errors.Conflict):
            self.devs.rotate_credential(alice, reg["device_id"], "password1")
        self.assertFalse(can_transition("revoked", "active"))
        self.devs.retire_device(alice, reg["device_id"])
        self.assertEqual(store.get_device(reg["device_id"])["status"], "retired")

    def test_heartbeat_activates_and_checks_path(self):
        alice = self.new_user("alice")
        reg = self.devs.register_device(alice, "p", "linux", "laptop")
        dp = self.devs.authenticate_credential(reg["credential"]["token"])
        with self.assertRaises(errors.Forbidden):
            self.devs.heartbeat(dp, str(uuid.uuid4()))
        out = self.devs.heartbeat(dp, reg["device_id"], client_version="1.2",
                                  capabilities=["a"], capability_status={"a": "permission_denied"})
        self.assertEqual(out["status"], "active")
        device = store.get_device(reg["device_id"])
        self.assertEqual(device["capability_status"], {"a": "permission_denied"})
        with self.assertRaises(errors.ValidationFailed):
            self.devs.heartbeat(dp, reg["device_id"], capability_status={"a": "bogus"})

    def test_expired_credential_rejected(self):
        alice = self.new_user("alice")
        reg = self.devs.register_device(alice, "p", "linux", "laptop")
        with database.transaction() as conn:
            conn.execute("UPDATE device_credentials SET expires_at = ?",
                         ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
        with self.assertRaises(errors.Unauthorized):
            self.devs.authenticate_credential(reg["credential"]["token"])

    def test_admin_fleet_and_get_device(self):
        alice = self.new_user("alice")
        reg, _ = self.active_device(alice)
        fleet = self.devs.list_fleet(self.admin)
        self.assertTrue(any(d["device_id"] == reg["device_id"] for d in fleet["devices"]))
        with self.assertRaises(errors.Forbidden):
            self.devs.list_fleet(alice)
        self.assertEqual(self.devs.get_device(self.admin, reg["device_id"])["device_id"], reg["device_id"])
        self.assertEqual(self.devs.list_devices(self.admin)["devices"], [])  # no implicit grant

    def test_audit_trail_for_device_operations(self):
        alice = self.new_user("alice")
        reg, _ = self.active_device(alice)
        self.devs.revoke_device(alice, reg["device_id"])
        actions = {a["action"] for a in database.list_audit(500)}
        self.assertTrue({"device.register", "device.activate", "device.revoke"} <= actions)


class IngestionTests(Base):
    def setUp(self):
        super().setUp()
        self.alice = self.new_user("alice")
        self.reg, self.dp = self.active_device(self.alice)
        self.did = self.reg["device_id"]

    def ingest(self, events, principal=None, path=None):
        return self.ing.ingest_sync(principal or self.dp, path or self.did, events)

    def test_accept_duplicate_and_conflict(self):
        e = ev()
        resp, eph, durable = self.ingest([e])
        self.assertEqual((resp["accepted"], resp["duplicates"], resp["rejected"]), (1, 0, 0))
        self.assertEqual(len(eph), 1)      # telemetry: delivered ephemerally
        self.assertFalse(durable)
        resp, eph, _ = self.ingest([e])    # retry is safe and has no second side effect
        self.assertEqual((resp["accepted"], resp["duplicates"]), (0, 1))
        self.assertEqual(eph, [])
        changed = dict(e, payload={"cpu": {"usage_percent": 99}})
        resp, _, _ = self.ingest([changed])
        self.assertEqual(resp["results"][0]["code"], "event_id_conflict")
        self.assertIn("events.id_conflict", {a["action"] for a in database.list_audit(100)})

    def test_provenance_resolved_by_server_not_payload(self):
        e = ev(payload={"actor_user_id": 1, "device_id": "someone-else", "x": 1})
        e["actor_user_id"] = 1            # extra claim at event level is ignored
        e["device_id"] = str(uuid.uuid4())
        self.ingest([e])
        row = store.list_events(self.did)[0]
        self.assertEqual(row["device_id"], self.did)
        self.assertIsNone(row["actor_user_id"])
        self.assertTrue(row["received_at"])
        self.assertEqual(row["source_component"], "hardware_sensor")

    def test_path_credential_mismatch_rejected(self):
        other, other_dp = self.active_device(self.alice, "other")
        with self.assertRaises(errors.Forbidden):
            self.ingest([ev()], path=other["device_id"])

    def test_privileged_types_denied(self):
        for t in ("user.message", "agent.response", "command.agent.run", "kernel.ready",
                  "system.shutdown", "autonomous.decision", "admin.x.y", "random.thing"):
            resp, _, _ = self.ingest([ev(t)])
            self.assertEqual(resp["results"][0]["code"], "type_not_allowed", t)

    def test_validation_errors_per_item(self):
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        batch = [ev(schema_version=9), ev(occurred_at="garbage"), ev(occurred_at=old),
                 ev(occurred_at=future), ev(event_id="nope"), ev(source_component=""),
                 ev(device_sequence=-1), ev(payload=[1]), "str", ev()]
        resp, _, _ = self.ingest(batch)
        self.assertEqual((resp["accepted"], resp["rejected"]), (1, 9))
        codes = [r.get("code") for r in resp["results"]]
        self.assertEqual(codes[:3], ["unsupported_schema_version", "invalid_timestamp", "invalid_timestamp"])

    def test_limits(self):
        self.policy.max_batch_size = 3
        with self.assertRaises(errors.PayloadTooLarge):
            self.ingest([ev() for _ in range(4)])
        with self.assertRaises(errors.ValidationFailed):
            self.ingest([])
        resp, _, _ = self.ingest([ev(payload={"blob": "x" * (70 * 1024)})])
        self.assertEqual(resp["results"][0]["code"], "payload_too_large")

    def test_rate_limit(self):
        tight = EventIngestionService(Policy(events_per_minute=5))
        tight.ingest_sync(self.dp, self.did, [ev() for _ in range(5)])
        with self.assertRaises(errors.RateLimited) as ctx:
            tight.ingest_sync(self.dp, self.did, [ev()])
        self.assertIn("Retry-After", ctx.exception.headers)

    def test_pending_and_revoked_devices_cannot_ingest(self):
        reg = self.devs.register_device(self.alice, "new", "linux", "laptop")
        pdp = self.devs.authenticate_credential(reg["credential"]["token"])
        with self.assertRaises(errors.Forbidden):
            self.ing.ingest_sync(pdp, reg["device_id"], [ev()])
        self.devs.revoke_device(self.alice, self.did)
        with self.assertRaises(errors.Unauthorized):
            self.ingest([ev()])

    def test_missing_scope(self):
        weak = SimpleNamespace(device_id=self.did, has_scope=lambda s: False, is_server_local=False)
        with self.assertRaises(errors.Forbidden):
            self.ing.ingest_sync(weak, self.did, [ev()])

    def test_telemetry_payload_not_retained_but_latest_state_is(self):
        self.ingest([ev(payload={"cpu": {"usage_percent": 42}})])
        row = store.list_events(self.did, include_payload=True)[0]
        self.assertIsNone(row["payload"])
        self.assertEqual(store.get_latest_state(self.did)[0]["payload"]["cpu"]["usage_percent"], 42)
        # clipboard: neither payload nor latest state
        self.ingest([ev("sensor.clipboard.changed", {"content": "secret"})])
        types_ = [s["event_type"] for s in store.get_latest_state(self.did)]
        self.assertNotIn("sensor.clipboard.changed", types_)
        with database.get_connection() as conn:
            dump = json.dumps([dict(r) for r in conn.execute("SELECT * FROM device_events")])
        self.assertNotIn("secret", dump)

    def test_durable_events_write_outbox_in_same_transaction(self):
        e = ev("device.process.snapshot", {"process_count": 73}, source_component="process-monitor")
        resp, eph, durable = self.ingest([e])
        self.assertTrue(durable)
        self.assertEqual(eph, [])
        rows = database.claim_outbox_events(10)
        self.assertEqual(len(rows), 1)
        payload = json.loads(rows[0]["payload"])
        self.assertEqual(payload["device_id"], self.did)
        self.assertIsNone(payload["actor_user_id"])
        self.assertEqual(payload["data"], {"process_count": 73})
        self.assertTrue(payload["verified"])
        # duplicate must not enqueue a second outbox row
        self.ingest([e])
        self.assertEqual(sum(database.outbox_counts().values()), 1)

    def test_payload_visible_only_to_owner_operator(self):
        bob = self.new_user("bob")
        self.ingest([ev("device.process.snapshot", {"process_count": 1})])
        self.devs.grant_access(self.alice, self.did, bob.public_id, "viewer")
        listed = self.devs.list_events(bob, self.did)["events"]
        self.assertEqual(len(listed), 1)
        self.assertNotIn("payload", listed[0])
        with_payload = self.devs.list_events(self.alice, self.did, include_payload=True)["events"][0]
        self.assertEqual(with_payload["payload"], {"process_count": 1})

    def test_event_pagination(self):
        for _ in range(5):
            self.ingest([ev()])
        page1 = self.devs.list_events(self.alice, self.did, limit=3)
        self.assertEqual(len(page1["events"]), 3)
        page2 = self.devs.list_events(self.alice, self.did, limit=3, cursor=page1["next_cursor"])
        self.assertEqual(len(page2["events"]), 2)
        ids = {e["event_id"] for e in page1["events"]} | {e["event_id"] for e in page2["events"]}
        self.assertEqual(len(ids), 5)

    def test_stats_and_retention_purge(self):
        self.ingest([ev(device_sequence=7), ev(event_type="user.message")])
        device = store.get_device(self.did)
        self.assertEqual(device["last_accepted_sequence"], 7)
        self.assertEqual(device["ingest_error_count"], 1)
        self.assertIsNotNone(device["last_event_at"])
        future = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
        self.assertGreaterEqual(store.purge_expired(future), 1)

    def test_batch_dispatch_callbacks(self):
        delivered, kicked = [], []

        async def dispatch(envelope):
            delivered.append(envelope)

        async def kick():
            kicked.append(1)

        svc = EventIngestionService(self.policy, dispatch=dispatch, kick_outbox=kick)
        run(svc.ingest(self.dp, self.did, [ev(), ev("device.x.y", {"a": 1})]))
        self.assertEqual(len(delivered), 1)
        self.assertEqual(delivered[0]["device_id"], self.did)
        self.assertEqual(kicked, [1])


class VisibilityTests(Base):
    def test_stream_acl(self):
        alice, bob = self.new_user("alice"), self.new_user("bob")
        reg, _ = self.active_device(alice)
        did = reg["device_id"]
        device_event = {"device_id": did, "data": {"secret": 1}, "type": "sensor.hardware.state"}
        a_cache, b_cache = AccessCache(alice.user_id), AccessCache(bob.user_id)
        self.assertEqual(authorize_event(device_event, alice.user_id, False, a_cache), device_event)
        self.assertIsNone(authorize_event(device_event, bob.user_id, False, b_cache))
        # viewer gets metadata only
        self.devs.grant_access(alice, did, bob.public_id, "viewer")
        b_cache.invalidate()
        seen = authorize_event(device_event, bob.user_id, False, b_cache)
        self.assertIsNone(seen["data"])
        self.assertTrue(seen["redacted"])
        # revocation takes effect after the cache refreshes
        self.devs.revoke_access(alice, did, bob.public_id)
        b_cache.invalidate()
        self.assertIsNone(authorize_event(device_event, bob.user_id, False, b_cache))
        # an admin has no implicit fleet-wide stream access
        admin_cache = AccessCache(self.admin.user_id)
        self.assertIsNone(authorize_event(device_event, self.admin.user_id, True, admin_cache))

    def test_user_addressed_and_system_events(self):
        alice, bob = self.new_user("alice"), self.new_user("bob")
        chat = {"type": "agent.response", "data": {"user_id": alice.user_id, "response": "hi"}}
        self.assertEqual(authorize_event(chat, alice.user_id, False, AccessCache(alice.user_id)), chat)
        self.assertIsNone(authorize_event(chat, bob.user_id, False, AccessCache(bob.user_id)))
        self.assertIsNone(authorize_event(chat, self.admin.user_id, True, AccessCache(self.admin.user_id)))
        system = {"type": "kernel.ready", "data": {}}
        self.assertIsNotNone(authorize_event(system, self.admin.user_id, True, AccessCache(1)))
        self.assertIsNone(authorize_event(system, bob.user_id, False, AccessCache(bob.user_id)))
        actor = {"type": "x", "actor_user_id": alice.user_id, "data": {}}
        self.assertIsNone(authorize_event(actor, bob.user_id, False, AccessCache(bob.user_id)))


class ServerAsDeviceTests(Base):
    def test_local_device_is_unique_owned_by_admins_and_ingests(self):
        mgr = LocalDeviceManager("Test Server")
        did = mgr.ensure()
        self.assertEqual(LocalDeviceManager("Other").ensure(), did)  # idempotent: one row
        device = store.get_server_local_device()
        self.assertTrue(device["is_server_local"])
        self.assertEqual(device["device_type"], "server")
        self.assertEqual(store.get_access(self.admin.user_id, did), "owner")
        alice = self.new_user("alice")
        self.assertIsNone(store.get_access(alice.user_id, did))   # users do not see it by default
        with self.assertRaises(errors.Conflict):
            self.devs.revoke_device(self.admin, did)

        ingestion = EventIngestionService(self.policy)
        dispatcher = LocalDeviceDispatcher(mgr, ingestion)
        event = SimpleNamespace(type="sensor.hardware.state", data={"cpu": {"usage_percent": 3}},
                                source="hardware_sensor", correlation_id=str(uuid.uuid4()),
                                causation_id=None)
        self.assertEqual(run(dispatcher.publish(event)), 1)
        row = store.list_events(did)[0]
        self.assertEqual(row["source_component"], "hardware_sensor")
        self.assertIsNone(row["actor_user_id"])
        # policy applies to the server too
        bad = SimpleNamespace(type="user.message", data={}, source="x",
                              correlation_id=str(uuid.uuid4()), causation_id=None)
        self.assertEqual(run(dispatcher.publish(bad)), 0)
        # file/clipboard events from server sensors are covered by the default policy
        for t in ("file.created", "sensor.clipboard.changed"):
            ok = SimpleNamespace(type=t, data={"path": "/tmp/x"}, source="s",
                                 correlation_id=str(uuid.uuid4()), causation_id=None)
            self.assertEqual(run(dispatcher.publish(ok)), 1, t)

    def test_new_admin_gets_server_device(self):
        mgr = LocalDeviceManager()
        did = mgr.ensure()
        self.users.create_user(self.admin, "admin2", "admin", "password1")
        mgr.sync_access()
        uid = database.get_user_by_username("admin2")["id"]
        self.assertEqual(store.get_access(uid, did), "owner")

    def test_share_with_all_users_option(self):
        alice = self.new_user("alice")
        mgr = LocalDeviceManager(share_with_all_users=True)
        did = mgr.ensure()
        self.assertEqual(store.get_access(alice.user_id, did), "viewer")


class DataScopeTests(Base):
    def test_device_scoped_memories_follow_grants(self):
        alice, bob = self.new_user("alice"), self.new_user("bob")
        reg, _ = self.active_device(alice)
        database.store_memory(None, "alice laptop is hot", device_id=reg["device_id"])
        database.store_memory(None, "global note")
        got = lambda u: {m["content"] for m in database.search_memories(u.user_id)}
        self.assertEqual(got(alice), {"alice laptop is hot", "global note"})
        self.assertEqual(got(bob), {"global note"})

    def test_messages_record_submitting_device(self):
        alice = self.new_user("alice")
        reg, _ = self.active_device(alice)
        cid = database.create_conversation(alice.user_id)
        msg = database.append_message(cid, alice.user_id, "user", "hi",
                                      created_by_device_id=reg["device_id"])
        rows = database.list_messages(cid, alice.user_id)
        self.assertEqual(rows[0]["created_by_device_id"], reg["device_id"])
        self.assertEqual(msg["created_by_device_id"], reg["device_id"])

    def test_conversation_isolation(self):
        alice, bob = self.new_user("alice"), self.new_user("bob")
        cid = database.create_conversation(alice.user_id)
        self.assertIsNone(database.get_conversation(cid, bob.user_id))
        self.assertEqual(database.list_conversations(bob.user_id), [])


class MiscTests(unittest.TestCase):
    def test_rate_limiter_refills(self):
        now = [0.0]
        rl = RateLimiter(60, burst=2, clock=lambda: now[0])
        self.assertTrue(rl.allow("k")[0])
        self.assertTrue(rl.allow("k")[0])
        ok, retry = rl.allow("k")
        self.assertFalse(ok)
        self.assertGreater(retry, 0)
        now[0] += 2
        self.assertTrue(rl.allow("k")[0])

    def test_policy_config_override(self):
        p = EventPolicy.from_config({"max_batch_size": 5, "types": [
            {"pattern": "custom.*", "class": "domain", "retention_hours": 1}]})
        self.assertEqual(p.max_batch_size, 5)
        self.assertIsNotNone(p.rule_for("custom.thing"))
        self.assertIsNone(p.rule_for("sensor.hardware.state"))
        self.assertIsNone(EventPolicy().rule_for("user.message"))


if __name__ == "__main__":
    unittest.main()
