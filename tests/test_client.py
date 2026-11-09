"""Tests of the calls that succeed."""

from __future__ import annotations

from datetime import UTC, datetime

from alacart import AlacartClient, ItemOrder, MealType, NewMeal, RecipeSort

from .conftest import TOKEN, FakeApi, load_fixture


async def test_get_me_sends_the_token_and_reads_the_account(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/me", json_body=load_fixture("me"))

    me = await client.get_me()

    assert me.id == "481516"
    assert me.display_name == "Kim Andersson"
    assert me.premium_expires_at == datetime(2027, 3, 1, tzinfo=UTC)
    assert me.is_family_premium is True
    headers = api.sent("GET", "/v1/me").headers
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["Accept"] == "application/json"


async def test_get_stores_reads_stores_without_an_address(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/stores", json_body=load_fixture("stores"))

    stores = await client.get_stores()

    assert [store.name for store in stores] == ["Ica Kvantum Malmborgs", "Coop Triangeln"]
    assert stores[0].latitude == 55.5807
    assert stores[1].address is None
    assert stores[1].last_visited_at is None


async def test_get_item_lists_returns_the_etag(client: AlacartClient, api: FakeApi) -> None:
    api.answer(
        "GET", "/v1/item-lists", json_body=load_fixture("item_lists"), headers={"ETag": '"a1"'}
    )

    result = await client.get_item_lists()

    assert [item_list.name for item_list in result.item_lists] == ["Handla", "Bygghandeln"]
    assert result.item_lists[0].is_default is True
    assert result.etag == '"a1"'
    assert "If-None-Match" not in api.sent("GET", "/v1/item-lists").headers


async def test_get_item_lists_returns_none_when_not_modified(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/item-lists", status=304)

    assert await client.get_item_lists(etag='"a1"') is None
    assert api.sent("GET", "/v1/item-lists").headers["If-None-Match"] == '"a1"'


async def test_create_item_list_sends_only_the_given_fields(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("POST", "/v1/item-lists", status=201, json_body=load_fixture("item_list"))

    item_list = await client.create_item_list("Fest")

    assert item_list.id == "9003"
    assert api.sent("POST", "/v1/item-lists").json == {"name": "Fest"}


async def test_change_item_list_sends_the_changes(client: AlacartClient, api: FakeApi) -> None:
    api.answer("PATCH", "/v1/item-lists/9003", json_body=load_fixture("item_list"))

    await client.change_item_list("9003", is_private=False)

    assert api.sent("PATCH", "/v1/item-lists/9003").json == {"isPrivate": False}


async def test_delete_item_list(client: AlacartClient, api: FakeApi) -> None:
    api.answer("DELETE", "/v1/item-lists/9003", status=204)

    await client.delete_item_list("9003")
    api.sent("DELETE", "/v1/item-lists/9003")


async def test_get_sorted_items_reads_departments(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/item-lists/9001/sorted", json_body=load_fixture("sorted_items"))

    sorted_items = await client.get_sorted_items("9001", "2342")

    assert [[item.text for item in department] for department in sorted_items.departments] == [
        ["bananer"],
        ["2 l mjölk", "smör"],
    ]
    assert [item.text for item in sorted_items.unplaced_items] == ["present till mormor"]
    assert api.sent("GET", "/v1/item-lists/9001/sorted").query["storeId"] == "2342"


async def test_set_manual_order_sends_the_ids(client: AlacartClient, api: FakeApi) -> None:
    api.answer("PUT", "/v1/item-lists/9001/manual-order", status=204)

    await client.set_manual_order("9001", ("77003", "77002"))

    body = api.sent("PUT", "/v1/item-lists/9001/manual-order").json
    assert body == {"itemIds": ["77003", "77002"]}


async def test_get_items_reads_items_and_the_etag(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/items", json_body=load_fixture("items"), headers={"ETag": '"b2"'})

    result = await client.get_items()

    assert [item.text for item in result.items] == ["2 l mjölk", "bröd", "skruv 4x40"]
    assert result.items[1].is_checked is True
    assert result.items[2].is_permanent is True
    assert result.items[0].added_at == datetime(2026, 11, 8, 9, 12, 45, tzinfo=UTC)
    assert result.etag == '"b2"'
    assert len(api.sent("GET", "/v1/items").query) == 0


async def test_get_items_sends_the_list_order_and_etag(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/items", status=304)

    result = await client.get_items(list_id="9001", order=ItemOrder.MANUAL, etag='"b2"')

    assert result is None
    sent = api.sent("GET", "/v1/items")
    assert dict(sent.query) == {"listId": "9001", "order": "manual"}
    assert sent.headers["If-None-Match"] == '"b2"'


async def test_add_items_reads_merged_items(client: AlacartClient, api: FakeApi) -> None:
    api.answer("POST", "/v1/items", json_body=load_fixture("added_items"))

    added = await client.add_items(["ägg", "1 l mjölk"], list_id="9001")

    assert [entry.merged_into_existing for entry in added] == [False, True]
    assert added[1].item.text == "3 l mjölk"
    assert api.sent("POST", "/v1/items").json == {"texts": ["ägg", "1 l mjölk"], "listId": "9001"}


async def test_change_item_sends_only_the_given_fields(client: AlacartClient, api: FakeApi) -> None:
    api.answer("PATCH", "/v1/items/77003", json_body=load_fixture("item"))

    item = await client.change_item("77003", is_checked=True)

    assert item.is_checked is True
    assert api.sent("PATCH", "/v1/items/77003").json == {"isChecked": True}


async def test_remove_item(client: AlacartClient, api: FakeApi) -> None:
    api.answer("DELETE", "/v1/items/77003", status=204)

    await client.remove_item("77003")
    api.sent("DELETE", "/v1/items/77003")


async def test_ids_cannot_change_the_path(client: AlacartClient, api: FakeApi) -> None:
    api.answer("DELETE", "/v1/items/1%2F..%2Fme", status=204)

    await client.remove_item("1/../me")

    api.sent("DELETE", "/v1/items/1%2F..%2Fme")


async def test_get_favorite_items_and_suggestions_return_texts(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/items/favorites", json_body=load_fixture("favorites"))
    api.answer("GET", "/v1/items/suggestions", json_body=load_fixture("suggestions"))

    assert await client.get_favorite_items() == ["mjölk", "bröd", "bananer"]
    assert await client.get_item_suggestions("mj") == ["mjölk", "mjölkchoklad"]
    assert api.sent("GET", "/v1/items/suggestions").query["query"] == "mj"


async def test_search_recipe_box_sends_every_filter(client: AlacartClient, api: FakeApi) -> None:
    api.answer("GET", "/v1/recipe-box", json_body=load_fixture("recipe_search"))

    result = await client.search_recipe_box(
        query="pannkakor",
        tags=["snabbt", "barnvänligt"],
        sort=RecipeSort.MOST_COOKED,
        max_cooking_time=30,
        min_grade=4,
        cooked=True,
        own_recipes_only=False,
        limit=10,
        offset=20,
        include_cook_count=True,
        include_last_cooked_at=True,
    )

    assert result.total_count == 57
    assert result.recipes[0].cook_count == 12
    assert result.recipes[0].last_cooked_at == datetime(2026, 11, 1, 17, 30, tzinfo=UTC)
    assert result.recipes[1].grade is None
    assert result.recipes[1].last_cooked_at is None
    query = api.sent("GET", "/v1/recipe-box").query
    assert query.getall("tags") == ["snabbt", "barnvänligt"]
    assert {key: query.getone(key) for key in query if key != "tags"} == {
        "query": "pannkakor",
        "sort": "most_cooked",
        "maxCookingTime": "30",
        "minGrade": "4",
        "cooked": "true",
        "ownRecipesOnly": "false",
        "limit": "10",
        "offset": "20",
        "include": "cookCount,lastCookedAt",
    }


async def test_search_recipe_box_without_filters_sends_no_query(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/recipe-box", json_body=load_fixture("recipe_search"))

    await client.search_recipe_box()

    assert len(api.sent("GET", "/v1/recipe-box").query) == 0


async def test_get_recipe_leaves_out_fields_it_did_not_ask_for(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/recipe-box/5501", json_body=load_fixture("recipe"))

    recipe = await client.get_recipe("5501")

    assert recipe.title == "Pannkakor"
    assert recipe.portions == 4
    assert recipe.selected_portions == "5/2"
    assert recipe.ingredients[1] == "3 dl vetemjöl"
    assert recipe.advice is None
    assert recipe.cook_count is None


async def test_get_recipe_ingredients_sends_portions_and_list(
    client: AlacartClient, api: FakeApi
) -> None:
    path = "/v1/recipe-box/5501/ingredients"
    api.answer("GET", path, json_body=load_fixture("recipe_ingredients"))

    ingredients = await client.get_recipe_ingredients("5501", portions=2, list_id="9001")

    assert [(i.text, i.probably_needed) for i in ingredients] == [
        ("3 dl vetemjöl", True),
        ("salt", False),
    ]
    assert dict(api.sent("GET", path).query) == {"portions": "2", "listId": "9001"}


async def test_add_recipe_sends_the_recipe(client: AlacartClient, api: FakeApi) -> None:
    api.answer("POST", "/v1/recipe-box", status=201, json_body=load_fixture("recipe_summary"))

    summary = await client.add_recipe("Kladdkaka", ["2 ägg", "3 dl socker"], tags=["dessert"])

    assert summary.id == "5503"
    assert api.sent("POST", "/v1/recipe-box").json == {
        "title": "Kladdkaka",
        "ingredients": ["2 ägg", "3 dl socker"],
        "tags": ["dessert"],
    }


async def test_import_recipe_tells_a_new_recipe_from_a_known_one(
    client: AlacartClient, api: FakeApi
) -> None:
    path = "/v1/recipe-box/import"
    api.answer("POST", path, status=201, json_body=load_fixture("recipe_summary"))
    api.answer("POST", path, status=200, json_body=load_fixture("recipe_summary"))

    first = await client.import_recipe("https://example.com/kladdkaka")
    second = await client.import_recipe("https://example.com/kladdkaka")

    assert (first.created, second.created) == (True, False)
    assert first.recipe.title == "Kladdkaka"
    assert api.requests[0].json == {"url": "https://example.com/kladdkaka"}


async def test_delete_recipe(client: AlacartClient, api: FakeApi) -> None:
    api.answer("DELETE", "/v1/recipe-box/5503", status=204)

    await client.delete_recipe("5503")
    api.sent("DELETE", "/v1/recipe-box/5503")


async def test_get_active_meal_plan_reads_both_meal_types(
    client: AlacartClient, api: FakeApi
) -> None:
    api.answer("GET", "/v1/meal-plans/active", json_body=load_fixture("meal_plan"))

    meals = await client.get_active_meal_plan(include_ingredients=True)

    assert [meal.type for meal in meals] == [MealType.RECIPE, MealType.TITLE]
    assert meals[0].ingredients == ["3 dl vetemjöl", "6 dl mjölk", "3 ägg"]
    assert meals[1].recipe_id is None
    assert meals[1].ingredients == []
    assert dict(api.sent("GET", "/v1/meal-plans/active").query) == {"include": "ingredients"}


async def test_add_meals_sends_each_meal(client: AlacartClient, api: FakeApi) -> None:
    path = "/v1/meal-plans/active/meals"
    api.answer("POST", path, status=201, json_body=load_fixture("added_meals"))

    meals = await client.add_meals(
        [NewMeal(recipe_id="5502", ingredients=["2 dl röda linser"], occasion="söndag")]
    )

    assert meals[0].occasion == "söndag"
    assert meals[0].ingredients is None
    assert api.sent("POST", path).json == {
        "meals": [
            {
                "type": "recipe",
                "recipeId": "5502",
                "ingredients": ["2 dl röda linser"],
                "occasion": "söndag",
            }
        ]
    }


async def test_change_meal_sends_only_the_given_fields(client: AlacartClient, api: FakeApi) -> None:
    path = "/v1/meal-plans/active/meals/3301"
    api.answer("PATCH", path, json_body=load_fixture("meal"))

    meal = await client.change_meal("3301", portions="3", occasion="lördag")

    assert meal.portions == "3"
    assert api.sent("PATCH", path).json == {"portions": "3", "occasion": "lördag"}


async def test_remove_meal(client: AlacartClient, api: FakeApi) -> None:
    api.answer("DELETE", "/v1/meal-plans/active/meals/3301", status=204)

    await client.remove_meal("3301")
    api.sent("DELETE", "/v1/meal-plans/active/meals/3301")


async def test_fields_and_values_from_a_later_release_do_not_break_parsing(
    client: AlacartClient, api: FakeApi
) -> None:
    meal = {**load_fixture("meal"), "type": "takeaway", "restaurant": "Pizzeria Napoli"}
    api.answer("GET", "/v1/meal-plans/active", json_body={"meals": [meal], "nextPage": None})

    meals = await client.get_active_meal_plan()

    assert meals[0].type == "takeaway"


async def test_create_item_list_can_make_it_private(client: AlacartClient, api: FakeApi) -> None:
    api.answer("POST", "/v1/item-lists", status=201, json_body=load_fixture("item_list"))

    await client.create_item_list("Fest", is_private=True)

    assert api.sent("POST", "/v1/item-lists").json == {"name": "Fest", "isPrivate": True}


async def test_change_item_list_can_rename(client: AlacartClient, api: FakeApi) -> None:
    api.answer("PATCH", "/v1/item-lists/9003", json_body=load_fixture("item_list"))

    await client.change_item_list("9003", name="Kalas")

    assert api.sent("PATCH", "/v1/item-lists/9003").json == {"name": "Kalas"}


async def test_get_recipe_asks_for_the_optional_fields(client: AlacartClient, api: FakeApi) -> None:
    recipe = {**load_fixture("recipe"), "cookCount": 3, "lastCookedAt": "2026-10-01T18:00:00Z"}
    api.answer("GET", "/v1/recipe-box/5501", json_body=recipe)

    result = await client.get_recipe("5501", include_cook_count=True, include_last_cooked_at=True)

    assert result.cook_count == 3
    assert result.last_cooked_at == datetime(2026, 10, 1, 18, tzinfo=UTC)
    query = api.sent("GET", "/v1/recipe-box/5501").query
    assert dict(query) == {"include": "cookCount,lastCookedAt"}


async def test_add_meals_sends_portions_and_list(client: AlacartClient, api: FakeApi) -> None:
    path = "/v1/meal-plans/active/meals"
    api.answer("POST", path, status=201, json_body=load_fixture("added_meals"))

    await client.add_meals([NewMeal(recipe_id="5502", ingredients=[], portions="3/2", list_id="9")])

    assert api.sent("POST", path).json == {
        "meals": [
            {
                "type": "recipe",
                "recipeId": "5502",
                "ingredients": [],
                "portions": "3/2",
                "listId": "9",
            }
        ]
    }


async def test_change_meal_marks_it_bought_and_cooked(client: AlacartClient, api: FakeApi) -> None:
    path = "/v1/meal-plans/active/meals/3301"
    api.answer("PATCH", path, json_body=load_fixture("meal"))
    api.answer("PATCH", path, json_body=load_fixture("meal"))

    await client.change_meal("3301", is_purchased=True)
    await client.change_meal("3301", is_cooked=True)

    assert [request.json for request in api.requests] == [
        {"isPurchased": True},
        {"isCooked": True},
    ]


async def test_change_item_sends_every_field(client: AlacartClient, api: FakeApi) -> None:
    api.answer("PATCH", "/v1/items/77003", json_body=load_fixture("item"))

    await client.change_item(
        "77003", text="1 l mjölk", list_id="9002", is_permanent=True, is_checked=False
    )

    assert api.sent("PATCH", "/v1/items/77003").json == {
        "text": "1 l mjölk",
        "listId": "9002",
        "isPermanent": True,
        "isChecked": False,
    }


async def test_add_recipe_sends_every_field(client: AlacartClient, api: FakeApi) -> None:
    api.answer("POST", "/v1/recipe-box", status=201, json_body=load_fixture("recipe_summary"))

    await client.add_recipe(
        "Kladdkaka",
        ["2 ägg"],
        instructions="Grädda.",
        portions=8,
        description="Kladdig.",
        tags=[],
    )

    assert api.sent("POST", "/v1/recipe-box").json == {
        "title": "Kladdkaka",
        "ingredients": ["2 ägg"],
        "instructions": "Grädda.",
        "portions": 8,
        "description": "Kladdig.",
        "tags": [],
    }
