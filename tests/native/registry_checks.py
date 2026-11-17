"""Validate registry writes and their recovery points on the actual Core owners."""

from typing import Any


async def exercise_registries(checks: Any, base: str) -> None:
    floor = await checks.call(
        "ha_set_area_or_floor",
        {"kind": "floor", "name": "Native registry floor", "level": 1},
    )
    assert floor["success"], floor
    floor_id = floor["floor_id"]
    area = await checks.call(
        "ha_set_area_or_floor",
        {"kind": "area", "name": "Native registry area", "floor_id": floor_id},
    )
    assert area["success"], area
    area_id = area["area_id"]
    updated = await checks.call(
        "ha_set_area_or_floor",
        {"kind": "area", "id": area_id, "aliases": ["Native alias"]},
    )
    assert updated["success"], updated
    locations = await checks.call("ha_list_floors_areas")
    selected = next(row for row in locations["floors"] if row["floor_id"] == floor_id)
    stored = next(row for row in selected["areas"] if row["area_id"] == area_id)
    assert stored["aliases"] == ["Native alias"], locations
    checks.passed("native_area_and_floor_writes_use_live_Core_registries")

    panel = base + "/api/ha_mcp_tools/ui/app/api/settings/backups"
    response = await checks.client.get(
        panel, params={"domain": "area_or_floor", "entity_id": "area:" + area_id}
    )
    response.raise_for_status()
    backups = response.json()["backups"]
    assert backups, response.json()
    restored = await checks.client.post(
        panel + "/" + backups[0]["name"] + "/restore", json={}
    )
    assert restored.status_code == 200, restored.text
    locations = await checks.call("ha_list_floors_areas")
    selected = next(row for row in locations["floors"] if row["floor_id"] == floor_id)
    stored = next(row for row in selected["areas"] if row["area_id"] == area_id)
    assert stored["aliases"] == [] and stored["floor_id"] == floor_id, locations
    checks.passed("native_area_restore_retains_original_floor_and_prewrite_fields")

    await exercise_location_ordering(checks, area_id, floor_id)

    category = await checks.call(
        "ha_config_set_category", {"scope": "script", "name": "Native category"}
    )
    assert category["success"], category
    category_id = category["category_id"]
    updated = await checks.call(
        "ha_config_set_category",
        {
            "scope": "script",
            "name": "Native category updated",
            "category_id": category_id,
        },
    )
    assert updated["success"], updated
    read = await checks.call(
        "ha_config_get_category", {"scope": "script", "category_id": category_id}
    )
    assert read["category"]["name"] == "Native category updated", read
    deleted = await checks.call(
        "ha_config_remove_category", {"scope": "script", "category_id": category_id}
    )
    assert deleted["success"], deleted
    checks.passed("native_scoped_category_create_update_read_and_remove")

    await exercise_labels(checks, base, area_id)

    for kind, identifier in (("area", area_id), ("floor", floor_id)):
        result = await checks.call(
            "ha_remove_area_or_floor", {"kind": kind, "id": identifier}
        )
        assert result["success"], result


async def exercise_labels(checks: Any, base: str, area_id: str) -> None:
    label = await checks.call(
        "ha_config_set_label",
        {"name": "Native label", "color": "blue", "areas": [area_id]},
    )
    assert label["success"] and label["assigned_areas"] == [area_id], label
    label_id = label["label_id"]
    updated = await checks.call(
        "ha_config_set_label", {"name": "Native label updated", "label_id": label_id}
    )
    assert updated["success"], updated
    read = await checks.call("ha_config_get_label", {"label_id": label_id})
    assert read["label"]["name"] == "Native label updated", read
    checks.passed("canonical_Core_label_service_creates_assigns_updates_and_reads")

    panel = base + "/api/ha_mcp_tools/ui/app/api/settings/backups"
    response = await checks.client.get(
        panel, params={"domain": "label", "entity_id": label_id}
    )
    response.raise_for_status()
    backups = response.json()["backups"]
    assert backups, response.json()
    restored = await checks.client.post(
        panel + "/" + backups[0]["name"] + "/restore", json={}
    )
    assert restored.status_code == 200, restored.text
    read = await checks.call("ha_config_get_label", {"label_id": label_id})
    assert read["label"]["name"] == "Native label", read
    removed = await checks.call("ha_config_remove_label", {"label_id": label_id})
    assert removed["success"], removed
    listed = await checks.call("ha_config_get_label")
    assert not any(row["label_id"] == label_id for row in listed["labels"]), listed
    checks.passed("canonical_Core_label_restore_and_removal_preserve_public_contract")

    recreated = await checks.call(
        "ha_config_set_label", {"name": "Native recreate original"}
    )
    previous_id = recreated["label_id"]
    await checks.call(
        "ha_config_set_label",
        {"label_id": previous_id, "name": "Native recreate renamed"},
    )
    await checks.call("ha_config_remove_label", {"label_id": previous_id})
    response = await checks.client.get(
        panel, params={"domain": "label", "entity_id": previous_id}
    )
    response.raise_for_status()
    saved = response.json()["backups"][0]["name"]
    restored = await checks.client.post(panel + "/" + saved + "/restore", json={})
    assert restored.status_code == 200, restored.text
    labels = (await checks.call("ha_config_get_label"))["labels"]
    matches = [row for row in labels if row["name"] == "Native recreate renamed"]
    assert len(matches) == 1 and matches[0]["label_id"] != previous_id, labels
    await checks.call("ha_config_remove_label", {"label_id": matches[0]["label_id"]})
    checks.passed(
        "native_deleted_label_recreation_keeps_Core_identity_and_public_backup_path"
    )


async def exercise_location_ordering(checks: Any, area_id: str, floor_id: str) -> None:
    floor = await checks.call("ha_set_area_or_floor", {"kind": "floor", "name": "Native reorder floor", "level": -1})
    second_floor = floor["floor_id"]
    area = await checks.call("ha_set_area_or_floor", {"kind": "area", "name": "Native reorder area", "floor_id": floor_id})
    second_area = area["area_id"]
    topology = await checks.call("ha_list_floors_areas")
    previous = [row["floor_id"] for row in topology["floors"]]
    order = list(reversed(previous))
    reordered = await checks.call("ha_set_area_or_floor", {"kind": "floor", "order": order})
    assert reordered["success"] and reordered["previous_order"] == previous, reordered
    listed = await checks.call("ha_list_floors_areas")
    assert [row["floor_id"] for row in listed["floors"]] == order, listed
    assert reordered["order"] == order and reordered["warnings"], reordered
    await checks.call("ha_set_area_or_floor", {"kind": "floor", "order": previous})
    checks.passed("native_floor_reorder_preserves_Core_order_and_previous_order")

    rows = [row for floor in listed["floors"] for row in floor["areas"]] + listed["unassigned_areas"] + listed["orphaned_areas"]
    order = list(reversed([row["area_id"] for row in rows]))
    reordered = await checks.call("ha_set_area_or_floor", {"kind": "area", "order": order})
    assert reordered["success"] and reordered["order"] == order, reordered
    listed = await checks.call("ha_list_floors_areas")
    parent = next(row for row in listed["floors"] if row["floor_id"] == floor_id)
    assert [row["area_id"] for row in parent["areas"] if row["area_id"] in {area_id, second_area}] == [second_area, area_id], parent
    await checks.call("ha_set_area_or_floor", {"kind": "area", "order": reordered["previous_order"]})
    checks.passed("native_area_reorder_uses_Core_owner_and_lists_group_order")

    await checks.call("ha_set_area_or_floor", {"kind": "floor", "id": second_floor, "level": None})
    await checks.call("ha_set_area_or_floor", {"kind": "floor", "id": second_floor, "name": "Native cleared floor"})
    listed = await checks.call("ha_list_floors_areas")
    assert next(row for row in listed["floors"] if row["floor_id"] == second_floor)["level"] is None, listed
    checks.passed("native_floor_null_clears_level_and_omission_keeps_it")
    await checks.call("ha_remove_area_or_floor", {"kind": "area", "id": second_area})
    await checks.call("ha_remove_area_or_floor", {"kind": "floor", "id": second_floor})