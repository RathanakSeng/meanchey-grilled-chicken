"""Preparation access: registry levels and defaults, backfill, staff Off / View only / Record,
supervisors (Record, no reopen / cancel until management Full), the supervisor cap for staff,
and the alerts (recipients = holders of preparation.update, repeat after reopen, texts)."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.bootstrap import bootstrap
from app.bot import notify
from app.bot.runtime import TelegramRuntime
from app.bot.setup import create_bot, create_dispatcher
from app.config import get_settings
from app.main import app
from app.models import Language, Notification, Permission, Role, UserPermission
from app.permissions import registry
from tests.conftest import assert_error, auth
from tests.telegram_fakes import RecordingSession
from tests.test_preparations import SATAY_LINES, Prep, add_stock, materials
from tests.test_production import ok

ALL_CODES = ("preparation.view", "preparation.create", "preparation.update", "preparation.cancel")
MINI_APP = "https://meanchey.example.com"


@pytest.fixture
async def gm(make_user):
    return await make_user(Role.GENERAL_MANAGER, telegram_user_id=2001)


@pytest.fixture
async def stocked(client, gm) -> dict[str, dict]:
    ms = await materials(client, gm)
    await add_stock(client, gm, ms["Satay sauce"], "5000")
    await add_stock(client, gm, ms["Zip bag 7 (2-piece packs)"], "2")
    await add_stock(client, gm, ms["Zip bag 7 (4-piece packs)"], "2")
    await add_stock(client, gm, ms["String"], "5")
    await add_stock(client, gm, ms["Skewer"], "5")
    return ms


async def _level(client, grantor, user, feature: str, level: str):
    return await client.put(
        f"/users/{user.id}/features/{feature}", json={"level": level}, headers=auth(grantor)
    )


# --- Registry, defaults, backfill ----------------------------------------------------------------


def test_registry_levels_and_defaults() -> None:
    f = registry.FEATURES_BY_CODE
    assert f["preparation"].menu == "workstation"
    assert f["preparation"].level_map == {
        "off": frozenset(),
        "view": {"preparation.view"},
        "record": {"preparation.view", "preparation.create"},
    }
    assert f["preparation_management"].level_map == {
        "off": frozenset(),
        "full": {"preparation.update", "preparation.cancel"},
    }
    assert Role.STAFF in f["preparation"].applies_to
    assert Role.STAFF not in f["preparation_management"].applies_to
    defaults = registry.DEFAULT_PERMISSIONS
    assert set(ALL_CODES) <= defaults[Role.GENERAL_MANAGER]
    assert {c for c in defaults[Role.SUPERVISOR] if c.startswith("preparation.")} == {
        "preparation.view",
        "preparation.create",
    }
    assert not {c for c in defaults[Role.STAFF] if c.startswith("preparation.")}


async def test_backfill_follows_the_defaults(session, make_user) -> None:
    gm = await make_user(Role.GENERAL_MANAGER)
    sup = await make_user(Role.SUPERVISOR)
    staff = await make_user(Role.STAFF)
    await session.execute(
        delete(UserPermission).where(UserPermission.permission_code.in_(ALL_CODES))
    )
    await session.execute(delete(Permission).where(Permission.code.in_(ALL_CODES)))
    await session.commit()

    await bootstrap(session)

    async def held(user) -> set[str]:
        return set(
            await session.scalars(
                select(UserPermission.permission_code).where(
                    UserPermission.user_id == user.id,
                    UserPermission.permission_code.in_(ALL_CODES),
                )
            )
        )

    assert await held(gm) == set(ALL_CODES)
    assert await held(sup) == {"preparation.view", "preparation.create"}
    assert await held(staff) == set()


async def test_gm_levels_read_record_and_full(client, gm, superadmin) -> None:
    features = ok(await client.get(f"/users/{gm.id}/features", headers=auth(superadmin)))
    levels = {f["code"]: f["current_level"] for menu in features["menus"] for f in menu["features"]}
    assert levels["preparation"] == "record"
    assert levels["preparation_management"] == "full"


# --- Access per level ----------------------------------------------------------------------------


async def test_staff_off_view_record(client, gm, make_user, stocked) -> None:
    staff = await make_user(Role.STAFF)
    assert_error(await client.get("/preparations", headers=auth(staff)), 403, "MISSING_PERMISSION")
    ok(await _level(client, gm, staff, "preparation", "view"))
    assert ok(await client.get("/preparations", headers=auth(staff)))["total"] == 0
    ok(await client.get("/preparations/stats", headers=auth(staff)))
    r = await client.post("/preparations", json={"type": "satay_sachet"}, headers=auth(staff))
    assert_error(r, 403, "MISSING_PERMISSION")
    r = await client.get("/preparations/material-options", headers=auth(staff))
    assert_error(r, 403, "MISSING_PERMISSION")
    ok(await _level(client, gm, staff, "preparation", "record"))
    p = await Prep(client, staff).finished("satay_sachet", SATAY_LINES)
    assert p["status"] == "finished"
    # Management isn't applicable to staff.
    r = await _level(client, gm, staff, "preparation_management", "full")
    assert_error(r, 422, "FEATURE_NOT_APPLICABLE")
    assert_error(await Prep(client, staff).action(p, "reopen"), 403, "MISSING_PERMISSION")


async def test_supervisor_record_then_management(client, gm, make_user, stocked) -> None:
    sup = await make_user(Role.SUPERVISOR)
    prep = Prep(client, sup)
    p = await prep.finished("satay_sachet", SATAY_LINES)
    assert_error(await prep.action(p, "reopen"), 403, "MISSING_PERMISSION")
    assert_error(await prep.action(p, "cancel", reason="x"), 403, "MISSING_PERMISSION")
    ok(await _level(client, gm, sup, "preparation_management", "full"))
    p = ok(await prep.action(p, "reopen"))
    ok(await prep.action(p, "cancel", reason="Mistake"))


async def test_supervisor_cap_for_staff(client, gm, make_user) -> None:
    sup = await make_user(Role.SUPERVISOR)  # Preparation Record, with Staff access
    staff = await make_user(Role.STAFF)
    ok(await _level(client, sup, staff, "preparation", "record"))
    other = await make_user(Role.STAFF)
    ok(await _level(client, gm, sup, "preparation", "view"))
    r = await _level(client, sup, other, "preparation", "record")
    assert_error(r, 403, "PERMISSION_NOT_HELD")
    ok(await _level(client, sup, other, "preparation", "view"))


# --- Alerts --------------------------------------------------------------------------------------


async def _rows(session, **where) -> list[Notification]:
    stmt = (
        select(Notification)
        .where(Notification.type == "preparation.finished")
        .order_by(Notification.created_at, Notification.id)
        .execution_options(populate_existing=True)
    )
    for key, value in where.items():
        stmt = stmt.where(getattr(Notification, key) == value)
    return list(await session.scalars(stmt))


async def test_recipients_and_repeat(session, client, gm, superadmin, make_user, stocked) -> None:
    sup = await make_user(Role.SUPERVISOR)
    manager_sup = await make_user(Role.SUPERVISOR)
    ok(await _level(client, gm, manager_sup, "preparation_management", "full"))
    staff = await make_user(Role.STAFF)
    ok(await _level(client, gm, staff, "preparation", "record"))
    p = await Prep(client, staff).finished("satay_sachet", SATAY_LINES)
    rows = await _rows(session, entity_id=uuid.UUID(p["id"]))
    assert {r.user_id for r in rows} == {gm.id, superadmin.id, manager_sup.id}
    assert sup.id not in {r.user_id for r in rows}
    payload = rows[0].payload
    assert payload["code"] == p["code"] and payload["sachets_2"] == 40
    assert payload["sachets_4"] == 25 and payload["repeat"] is False
    assert payload["actor_id"] == str(staff.id)
    # A refused Finish stores nothing; a re-finish after reopen says "again".
    p = ok(await Prep(client, gm).action(p, "reopen"))
    p = ok(await Prep(client, gm).action(p, "finish"))
    rows = await _rows(session, user_id=gm.id)
    assert [r.payload["repeat"] for r in rows] == [False, True]
    bell = ok(await client.get("/notifications", headers=auth(gm)))
    item = next(i for i in bell["items"] if i["type"] == "preparation.finished")
    assert item["entity_type"] == "preparation" and "actor_id" not in item["payload"]


async def test_no_alert_when_finish_is_refused(session, client, gm) -> None:
    p = await Prep(client, gm).create("satay_sachet")
    p = ok(
        await Prep(client, gm).save(
            p, lines=[{"pack_size": 2, "satay_g": "1", "zip_bag_qty": "0.1", "sachets": 1}]
        )
    )
    assert_error(await Prep(client, gm).action(p, "finish"), 409, "INVENTORY_INSUFFICIENT")
    assert await _rows(session) == []


@pytest.fixture
def webhook_bot(monkeypatch):
    tg = RecordingSession()
    monkeypatch.setattr(get_settings(), "bot_mode", "webhook")
    monkeypatch.setattr(get_settings(), "mini_app_url", MINI_APP)
    app.state.telegram = TelegramRuntime(
        bot=create_bot(session=tg), dp=create_dispatcher(), secret="s"
    )
    yield tg
    app.state.telegram = None


async def test_telegram_text_and_button(session, client, gm, stocked, webhook_bot) -> None:
    lines = [
        {"material_id": stocked["Skewer"]["id"], "quantity": "2"},
        {"material_id": stocked["String"]["id"], "quantity": "0.5"},
    ]
    p = await Prep(client, gm).finished("packaging_material", lines)
    sent = [m for m in webhook_bot.calls("SendMessage") if m.chat_id == gm.telegram_user_id]
    assert len(sent) == 1
    # Khmer is the default language.
    assert sent[0].text == (
        f"🧂 <b>{p['code']}</b>៖ ការរៀបចំបានបញ្ចប់ — ចង្កាក់ 2.000 គ.ក, ខ្សែ 0.500 គ.ក។"
    )
    button = sent[0].reply_markup.inline_keyboard[0][0]
    assert button.web_app.url == f"{MINI_APP}/workstation/preparations/{p['id']}"
    assert {r.telegram_status for r in await _rows(session, user_id=gm.id)} == {"sent"}


def test_english_texts() -> None:
    def row(**payload) -> Notification:
        return Notification(
            type="preparation.finished",
            entity_type="preparation",
            entity_id="00000000-0000-0000-0000-000000000001",
            payload={"code": "PP-20261006-001", **payload},
        )

    cases = [
        (
            row(sachets_2=40, sachets_4=25, materials=[]),
            "🧂 <b>PP-20261006-001</b>: preparation finished — 40 satay sachets (2-piece), "
            "25 (4-piece).",
        ),
        (
            row(sachets_2=None, sachets_4=10, materials=[], repeat=True),
            "🧂 <b>PP-20261006-001</b>: preparation finished again — 10 satay sachets (4-piece).",
        ),
        (
            row(
                materials=[
                    {"name_en": "Skewer", "name_km": "x", "quantity": "2.000", "unit": "kg"},
                    {"name_en": "Tape <A>", "name_km": "x", "quantity": "5", "unit": "count"},
                    {"name_en": "Glue", "name_km": "x", "quantity": "10.5", "unit": "g"},
                ]
            ),
            "🧂 <b>PP-20261006-001</b>: preparation finished — Skewer 2.000 kg, Tape &lt;A&gt; 5, "
            "Glue 10.5 g.",
        ),
    ]
    for notification, expected in cases:
        text, keyboard = notify.message_for(notification, Language.EN)
        assert text == expected
        assert keyboard is None  # MINI_APP_URL isn't HTTPS in tests
